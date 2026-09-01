"""
الهدف:
منطق العمل (Business Logic) لوحدة "إدارة الاجتماعات" — FR-MEET-001 →
FR-MEET-005 (SRS §3.1.1/3.1.2) + إدارة جدول الأعمال (§3.1.3). بدون أي
تكامل مع Microsoft Teams/Graph API وبدون خدمات الذكاء الاصطناعي (§3.1.5)
— قرار موثّق 2026-08-31، راجعي رأس db/migrations/0016_meetings_schema.sql.

من يقدر يفعل ماذا (حسب BRS بند 3 وpermissions.xlsx، قسم "إدارة الاجتماعات"):
- إنشاء/تعديل (قبل الانعقاد)/حذف اجتماع، وكل عمليات جدول الأعمال والمرفقات
  → حصريًا رئيس اللجنة المرتبط بالاجتماع (committee.chair_user_id).
- عرض الاجتماع وتفاصيله وجدول أعماله → رئيس اللجنة، أعضاؤها، أو أي دور
  يملك صلاحية meetings.view/meetings.view_details بنطاق كافٍ (department/
  all — مثال: ادمن يشوف اجتماعات لجان إدارته، migration 0017).

ملاحظة تصميم مهمة (لماذا لا تُستخدَم require_permission وحدها هنا):
"رئيس لجنة" و"عضو لجنة" ليسا دورين بجدول roles (حُذفا نهائيًا من كتالوج
الأدوار العامة — 0013_committee_chair.sql)، فلا صلاحية meetings.* بالكتالوج
تُمنح لهما عبر role_permissions إطلاقًا (راجعي رأس 0017). التحقق هنا إذن
"هجين" بنفس فلسفة committee_service.get_committee تمامًا: (أ) فحص هيكلي
مباشر (هل actor هو فعلًا رئيس/عضو اللجنة المالكة لهذا الاجتماع تحديدًا)،
أو (ب) صلاحية عامة من الكتالوج بنطاق يغطي الحالة (يمنح super_admin
[منح شامل تلقائي من 0006] وادمن [منح قراءة فقط من 0017] وصولًا دون أن
يكونا رئيسًا/عضوًا فعليًا). يكفي تحقق أحدهما لتمرير الفحص.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.committee import Committee
from app.models.meeting import Meeting, MeetingAgendaItem, MeetingStatus
from app.models.user import User
from app.services import audit_service


class MeetingNotFoundError(Exception):
    """الاجتماع غير موجود (أو محذوف) — تُترجَم إلى 404 في طبقة الـ API."""


class AgendaItemNotFoundError(Exception):
    """بند جدول الأعمال غير موجود — تُترجَم إلى 404."""


class MeetingForbiddenError(Exception):
    """محاولة إجراء غير مسموح بها لهذا المستخدم تحديدًا — تُترجَم إلى 403."""


class MeetingInvalidStateError(Exception):
    """محاولة تعديل/حذف اجتماع في حالة لا تسمح بذلك (مثال: بعد انعقاده) — تُترجَم إلى 409."""


# ============================== تحقق الصلاحية (Authorization) ==============================


def _is_chair(actor: User, committee: Committee) -> bool:
    return committee.chair_user_id is not None and committee.chair_user_id == actor.user_id


def _is_member(actor: User, committee: Committee) -> bool:
    return _is_chair(actor, committee) or any(
        m.user_id == actor.user_id for m in committee.members
    )


def _has_catalog_access(actor: User, committee: Committee, *, code: str) -> bool:
    """راجعي docstring الملف — البديل الثاني (المنح العام من الكتالوج) عن الفحص الهيكلي."""
    if code not in actor.permission_codes:
        return False
    scope = actor.scope_for(code)
    if scope == "all":
        return True
    if scope == "department":
        committee_dep_id = committee.chair.dep_id if committee.chair else None
        return actor.dep_id is not None and actor.dep_id == committee_dep_id
    return False  # own بدون عضوية فعلية لا معنى له هنا — الفحص الهيكلي أعلاه يغطيه أصلًا


def _authorize_view(actor: User, committee: Committee) -> None:
    if _is_member(actor, committee) or _has_catalog_access(
        actor, committee, code="meetings.view"
    ):
        return
    raise MeetingForbiddenError("ليست لديك صلاحية لعرض هذا الاجتماع")


def _authorize_manage(actor: User, committee: Committee) -> None:
    """إنشاء/تعديل/حذف الاجتماع وجدول أعماله — حصريًا رئيس اللجنة (أو من يملك meetings.schedule بالكتالوج)."""
    if _is_chair(actor, committee) or _has_catalog_access(
        actor, committee, code="meetings.schedule"
    ):
        return
    raise MeetingForbiddenError("هذا الإجراء متاح لرئيس اللجنة فقط")


async def _load_committee(db: AsyncSession, committee_id: uuid.UUID) -> Committee:
    result = await db.execute(
        select(Committee).where(Committee.committee_id == committee_id)
    )
    committee = result.scalar_one_or_none()
    if committee is None or committee.is_deleted:
        raise MeetingNotFoundError("اللجنة المرتبطة غير موجودة")
    return committee


async def _load_meeting(db: AsyncSession, meeting_id: uuid.UUID) -> Meeting:
    result = await db.execute(select(Meeting).where(Meeting.meeting_id == meeting_id))
    meeting = result.scalar_one_or_none()
    if meeting is None or meeting.is_deleted:
        raise MeetingNotFoundError("الاجتماع غير موجود")
    return meeting


def _resolve_participants(committee: Committee, participant_ids: list[uuid.UUID]) -> list[User]:
    """
    يتحقق من أن كل مشارك مقترَح هو فعلًا عضو أو رئيس اللجنة — بنفس منطق
    committee_service._resolve_members (لا يُختار مشاركون من خارج اللجنة).
    """
    valid_ids = {m.user_id for m in committee.members}
    if committee.chair_user_id is not None:
        valid_ids.add(committee.chair_user_id)
    unknown = set(participant_ids) - valid_ids
    if unknown:
        raise ValueError("لا يمكن دعوة مستخدم ليس عضوًا في اللجنة المرتبطة بالاجتماع")
    all_members = {m.user_id: m for m in committee.members}
    if committee.chair is not None:
        all_members[committee.chair_user_id] = committee.chair
    return [all_members[pid] for pid in participant_ids]


# ============================== إنشاء/تعديل/حذف الاجتماع ==============================


async def create_meeting(
    db: AsyncSession,
    *,
    actor: User,
    committee_id: uuid.UUID,
    title: str,
    description: str | None,
    meeting_type: str | None,
    scheduled_at: datetime,
    participant_ids: list[uuid.UUID],
    agenda_items: list[dict],
) -> Meeting:
    """FR-MEET-001: إنشاء اجتماع جديد — حصريًا رئيس اللجنة."""
    committee = await _load_committee(db, committee_id)
    _authorize_manage(actor, committee)

    participants = _resolve_participants(committee, participant_ids)

    meeting = Meeting(
        committee_id=committee_id,
        title=title,
        description=description,
        meeting_type=meeting_type,
        scheduled_at=scheduled_at,
        created_by=actor.user_id,
        participants=participants,
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
    return meeting


async def get_meeting(db: AsyncSession, meeting_id: uuid.UUID, *, actor: User) -> Meeting:
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    _authorize_view(actor, committee)
    return meeting


async def list_meetings(db: AsyncSession, *, actor: User) -> list[Meeting]:
    """
    عرض الاجتماعات (FR-MEET §3.1.2) — بنفس فلسفة committee_service.list_committees:
    - نطاق meetings.view = all → كل الاجتماعات.
    - نطاق meetings.view = department → اجتماعات اللجان التي رئيسها من نفس إدارة actor.
    - غير ذلك (own الافتراضي، أو بلا صلاحية بالكتالوج إطلاقًا) → اجتماعات
      اللجان التي actor رئيسها أو عضو فيها فعليًا فقط.
    """
    scope = actor.scope_for("meetings.view")
    stmt = select(Meeting).where(Meeting.deleted_at.is_(None)).order_by(
        Meeting.scheduled_at.desc()
    )

    if scope == "all":
        pass
    elif scope == "department":
        if actor.dep_id is None:
            return []
        chair = aliased(User)
        stmt = (
            stmt.join(Committee, Meeting.committee_id == Committee.committee_id)
            .join(chair, Committee.chair_user_id == chair.user_id)
            .where(chair.dep_id == actor.dep_id)
        )
    else:
        stmt = stmt.join(Committee, Meeting.committee_id == Committee.committee_id).where(
            or_(
                Committee.chair_user_id == actor.user_id,
                Committee.members.any(User.user_id == actor.user_id),
            )
        )

    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def update_meeting(
    db: AsyncSession,
    *,
    actor: User,
    meeting_id: uuid.UUID,
    title: str | None,
    description: str | None,
    meeting_type: str | None,
    scheduled_at: datetime | None,
    participant_ids: list[uuid.UUID] | None,
) -> Meeting:
    """FR-MEET-003: تعديل بيانات الاجتماع — رئيس اللجنة فقط، وقبل انعقاده حصرًا."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    _authorize_manage(actor, committee)

    if meeting.status != MeetingStatus.upcoming:
        raise MeetingInvalidStateError("لا يمكن تعديل اجتماع بعد بدء انعقاده")

    if title is not None:
        meeting.title = title
    if description is not None:
        meeting.description = description
    if meeting_type is not None:
        meeting.meeting_type = meeting_type
    if scheduled_at is not None:
        meeting.scheduled_at = scheduled_at
    if participant_ids is not None:
        meeting.participants = _resolve_participants(committee, participant_ids)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="meeting",
        target_id=meeting.meeting_id,
    )
    return meeting


async def delete_meeting(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> None:
    """FR-MEET-004: حذف الاجتماع — رئيس اللجنة فقط (Soft Delete)."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    _authorize_manage(actor, committee)

    meeting.deleted_at = datetime.now(UTC)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="delete",
        target_type="meeting",
        target_id=meeting.meeting_id,
    )


# ============================== جدول الأعمال ==============================


async def add_agenda_item(
    db: AsyncSession,
    *,
    actor: User,
    meeting_id: uuid.UUID,
    title: str,
    description: str | None,
    sort_order: int,
) -> MeetingAgendaItem:
    """FR-MEET §3.1.3: إضافة بند لجدول الأعمال — رئيس اللجنة فقط."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    _authorize_manage(actor, committee)

    item = MeetingAgendaItem(
        meeting_id=meeting_id, title=title, description=description, sort_order=sort_order
    )
    db.add(item)
    await db.flush()
    return item


async def _load_agenda_item(db: AsyncSession, agenda_item_id: uuid.UUID) -> MeetingAgendaItem:
    result = await db.execute(
        select(MeetingAgendaItem).where(MeetingAgendaItem.agenda_item_id == agenda_item_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise AgendaItemNotFoundError("بند جدول الأعمال غير موجود")
    return item


async def update_agenda_item(
    db: AsyncSession,
    *,
    actor: User,
    agenda_item_id: uuid.UUID,
    title: str | None,
    description: str | None,
    sort_order: int | None,
) -> MeetingAgendaItem:
    item = await _load_agenda_item(db, agenda_item_id)
    meeting = await _load_meeting(db, item.meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    _authorize_manage(actor, committee)

    if title is not None:
        item.title = title
    if description is not None:
        item.description = description
    if sort_order is not None:
        item.sort_order = sort_order
    return item


async def delete_agenda_item(db: AsyncSession, *, actor: User, agenda_item_id: uuid.UUID) -> None:
    item = await _load_agenda_item(db, agenda_item_id)
    meeting = await _load_meeting(db, item.meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    _authorize_manage(actor, committee)

    await db.delete(item)
