"""
إنشاء/عرض/قائمة/تعديل/حذف المهام (FR-TASK-001/002/016/018).

قائمة المهام (إعادة هيكلة 2026-10-24): عدد استعلامات ثابت مهما كان عدد
المهام — التحميل من loading.tasks_query()، والصلاحيات عبر CommitteeAccess.
شكل الاستجابة (TaskOut) لم يتغيّر.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.committee_period import assert_committee_not_expired, assert_within_committee_period
from app.models.committee import Committee
from app.models.task import Task, TaskAssignmentHistory, TaskPriority, TaskStatus
from app.models.user import User
from app.services import audit_service
from app.services.committee_access import CommitteeAccess
from app.services.task_service.access import (
    _require_access,
    _require_object_scoped_access,
    _validate_assignee_membership,
)
from app.services.task_service.codes import _CREATE, _DELETE, _UPDATE, _VIEW, _VIEW_DETAILS
from app.services.task_service.errors import TaskInvalidStateError, TaskValidationError
from app.services.task_service.loading import load_committee, load_task, tasks_query


async def create_task(
    db: AsyncSession,
    *,
    actor: User,
    committee_id: uuid.UUID,
    title: str,
    start_date: date,
    end_date: date,
    assignee_user_id: uuid.UUID,
    priority: TaskPriority = TaskPriority.medium,
    reminder_offset_days: int = 1,
) -> Task:
    """FR-TASK-001/002: إنشاء مباشر من واجهة المهام، مسؤول واحد فقط."""
    access = CommitteeAccess(db, actor)
    committee = await load_committee(db, committee_id)
    await _require_access(access, committee, _CREATE, "ليست لديك صلاحية إنشاء مهمة لهذه اللجنة"
    )
    assert_committee_not_expired(committee, action_label="إنشاء مهمة جديدة لهذه اللجنة")
    assert_within_committee_period(committee, field_label="تاريخ بداية المهمة", value=start_date)
    assert_within_committee_period(committee, field_label="تاريخ استحقاق المهمة", value=end_date)
    _validate_assignee_membership(committee, assignee_user_id)

    task = Task(
        committee_id=committee_id,
        title=title,
        start_date=start_date,
        end_date=end_date,
        assignee_user_id=assignee_user_id,
        created_by=actor.user_id,
        priority=priority,
        reminder_offset_days=reminder_offset_days,
    )
    db.add(task)
    await db.flush()

    # التعيين الأول — يُسجَّل بمسار المهمة (from_user_id = NULL)
    db.add(
        TaskAssignmentHistory(
            task_id=task.task_id,
            from_user_id=None,
            to_user_id=assignee_user_id,
            changed_by=actor.user_id,
        )
    )

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="create",
        target_type="task",
        target_id=task.task_id,
    )
    await db.commit()
    return await load_task(db, task.task_id, reload=True)


async def get_task(db: AsyncSession, task_id: uuid.UUID, *, actor: User) -> Task:
    access = CommitteeAccess(db, actor)
    task = await load_task(db, task_id)
    committee = task.committee  # محمَّلة مع المهمة (loading.task_options)
    await _require_object_scoped_access(
        access,
        committee,
        task,
        _VIEW_DETAILS,
        "ليست لديك صلاحية لعرض هذه المهمة",
        "يمكنك عرض المهام المسندة إليك فقط",
    )
    return task


async def list_tasks(
    db: AsyncSession, *, actor: User, access: CommitteeAccess | None = None, summary: bool = False
) -> list[Task]:
    """
    رئيس اللجنة يشوف كل مهام لجانه (بمن فيها الي مسندة لغيره)، العضو
    العادي يشوف بس مهامه المسندة له (حتى لو عضو بأكثر من لجنة).
    

    summary=True: المهمة + لجنتها فقط (بلا المسؤول/المنشئ/مسار الإسناد) — للوحة
    التحكم التي تعرض العنوان والحالة والموعد واسم اللجنة فقط.

    access (اختياري — تحسين أداء 2026-10-24): CommitteeAccess مشترك من
    المستدعي (لوحة التحكم تستدعي عدة قوائم بنفس الطلب) حتى تُجلب أكواد أدوار
    لجان المستخدم مرة واحدة للطلب كله بدل مرة لكل قائمة. نفس القاعدة حرفيًا."""
    access = access or CommitteeAccess(db, actor)
    scope = actor.scope_for(_VIEW)
    stmt = tasks_query(summary=summary).where(Task.deleted_at.is_(None)).order_by(Task.created_at.desc())

    # إصلاح 2026-09-13 (بلاغ لاما — بنفس نمط meeting_service.list_meetings/
    # decision_service.list_decisions المُصلَحين لنفس السبب): "department"
    # كان حصريًا (elif) فيُقصي مسار Committee Role بالكامل — عضو مهمّة
    # بلجنة يقودها رئيس من إدارة مختلفة لا يرى مهامه إطلاقًا. دُمج الشرطان
    # بـOR بدل الإقصاء، مع الحفاظ الكامل على تمييز رئيس/عضو أدناه (رئيس
    # اللجنة يرى كل مهام لجانه، العضو العادي يرى فقط مهامه المسندة له).
    if scope != "all":
        conditions = []

        if scope == "department" and actor.dep_id is not None:
            chair = aliased(User)
            dept_committee_ids = (
                select(Committee.committee_id)
                .join(chair, Committee.chair_user_id == chair.user_id)
                .where(chair.dep_id == actor.dep_id)
            )
            conditions.append(Task.committee_id.in_(dept_committee_ids))

        committee_ids = await access.committee_ids_with_code(_VIEW)
        if committee_ids:
            # تحسين أداء 2026-10-25: "هل هو رئيس هذي اللجنة؟" صار شرطًا داخل
            # نفس استعلام المهام (subquery) بدل استعلام مستقل قبله — نفس
            # النتيجة حرفيًا: لجان يرأسها → كل مهامها، ولجان هو عضو فيها فقط
            # → مهامه المسندة له فقط.
            chaired_committee_ids = select(Committee.committee_id).where(
                Committee.committee_id.in_(committee_ids),
                Committee.chair_user_id == actor.user_id,
            )
            conditions.append(
                and_(
                    Task.committee_id.in_(committee_ids),
                    or_(
                        Task.committee_id.in_(chaired_committee_ids),
                        Task.assignee_user_id == actor.user_id,
                    ),
                )
            )

        if not conditions:
            return []
        stmt = stmt.where(or_(*conditions))

    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def update_task(
    db: AsyncSession,
    *,
    actor: User,
    task_id: uuid.UUID,
    title: str | None,
    start_date: date | None,
    end_date: date | None,
    priority: TaskPriority | None = None,
    reminder_offset_days: int | None = None,
) -> Task:
    access = CommitteeAccess(db, actor)
    task = await load_task(db, task_id)
    committee = task.committee  # محمَّلة مع المهمة (loading.task_options)
    await _require_access(access, committee, _UPDATE, "ليست لديك صلاحية تعديل هذه المهمة")

    if task.status == TaskStatus.completed:
        raise TaskInvalidStateError("لا يمكن تعديل مهمة مكتملة")

    effective_start = start_date if start_date is not None else task.start_date
    effective_end = end_date if end_date is not None else task.end_date
    if effective_end < effective_start:
        raise TaskValidationError("تاريخ نهاية المهمة يجب أن يكون بعد تاريخ البداية أو يساويه")
    assert_within_committee_period(committee, field_label="تاريخ بداية المهمة", value=effective_start)
    assert_within_committee_period(committee, field_label="تاريخ استحقاق المهمة", value=effective_end)

    old_priority = task.priority
    other_field_changed = False

    if title is not None:
        task.title = title
        other_field_changed = True
    if start_date is not None:
        task.start_date = start_date
        other_field_changed = True
    if end_date is not None:
        # تمديد/تقديم الموعد يعيد ضبط "ساعة" التذكير والتأخر — تُرسَل
        # التذكيرات من جديد على الموعد الجديد، ولو كانت متأخرة فعليًا
        # ورُفع الموعد لاحقًا (تمديد)، يُسمح بتنبيه تأخر جديد لاحقًا لو
        # تأخرت مرة أخرى عن الموعد الممدَّد (طلب صاحبة المشروع 2026-09-11).
        task.end_date = end_date
        task.reminder_sent_at = None
        task.overdue_notified_at = None
        other_field_changed = True
    if reminder_offset_days is not None:
        task.reminder_offset_days = reminder_offset_days
        other_field_changed = True
    if priority is not None:
        task.priority = priority

    # ميتاداتا مفصّلة لمسار المهمة الموحَّد (راجعي get_task_activity) —
    # الأولوية بحقل مخصَّص لأنها الحقل اللي طلبت صاحبة المشروع تتبّعه
    # بمسار المهمة تحديدًا (2026-09-11)، وباقي الحقول (عنوان/تواريخ/
    # تذكير) تُجمَّع بعلم عام واحد بدل تفصيل كل حقل — كفاية لحجم النظام.
    audit_metadata: dict[str, object] = {"action": "task_updated"}
    if priority is not None and priority != old_priority:
        audit_metadata["priority_from"] = old_priority.value
        audit_metadata["priority_to"] = priority.value
    if other_field_changed:
        audit_metadata["other_fields_changed"] = True

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="task",
        target_id=task.task_id,
        metadata=audit_metadata,
    )
    await db.commit()
    return await load_task(db, task.task_id, reload=True)


async def delete_task(db: AsyncSession, *, actor: User, task_id: uuid.UUID) -> None:
    access = CommitteeAccess(db, actor)
    task = await load_task(db, task_id)
    committee = task.committee  # محمَّلة مع المهمة (loading.task_options)
    await _require_access(access, committee, _DELETE, "ليست لديك صلاحية حذف هذه المهمة")

    if task.status == TaskStatus.completed:
        raise TaskInvalidStateError("لا يمكن حذف مهمة مكتملة")

    task.deleted_at = datetime.now(UTC)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="delete",
        target_type="task",
        target_id=task.task_id,
    )
    await db.commit()
