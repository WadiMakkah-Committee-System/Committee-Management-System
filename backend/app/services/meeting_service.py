"""
الهدف:
منطق العمل (Business Logic) لوحدة "إدارة الاجتماعات" — FR-MEET-001 →
FR-MEET-005 (SRS §3.1.1/3.1.2) + إدارة جدول الأعمال (§3.1.3) + مرفقات
الاجتماع (عرض تقديمي + مرفقات عامة، عبر document_links الموجود أصلًا).
بدون أي تكامل فعلي مع Microsoft Teams/Graph API — mode='remote' يمهّد
لتلك المرحلة فقط (راجعي app/models/meeting.py).

التفويض (بعد "أدوار اللجان" — راجعي committee_service.py::
get_committee_role_permission_codes): الوصول = صلاحية على مستوى System
Role (own/department/all، من دور المستخدم العام) **أو** صلاحية على
مستوى Committee Role (رئيس اللجنة/عضو اللجنة — من دور عضويته بهذه اللجنة
تحديدًا، تُقرأ حيًا من role_permissions). لا شيء مكتوب بثبات بالكود —
يُضبط من شاشة "الأدوار والصلاحيات".

تحديثات 2026-09-01 (قرارات صاحبة المشروع):
- meeting_type (نص حر) → mode (عن بعد/حضوري) + location (إلزامي حضوري).
- المشاركون: لا يوجد اختيار يدوي بعد الآن — كل أعضاء اللجنة (بمن فيهم
  رئيسها) يُضافون تلقائيًا عند الإنشاء (create_meeting)، وتُحدَّث القائمة
  تلقائيًا أيضًا لو تغيّرت عضوية اللجنة لاحقًا لا تنعكس هنا (عضوية اللجنة
  مقفلة أصلًا بعد الاعتماد — راجعي committee_service.approve_request).
- حذف الاجتماع (delete_meeting) ممنوع بعد وقت انعقاده الفعلي (لا معنى
  لحذف اجتماع انتهى وقته) — قيد جديد لم يكن موجودًا سابقًا.
- مرفقات الاجتماع: قسمان مستقلان (kind: 'presentation' | 'attachment')،
  يُخزَّنان عبر document_service.create_document (نفس بنية تخزين وحدة
  الوثائق) ثم يُربطان بالاجتماع عبر document_links (linked_entity_type=
  'meeting_presentation'/'meeting_attachment'، linked_entity_id=meeting_id)
  — الجدول كان "جاهزًا بالقاعدة، غير مستخدَم بعد" (راجعي 0012)، وهذا أول
  استخدام فعلي له.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.committee import Committee, committee_members
from app.models.document import Document, DocumentLink
from app.models.meeting import Meeting, MeetingAgendaItem, MeetingMode, MeetingStatus
from app.models.role import Permission, RolePermission
from app.models.user import User
from app.services import audit_service, committee_service, document_service

# يقابل بالضبط MeetingAttachmentKind بـschemas/meeting.py.
_ATTACHMENT_LINK_TYPE = {
    "presentation": "meeting_presentation",
    "attachment": "meeting_attachment",
}


class MeetingNotFoundError(Exception):
    """الاجتماع غير موجود (أو محذوف) — تُترجَم إلى 404 في طبقة الـ API."""


class AgendaItemNotFoundError(Exception):
    """بند جدول الأعمال غير موجود — تُترجَم إلى 404."""


class AttachmentNotFoundError(Exception):
    """المرفق غير موجود أو غير مرتبط بهذا الاجتماع — تُترجَم إلى 404."""


class MeetingForbiddenError(Exception):
    """محاولة إجراء غير مسموح بها لهذا المستخدم تحديدًا — تُترجَم إلى 403."""


class MeetingInvalidStateError(Exception):
    """محاولة تعديل/حذف اجتماع في حالة لا تسمح بذلك (مثال: بعد انعقاده) — تُترجَم إلى 409."""


class MeetingValidationError(Exception):
    """خطأ تحقق من بيانات العمل (مثال: مكان الاجتماع مفقود لحضوري) — تُترجَم إلى 400."""


# ============================== تحقق الصلاحية (Authorization) ==============================


def _system_scope_allows(actor: User, committee: Committee, code: str) -> bool:
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


def _all_committee_members(committee: Committee) -> list[User]:
    """
    كل أعضاء اللجنة (بمن فيهم رئيسها) — مصدر المشاركين التلقائي الوحيد
    الآن (راجعي docstring أعلى الملف). لا تكرار: الرئيس قد يكون أيضًا
    ضمن committee.members حسب لحظة الاستعلام، فنستبعد تكراره صراحة.
    """
    members: dict[uuid.UUID, User] = {m.user_id: m for m in committee.members}
    if committee.chair is not None:
        members[committee.chair_user_id] = committee.chair
    return list(members.values())


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
    agenda_items: list[dict],
) -> Meeting:
    """
    FR-MEET-001: إنشاء اجتماع جديد — يتطلب meetings.schedule (System Role
    أو Committee Role). المشاركون كل أعضاء اللجنة تلقائيًا (بلا اختيار).
    """
    committee = await _load_committee(db, committee_id)
    await _require_access(
        db, actor, committee, "meetings.schedule", "ليست لديك صلاحية جدولة اجتماع لهذه اللجنة"
    )
    _validate_mode_location(mode, location)

    meeting = Meeting(
        committee_id=committee_id,
        title=title,
        description=description,
        mode=mode,
        location=location if mode == MeetingMode.in_person else None,
        scheduled_at=scheduled_at,
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
    return await _load_meeting(db, meeting.meeting_id)


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
    بـcommittees.py (System Role scope أو Committee Role permission).
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
    mode: MeetingMode | None,
    location: str | None,
    scheduled_at: datetime | None,
) -> Meeting:
    """FR-MEET-003: تعديل بيانات الاجتماع — يتطلب meetings.update، وقبل انعقاده حصرًا."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db, actor, committee, "meetings.update", "ليست لديك صلاحية تعديل هذا الاجتماع"
    )

    if meeting.status != MeetingStatus.upcoming:
        raise MeetingInvalidStateError("لا يمكن تعديل اجتماع بعد بدء انعقاده")

    effective_mode = mode if mode is not None else meeting.mode
    effective_location = location if location is not None else meeting.location
    if effective_mode == MeetingMode.remote:
        effective_location = None
    _validate_mode_location(effective_mode, effective_location)

    if title is not None:
        meeting.title = title
    if description is not None:
        meeting.description = description
    if mode is not None:
        meeting.mode = mode
    meeting.location = effective_location
    if scheduled_at is not None:
        meeting.scheduled_at = scheduled_at

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="meeting",
        target_id=meeting.meeting_id,
    )
    await db.commit()
    return await _load_meeting(db, meeting.meeting_id)


async def delete_meeting(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> None:
    """
    FR-MEET-004: حذف الاجتماع — يتطلب meetings.delete (Soft Delete)، وقبل
    وقت انعقاده الفعلي حصرًا (قرار صريح 2026-09-01: لا معنى لحذف اجتماع
    فات وقته أصلًا).
    """
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db, actor, committee, "meetings.delete", "ليست لديك صلاحية حذف هذا الاجتماع"
    )

    if datetime.now(UTC) >= meeting.scheduled_at:
        raise MeetingInvalidStateError("لا يمكن حذف اجتماع بعد حلول موعده")

    meeting.deleted_at = datetime.now(UTC)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="delete",
        target_type="meeting",
        target_id=meeting.meeting_id,
    )
    await db.commit()


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
    await db.commit()
    await db.refresh(item)
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
    await db.commit()
    await db.refresh(item)
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
    await db.commit()


# ============================== مرفقات الاجتماع ==============================
# قسمان مستقلان (kind): 'presentation' (العرض التقديمي — عادةً ملف واحد،
# لا قيد بالكود يفرض ذلك) و'attachment' (مرفقات عامة، متعددة). كلاهما
# يُخزَّن كوثيقة حقيقية بوحدة "إدارة الوثائق" (نفس Supabase Storage)، ثم
# يُربَط بالاجتماع عبر document_links — أول استخدام فعلي لهذا الجدول
# (كان جاهزًا بالقاعدة منذ 0012، غير مستخدَم من أي API قبل الآن).


async def add_attachment(
    db: AsyncSession,
    *,
    actor: User,
    meeting_id: uuid.UUID,
    kind: str,
    title: str,
    file_name: str,
    mime_type: str,
    content: bytes,
) -> tuple[Document, datetime]:
    """يتطلب meetings.attachments.add — يخزّن الملف كوثيقة ثم يربطها بالاجتماع."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db,
        actor,
        committee,
        "meetings.attachments.add",
        "ليست لديك صلاحية إضافة مرفقات لهذا الاجتماع",
    )

    # الوثيقة تُرى افتراضيًا من أعضاء اللجنة نفسها (visible_committees) —
    # نفس منطق رؤية وثائق اللجنة في وحدة الوثائق، وليست عامة (is_public=False).
    document = await document_service.create_document(
        db,
        actor=actor,
        title=title,
        description=None,
        category_id=None,
        is_public=False,
        department_ids=[],
        committee_ids=[committee.committee_id],
        user_ids=[],
        file_name=file_name,
        mime_type=mime_type,
        content=content,
    )

    link = DocumentLink(
        document_id=document.document_id,
        linked_entity_type=_ATTACHMENT_LINK_TYPE[kind],
        linked_entity_id=meeting_id,
        linked_by=actor.user_id,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return document, link.linked_at


async def list_attachments(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, kind: str | None
) -> list[tuple[Document, str, datetime]]:
    """يتطلب meetings.attachments.view. يرجع (الوثيقة، kind، تاريخ الربط) لكل مرفق."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db,
        actor,
        committee,
        "meetings.attachments.view",
        "ليست لديك صلاحية عرض مرفقات هذا الاجتماع",
    )

    link_types = (
        [_ATTACHMENT_LINK_TYPE[kind]] if kind else list(_ATTACHMENT_LINK_TYPE.values())
    )
    stmt = (
        select(DocumentLink, Document)
        .join(Document, Document.document_id == DocumentLink.document_id)
        .where(
            DocumentLink.linked_entity_id == meeting_id,
            DocumentLink.linked_entity_type.in_(link_types),
            Document.deleted_at.is_(None),
        )
        .order_by(DocumentLink.linked_at.asc())
    )
    result = await db.execute(stmt)
    reverse_kind = {v: k for k, v in _ATTACHMENT_LINK_TYPE.items()}
    return [
        (document, reverse_kind[link.linked_entity_type], link.linked_at)
        for link, document in result.all()
    ]


async def delete_attachment(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, document_id: uuid.UUID
) -> None:
    """يتطلب meetings.attachments.delete — يحذف الوثيقة نفسها (Soft Delete)، وليس الربط فقط."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db,
        actor,
        committee,
        "meetings.attachments.delete",
        "ليست لديك صلاحية حذف مرفقات هذا الاجتماع",
    )

    link_result = await db.execute(
        select(DocumentLink).where(
            DocumentLink.linked_entity_id == meeting_id,
            DocumentLink.document_id == document_id,
            DocumentLink.linked_entity_type.in_(_ATTACHMENT_LINK_TYPE.values()),
        )
    )
    if link_result.scalar_one_or_none() is None:
        raise AttachmentNotFoundError("المرفق غير موجود ضمن هذا الاجتماع")

    deleted = await document_service.delete_document(db, actor=actor, document_id=document_id)
    if deleted is None:
        raise AttachmentNotFoundError("المرفق غير موجود")
