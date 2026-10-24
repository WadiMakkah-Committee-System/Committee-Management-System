"""
إنشاء/عرض/قائمة/تعديل/حذف الاجتماعات — FR-MEET-001 → FR-MEET-005
(SRS §3.1.1/3.1.2). راجعي __init__.py لنظرة عامة على الوحدة كاملة.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, raiseload

from app.core.committee_period import assert_committee_not_expired, assert_within_committee_period
from app.models.committee import Committee
from app.models.meeting import Meeting, MeetingAgendaItem, MeetingMode, MeetingStatus
from app.models.user import User
from app.services import audit_service
from app.services.committee_access import CommitteeAccess
from app.services.meeting_service.access import (
    _committee_ids_with_committee_role_code,
    _require_access,
)
from app.services.meeting_service.errors import MeetingInvalidStateError, MeetingValidationError
from app.services.meeting_service.loading import (
    _all_committee_members,
    load_committee,
    load_meeting,
    participant_count_column,
    sync_meeting_status,
)


def _validate_mode_location(mode: MeetingMode, location: str | None) -> None:
    if mode == MeetingMode.in_person and not (location or "").strip():
        raise MeetingValidationError("مكان الاجتماع إلزامي عند اختيار اجتماع حضوري")


# ============================== إنشاء/تعديل/حذف الاجتماع ==============================


async def create_meeting(
    db: AsyncSession,
    *,
    actor: User,
    committee_id: uuid.UUID,
    title: str,
    description: str | None,
    mode: MeetingMode,
    location: str | None,
    scheduled_at: datetime,
    scheduled_end_at: datetime,
    agenda_items: list[dict],
) -> Meeting:
    """
    FR-MEET-001: إنشاء اجتماع جديد — يتطلب meetings.schedule (System Role
    أو Committee Role). كل أعضاء اللجنة يُضافون تلقائيًا كمشاركين
    (_all_committee_members) — بلا اختيار يدوي (قرار موثّق مع لاما
    2026-09-05).
    """
    committee = await load_committee(db, committee_id, with_members=True)
    await _require_access(
        db, actor, committee, "meetings.schedule", "ليست لديك صلاحية جدولة اجتماع لهذه اللجنة"
    )
    _validate_mode_location(mode, location)
    assert_committee_not_expired(committee, action_label="جدولة اجتماع جديد لهذه اللجنة")
    assert_within_committee_period(committee, field_label="تاريخ الاجتماع", value=scheduled_at.date())
    assert_within_committee_period(
        committee, field_label="تاريخ نهاية الاجتماع", value=scheduled_end_at.date()
    )

    meeting = Meeting(
        committee_id=committee_id,
        title=title,
        description=description,
        mode=mode,
        location=location if mode == MeetingMode.in_person else None,
        scheduled_at=scheduled_at,
        scheduled_end_at=scheduled_end_at,
        created_by=actor.user_id,
        participants=_all_committee_members(committee),
        agenda_items=[
            MeetingAgendaItem(
                title=item["title"],
                description=item.get("description"),
                sort_order=item.get("sort_order", index),
            )
            for index, item in enumerate(agenda_items)
        ],
    )
    db.add(meeting)
    await db.flush()

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="create",
        target_type="meeting",
        target_id=meeting.meeting_id,
    )
    await db.commit()
    return await load_meeting(db, meeting.meeting_id, detail=True, reload=True)


async def get_meeting(db: AsyncSession, meeting_id: uuid.UUID, *, actor: User) -> Meeting:
    meeting = await load_meeting(db, meeting_id, detail=True)
    await _require_access(
        db, actor, meeting.committee, "meetings.view", "ليست لديك صلاحية لعرض هذا الاجتماع"
    )
    return meeting


async def list_meetings(
    db: AsyncSession, *, actor: User, access: CommitteeAccess | None = None
) -> list[tuple[Meeting, int]]:
    """
    عرض الاجتماعات (FR-MEET §3.1.2) — بنفس منطق الوصول المزدوج المطبَّق
    بـcommittees.py (System Role scope أو Committee Role permission).

    إصلاح 2026-09-13 (بلاغ لاما — عضو لجنة لم يرَ اجتماعًا لجنته الفعلية
    ولا وصله إشعار، بينما رئيس اللجنة رآه بشكل طبيعي): كان "department"
    scope حصريًا (elif) — يستبعد بالكامل أي مسار Committee Role حتى لو
    actor عضو فعلي بلجنة يقودها رئيس من إدارة مختلفة. هذا يخالف التصميم
    الموثَّق أعلى الملف صراحةً ("الوصول = System Role scope **أو**
    Committee Role permission") — get_meeting/_has_access تُطبّق الـOR
    الصحيح لعنصر واحد، لكن هذه القائمة المجمَّعة (bulk) لم تكن تطبّقه.
    الحل: بناء الاثنين كشرطين مستقلّين ودمجهما بـOR (لا إقصاء) — بنفس
    نمط الإصلاح المطبَّق أيضًا بـdecision_service.list_decisions
    وtask_service.list_tasks لنفس السبب بالضبط.
    """
    scope = actor.scope_for("meetings.view")
    # تحسين 2026-10-24: صف واحد لكل اجتماع (أعمدته المباشرة + عدد مشاركيه
    # كعمود محسوب) باستعلام واحد — بدون أي علاقة (اللجنة/المنشئ/المشاركون/
    # البنود)؛ شاشة القائمة لا تعرض غير الحقول المباشرة وعدد المشاركين
    # (راجعي schemas/meeting.py::MeetingListItem). كانت تُرجع MeetingOut
    # كاملًا = ~29 استعلامًا عبر سلسلة selectin بالموديلات.
    stmt = (
        select(Meeting, participant_count_column())
        .where(Meeting.deleted_at.is_(None))
        .options(raiseload("*", sql_only=True))
        .order_by(Meeting.scheduled_at.desc())
    )

    if scope != "all":
        conditions = []
        if scope == "department" and actor.dep_id is not None:
            chair = aliased(User)
            dept_committee_ids = (
                select(Committee.committee_id)
                .join(chair, Committee.chair_user_id == chair.user_id)
                .where(chair.dep_id == actor.dep_id)
            )
            conditions.append(Meeting.committee_id.in_(dept_committee_ids))

        if access is not None:
            committee_ids = await access.committee_ids_with_code("meetings.view")
        else:
            committee_ids = await _committee_ids_with_committee_role_code(
                db, actor, "meetings.view"
            )
        if committee_ids:
            conditions.append(Meeting.committee_id.in_(committee_ids))

        if not conditions:
            return []
        stmt = stmt.where(or_(*conditions))

    result = await db.execute(stmt)
    rows = [(meeting, int(count)) for meeting, count in result.all()]
    for meeting, _count in rows:
        sync_meeting_status(meeting)
    return rows


async def update_meeting(
    db: AsyncSession,
    *,
    actor: User,
    meeting_id: uuid.UUID,
    title: str | None,
    description: str | None,
    mode: MeetingMode | None,
    mode_set: bool,
    location: str | None,
    location_set: bool,
    scheduled_at: datetime | None,
    scheduled_end_at: datetime | None,
) -> tuple[Meeting, dict[str, tuple[object, object]]]:
    """
    FR-MEET-003: تعديل بيانات الاجتماع — يتطلب meetings.update، وقبل انعقاده
    حصرًا. mode_set/location_set (من payload.model_fields_set بطبقة
    الـAPI — راجعي schemas/meeting.py::MeetingUpdate) لازمة للتفريق بين "لم
    يُرسَل" و"أُرسل بقيمة فارغة صراحة" — بنفس نمط category_explicitly_set
    بـdocument_service.update_document — لأن location قد يُطلَب مسحه صراحة
    (in_person → remote)، على عكس بقية الحقول هنا حيث None تعني "لا تعديل".

    الإرجاع (meeting, changes): changes قاموس بالحقول "المهمة" فقط التي
    تغيّرت فعليًا (موعد البداية/النهاية/النوع/المكان) بصيغة
    {field: (old, new)} — يُستخدَم بطبقة الـAPI لإرسال إشعار بريدي لأعضاء
    اللجنة عند التعديل، فقط إذا تغيّر أحدها (قرار لاما 2026-09-06: "الحقول
    المهمة فقط"، لتفادي إشعار بكل تعديل سطحي كتصحيح خطأ إملائي بالعنوان).
    """
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_access(
        db, actor, committee, "meetings.update", "ليست لديك صلاحية تعديل هذا الاجتماع"
    )

    if meeting.status != MeetingStatus.upcoming:
        raise MeetingInvalidStateError("لا يمكن تعديل اجتماع بعد بدء انعقاده")

    effective_mode = mode if mode_set else meeting.mode
    effective_location = location if location_set else meeting.location
    if effective_mode == MeetingMode.in_person and not (effective_location or "").strip():
        raise MeetingValidationError("مكان الاجتماع إلزامي للاجتماع الحضوري")
    if effective_mode == MeetingMode.remote and effective_location is not None:
        raise MeetingValidationError("لا يمكن تحديد مكان لاجتماع عن بُعد")

    effective_start = scheduled_at if scheduled_at is not None else meeting.scheduled_at
    effective_end = scheduled_end_at if scheduled_end_at is not None else meeting.scheduled_end_at
    if effective_end is not None and effective_end <= effective_start:
        raise MeetingValidationError("وقت نهاية الاجتماع يجب أن يكون بعد وقت البداية")
    assert_within_committee_period(committee, field_label="تاريخ الاجتماع", value=effective_start.date())
    if effective_end is not None:
        assert_within_committee_period(
            committee, field_label="تاريخ نهاية الاجتماع", value=effective_end.date()
        )

    _important_fields = ("scheduled_at", "scheduled_end_at", "mode", "location")
    _before = {field: getattr(meeting, field) for field in _important_fields}

    if title is not None:
        meeting.title = title
    if description is not None:
        meeting.description = description
    if mode_set:
        meeting.mode = mode
    if location_set:
        meeting.location = location
    if scheduled_at is not None:
        meeting.scheduled_at = scheduled_at
    if scheduled_end_at is not None:
        meeting.scheduled_end_at = scheduled_end_at

    changes = {
        field: (_before[field], getattr(meeting, field))
        for field in _important_fields
        if _before[field] != getattr(meeting, field)
    }

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="meeting",
        target_id=meeting.meeting_id,
    )
    await db.commit()
    meeting = await load_meeting(db, meeting.meeting_id, detail=True, reload=True)
    return meeting, changes


async def delete_meeting(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> Meeting:
    """
    FR-MEET-004: حذف الاجتماع — يتطلب meetings.delete (Soft Delete). قرار
    موثّق مع لاما 2026-09-01: الحذف مسموح فقط قبل موعد الاجتماع
    (scheduled_at) — وليس status == upcoming فقط (اجتماع status لا يزال
    upcoming لحظة بدئه فعليًا بالضبط، بانتظار التحويل التلقائي بالحالة
    الفعلية من Teams — خارج نطاق هذا الـPhase، راجعي رأس
    db/migrations/0018_meetings_schema.sql ملاحظة 4)؛ فحص الوقت الفعلي
    مقابل scheduled_at هو الفاصل الموثوق الوحيد المتاح الآن. تُعيد
    الاجتماع (بعد commit) — تستخدمه طبقة الـAPI لإرسال إشعار إلغاء بريدي
    لأعضاء اللجنة (راجعي notification_service.py).
    """
    # detail=True: الإشعار البريدي بعد الحذف (notify_meeting_cancelled) يقرأ
    # meeting.committee.name وmeeting.participants من هذا الكائن نفسه.
    meeting = await load_meeting(db, meeting_id, detail=True)
    await _require_access(
        db, actor, meeting.committee, "meetings.delete", "ليست لديك صلاحية حذف هذا الاجتماع"
    )

    if datetime.now(UTC) >= meeting.scheduled_at:
        raise MeetingInvalidStateError("لا يمكن حذف الاجتماع بعد بدء موعده")

    meeting.deleted_at = datetime.now(UTC)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="delete",
        target_type="meeting",
        target_id=meeting.meeting_id,
    )
    await db.commit()
    return meeting
