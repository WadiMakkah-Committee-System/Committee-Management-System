"""
البنود المستخرجة من مسودة الاجتماع وتحويلها لمهام/قرارات.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import gemini_client
from app.models.decision import Decision, DecisionClassification
from app.models.meeting_draft import MeetingDraft, MeetingDraftStatus
from app.models.meeting_extracted_item import MeetingExtractedItem, MeetingExtractedItemStatus
from app.models.task import Task
from app.models.user import User
from app.services import decision_service, task_service
from app.services.meeting_service.access import _require_access
from app.services.meeting_service.errors import ExtractedItemNotFoundError, MeetingValidationError
from app.services.meeting_service.loading import load_meeting


# ============================== البنود المستخرجة من الاجتماع ==============================
# FR-TASK-005 إلى FR-TASK-012 + FR-DEC-001 إلى FR-DEC-004 (§4.2/§5.2 SRS،
# UC2-UC9 بجدول حالات الاستخدام) — راجعي رأس app/models/meeting_extracted_item.py
# للتصميم الكامل. شاشة ترياج واحدة بصفحة تفاصيل الاجتماع (قرار موثّق مع
# صاحبة المشروع 2026-09-07 — SRS يذكرها تحت فصلي المهام والقرارات معًا
# بدون فصل UI صريح، فاعتُمدت شاشة واحدة مشتركة تفاديًا لازدواج/تزامن
# الحالة بين مرآتين منفصلتين).
#
# صلاحيات: الاستخراج/الإضافة اليدوية/الحذف تتطلب meetings.draft.summarize
# (نفس صلاحية توليد المسودة — إجراء ذكاء اصطناعي/إداري على مستوى
# الاجتماع، رئيس اللجنة فعليًا). "التعيين" كمهمة/قرار لا يتطلب صلاحية
# إضافية هنا صراحة — يُفوَّض بالكامل لـtask_service.create_task/
# decision_service.create_decision (كل منهما يتحقق من tasks.create/
# decisions.create بنفسه، ويرجع السجل المُنشأ مباشرة) تفاديًا لازدواج
# فحص الصلاحية أو إعادة استعلامه.


async def _list_extracted_items_query(
    db: AsyncSession, meeting_id: uuid.UUID
) -> list[MeetingExtractedItem]:
    result = await db.execute(
        select(MeetingExtractedItem)
        .where(MeetingExtractedItem.meeting_id == meeting_id)
        .order_by(MeetingExtractedItem.created_at)
    )
    return list(result.scalars().all())


async def list_extracted_items(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID
) -> list[MeetingExtractedItem]:
    """يتطلب meetings.draft.view حصرًا (رئيس اللجنة فعليًا).

    ملاحظة دمج 2026-09-21: لاما وسّعت هذا الشرط (490c772) ليقبل
    ai_items.view أيضًا فيصير عضو اللجنة العادي يشوف البنود المستخرجة —
    عند حل تعارض الدمج مع main تأكدت مع صاحبة المشروع (لجين) صراحةً وقالت
    "البنود المستخرجة بس لرئيس اللجنة"، فرجّعت الشرط لمتطلب meetings.draft.view
    فقط. صلاحية ai_items.view تبقى ممنوحة لدور عضو اللجنة بقاعدة البيانات
    (migration 0035) لكنها غير مُنفَذة هنا عمدًا — لو احتجنا تفعيلها لاحقًا
    يكفي إعادة ai_items.view لقائمة الأكواد أدناه عبر _has_any_access."""
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_access(
        db, actor, committee, "meetings.draft.view", "ليست لديك صلاحية عرض بنود هذا الاجتماع"
    )
    return await _list_extracted_items_query(db, meeting_id)


async def extract_meeting_items(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID
) -> list[MeetingExtractedItem]:
    """FR-TASK-005/UC2: يستخرج بنودًا جديدة من ملخص المسودة المولَّدة
    بالذكاء الاصطناعي (شرط أن تكون مكتملة). كل استدعاء يضيف دفعة جديدة
    بدون حذف/دمج مع البنود السابقة — لا يوجد شرط Idempotency موثّق بـSRS؛
    رئيس اللجنة يحذف يدويًا أي بند مكرر (FR-TASK-009)."""
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_access(
        db,
        actor,
        committee,
        "meetings.draft.summarize",
        "ليست لديك صلاحية استخراج بنود من مسودة هذا الاجتماع",
    )

    result = await db.execute(select(MeetingDraft).where(MeetingDraft.meeting_id == meeting_id))
    draft = result.scalar_one_or_none()
    if draft is None or draft.status != MeetingDraftStatus.completed or not draft.summary:
        raise MeetingValidationError(
            "يلزم توليد ملخص الاجتماع بالذكاء الاصطناعي أولًا قبل استخراج البنود"
        )

    texts = await gemini_client.extract_meeting_items(summary=draft.summary)
    for text in texts:
        db.add(
            MeetingExtractedItem(
                meeting_id=meeting_id,
                text=text,
                source="ai",
                status=MeetingExtractedItemStatus.pending,
                created_by=actor.user_id,
            )
        )
    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    result = await _list_extracted_items_query(db, meeting_id)
    await db.commit()
    return result


async def add_manual_extracted_item(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, text: str
) -> MeetingExtractedItem:
    """FR-TASK-007/UC4: إضافة بند يدوي لقائمة البنود المعروضة."""
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_access(
        db,
        actor,
        committee,
        "meetings.draft.summarize",
        "ليست لديك صلاحية إضافة بند لهذا الاجتماع",
    )
    item = MeetingExtractedItem(
        meeting_id=meeting_id,
        text=text,
        source="manual",
        status=MeetingExtractedItemStatus.pending,
        created_by=actor.user_id,
    )
    db.add(item)
    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    await db.refresh(item)
    await db.commit()
    return item


async def _load_extracted_item(db: AsyncSession, item_id: uuid.UUID) -> MeetingExtractedItem:
    result = await db.execute(
        select(MeetingExtractedItem).where(MeetingExtractedItem.item_id == item_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise ExtractedItemNotFoundError("البند المستخرج غير موجود")
    return item


async def delete_extracted_item(db: AsyncSession, *, actor: User, item_id: uuid.UUID) -> None:
    """FR-TASK-009/UC6: يزيل البند نهائيًا بدون تحويله لمهمة أو قرار —
    متاح فقط طالما البند لم يُعيَّن بعد (pending)."""
    item = await _load_extracted_item(db, item_id)
    meeting = await load_meeting(db, item.meeting_id)
    committee = meeting.committee
    await _require_access(
        db,
        actor,
        committee,
        "meetings.draft.summarize",
        "ليست لديك صلاحية حذف بنود هذا الاجتماع",
    )
    if item.status != MeetingExtractedItemStatus.pending:
        raise MeetingValidationError("لا يمكن حذف بند تم تحويله بالفعل إلى مهمة أو قرار")
    await db.delete(item)
    await db.commit()


async def assign_extracted_item_as_task(
    db: AsyncSession,
    *,
    actor: User,
    item_id: uuid.UUID,
    title: str | None,
    start_date,
    end_date,
    assignee_user_id: uuid.UUID,
) -> tuple[MeetingExtractedItem, Task]:
    """FR-TASK-010/011/UC7/UC8: يحوّل البند إلى مهمة حقيقية عبر
    task_service.create_task (يتحقق من tasks.create والعضوية بنفسه، ويرجع
    المهمة المُنشأة مباشرة)، ثم يربط البند بها.

    تُرجع (البند، المهمة) معًا — وليس البند فقط — عشان طبقة الـAPI
    (meetings.assign_extracted_item_as_task) تقدر تُطلِق
    notification_service.notify_task_created على المهمة المُنشأة، بنفس
    ما يصير بمسار الإنشاء العادي POST /tasks؛ هذا المسار (تعيين بند
    كمهمة) كان يتخطى tasks.py بالكامل فيفوّت الإشعار قبل هذا الإصلاح
    (قرار موثّق مع لجينـ 2026-09-09).
    """
    item = await _load_extracted_item(db, item_id)
    if item.status != MeetingExtractedItemStatus.pending:
        raise MeetingValidationError("هذا البند مُصنَّف مسبقًا")
    meeting = await load_meeting(db, item.meeting_id)

    task = await task_service.create_task(
        db,
        actor=actor,
        committee_id=meeting.committee_id,
        title=(title or item.text),
        start_date=start_date,
        end_date=end_date,
        assignee_user_id=assignee_user_id,
    )
    item.status = MeetingExtractedItemStatus.assigned_task
    item.linked_task_id = task.task_id
    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    await db.refresh(item)
    await db.commit()
    return item, task


async def assign_extracted_item_as_decision(
    db: AsyncSession,
    *,
    actor: User,
    item_id: uuid.UUID,
    title: str | None,
    classification: DecisionClassification,
    start_date,
    end_date,
) -> tuple[MeetingExtractedItem, Decision]:
    """FR-DEC-004/UC7: يحوّل البند إلى قرار حقيقي عبر
    decision_service.create_decision (يتحقق من decisions.create بنفسه،
    ويرجع القرار المُنشأ مباشرة)، مربوطًا بالاجتماع المصدر تلقائيًا
    (meeting_id)، ثم يربط البند به.

    تُرجع (البند، القرار) معًا — لنفس سبب assign_extracted_item_as_task
    أعلاه بالضبط (تمكين notify_decision_created بطبقة الـAPI)."""
    item = await _load_extracted_item(db, item_id)
    if item.status != MeetingExtractedItemStatus.pending:
        raise MeetingValidationError("هذا البند مُصنَّف مسبقًا")
    meeting = await load_meeting(db, item.meeting_id)

    decision = await decision_service.create_decision(
        db,
        actor=actor,
        committee_id=meeting.committee_id,
        title=(title or item.text),
        classification=classification,
        start_date=start_date,
        end_date=end_date,
        meeting_id=meeting.meeting_id,
    )
    item.status = MeetingExtractedItemStatus.assigned_decision
    item.linked_decision_id = decision.decision_id
    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    await db.refresh(item)
    await db.commit()
    return item, decision
