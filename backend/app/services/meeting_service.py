"""
الهدف:
منطق العمل (Business Logic) لوحدة "إدارة الاجتماعات" — FR-MEET-001 →
FR-MEET-005 (SRS §3.1.1/3.1.2) + إدارة جدول الأعمال (§3.1.3). بدون أي
تكامل مع Microsoft Teams/Graph API وبدون خدمات الذكاء الاصطناعي (§3.1.5)
— قرار موثّق 2026-08-31، راجعي رأس db/migrations/0018_meetings_schema.sql.

تحديث معماري 2026-09-01 (بعد "أدوار اللجان" — راجعي db/migrations/0016
و0017_remove_committee_roles_category.sql، وcommittee_service.py::
get_committee_role_permission_codes): التفويض هنا كان في نسخة سابقة يفحص
مباشرة committee.chair_user_id == actor.user_id (فحص هيكلي صرف، بلا أي
علاقة بجدول الصلاحيات). أُعيد بناؤه بالكامل هنا ليطابق النمط الموحّد الذي
بنته لاما لوحدة اللجان (committees.py::get_committee/list_committees):

    الوصول = صلاحية على مستوى System Role (own/department/all، من دور
             المستخدم العام) **أو** صلاحية على مستوى Committee Role
             (رئيس اللجنة/عضو اللجنة — من دور عضويته بهذه اللجنة تحديدًا،
             تُقرأ حيًا من role_permissions عبر
             committee_service.get_committee_role_permission_codes).

هذا يعني عمليًا: قدرة "رئيس اللجنة" على جدولة/تعديل/حذف اجتماع، أو إدارة
جدول أعماله، لم تعد مكتوبة بثبات بالكود — بل تُضبط من شاشة "الأدوار
والصلاحيات" (منح/سحب أكواد meetings.* لدور "رئيس اللجنة"/"عضو اللجنة"،
تمامًا كأي دور آخر). حتى صدور هذا التحديث، هذان الدوران لا يملكان أي كود
meetings.* افتراضيًا (0017_remove_committee_roles_category.sql أبقى فقط
committees.view) — فلا أحد غير سوبر أدمن يقدر يدير الاجتماعات فعليًا حتى
تُمنح هذه الصلاحيات صراحة لدور "رئيس اللجنة" من تلك الشاشة.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.committee import Committee, committee_members
from app.models.meeting import Meeting, MeetingAgendaItem, MeetingStatus
from app.models.role import Permission, RolePermission
from app.models.user import User
from app.services import audit_service, committee_service


class MeetingNotFoundError(Exception):
    """الاجتماع غير موجود (أو محذوف) — تُترجَم إلى 404 في طبقة الـ API."""


class AgendaItemNotFoundError(Exception):
    """بند جدول الأعمال غير موجود — تُترجَم إلى 404."""


class MeetingForbiddenError(Exception):
    """محاولة إجراء غير مسموح بها لهذا المستخدم تحديدًا — تُترجَم إلى 403."""


class MeetingInvalidStateError(Exception):
    """محاولة تعديل/حذف اجتماع في حالة لا تسمح بذلك (مثال: بعد انعقاده) — تُترجَم إلى 409."""


# ============================== تحقق الصلاحية (Authorization) ==============================


def _system_scope_allows(actor: User, committee: Committee, code: str) -> bool:
    """
    راجعي docstring الملف — المسار الأول (System Role) من مسارَي الـOR.
    نطاق 'own' غير مستخدَم هنا عمدًا: لا يوجد أي دور نظامي حاليًا يُمنح
    نطاق own على أكواد meetings.* (المكافئ العملي لـ"own" لاجتماعات لجنة
    محدَّدة هو بالضبط مسار Committee Role الثاني في _has_access أدناه).
    """
    scope = actor.scope_for(code)
    if scope == "all":
        return True
    if scope == "department":
        committee_dep_id = committee.chair.dep_id if committee.chair else None
        return actor.dep_id is not None and actor.dep_id == committee_dep_id
    return False


async def _has_access(db: AsyncSession, actor: User, committee: Committee, code: str) -> bool:
    if _system_scope_allows(actor, committee, code):
        return True
    committee_role_codes = await committee_service.get_committee_role_permission_codes(
        db, user_id=actor.user_id, committee_id=committee.committee_id
    )
    return code in committee_role_codes


async def _require_access(
    db: AsyncSession, actor: User, committee: Committee, code: str, message: str
) -> None:
    if not await _has_access(db, actor, committee, code):
        raise MeetingForbiddenError(message)


async def _committee_ids_with_committee_role_code(
    db: AsyncSession, actor: User, code: str
) -> set[uuid.UUID]:
    """
    اللجان التي يملك actor بها (عبر دور عضويته — رئيس أو عضو) الكود
    المحدَّد تحديدًا — تُستخدم فقط في list_meetings كبديل عن نطاق النظام
    own/department/all حين لا يملك actor أيًا منها (راجعي
    committee_service.user_has_committee_role_view_access لنفس الفكرة
    بصيغة "نعم/لا" بدل قائمة لجان).
    """
    stmt = (
        select(committee_members.c.committee_id)
        .select_from(committee_members)
        .join(RolePermission, RolePermission.role_id == committee_members.c.committee_role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(committee_members.c.user_id == actor.user_id, Permission.code == code)
    )
    result = await db.execute(stmt)
    return set(result.scalars().all())


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
    """FR-MEET-001: إنشاء اجتماع جديد — يتطلب meetings.schedule (System Role أو Committee Role)."""
    committee = await _load_committee(db, committee_id)
    await _require_access(
        db, actor, committee, "meetings.schedule", "ليست لديك صلاحية جدولة اجتماع لهذه اللجنة"
    )

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
    await _require_access(
        db, actor, committee, "meetings.view", "ليست لديك صلاحية لعرض هذا الاجتماع"
    )
    return meeting


async def list_meetings(db: AsyncSession, *, actor: User) -> list[Meeting]:
    """
    عرض الاجتماعات (FR-MEET §3.1.2) — بنفس منطق الوصول المزدوج المطبَّق
    بـcommittees.py (System Role scope أو Committee Role permission):
    - نطاق meetings.view (System Role) = all → كل الاجتماعات.
    - نطاق meetings.view (System Role) = department → اجتماعات اللجان
      التي رئيسها من نفس إدارة actor.
    - لا يملك أي نطاق نظامي → اجتماعات اللجان التي يملك بها actor فعليًا
      (عبر دور عضويته: رئيس أو عضو) صلاحية meetings.view تحديدًا — قد
      تكون فارغة تمامًا إن لم تُمنح هذه الصلاحية بعد لدور "رئيس اللجنة"/
      "عضو اللجنة" من شاشة الأدوار والصلاحيات (راجعي docstring الملف).
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
        committee_ids = await _committee_ids_with_committee_role_code(
            db, actor, "meetings.view"
        )
        if not committee_ids:
            return []
        stmt = stmt.where(Meeting.committee_id.in_(committee_ids))

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
    """FR-MEET-003: تعديل بيانات الاجتماع — يتطلب meetings.update، وقبل انعقاده حصرًا."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db, actor, committee, "meetings.update", "ليست لديك صلاحية تعديل هذا الاجتماع"
    )

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
    """FR-MEET-004: حذف الاجتماع — يتطلب meetings.delete (Soft Delete)."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db, actor, committee, "meetings.delete", "ليست لديك صلاحية حذف هذا الاجتماع"
    )

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
    """FR-MEET §3.1.3: إضافة بند لجدول الأعمال — يتطلب meetings.agenda.item.add."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db,
        actor,
        committee,
        "meetings.agenda.item.add",
        "ليست لديك صلاحية إضافة بند لجدول أعمال هذا الاجتماع",
    )

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
    await _require_access(
        db,
        actor,
        committee,
        "meetings.agenda.item.update",
        "ليست لديك صلاحية تعديل هذا البند",
    )

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
    await _require_access(
        db,
        actor,
        committee,
        "meetings.agenda.item.delete",
        "ليست لديك صلاحية حذف هذا البند",
    )

    await db.delete(item)
