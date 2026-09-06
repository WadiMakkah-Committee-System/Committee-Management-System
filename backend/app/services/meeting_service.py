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

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core import agora_client, storage_client
from app.core.config import settings
from app.models.committee import Committee, committee_members
from app.models.document import Document, DocumentLink
from app.models.meeting import (
    Meeting,
    MeetingAgendaItem,
    MeetingAttendance,
    MeetingMode,
    MeetingStatus,
)
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


class MeetingAttachmentNotFoundError(Exception):
    """المرفق غير موجود لهذا الاجتماع تحديدًا — تُترجَم إلى 404."""


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


def _maybe_transition_status(meeting: Meeting) -> None:
    """
    تحويل كسول (Lazy) لحالة الاجتماع من الوقت الفعلي مقابل
    (scheduled_at, scheduled_end_at) — بدل Scheduler/Cron منفصل (لا حاجة
    له بحجم هذا المشروع). يُستدعى من كل نقطة تحميل اجتماع (_load_meeting
    وlist_meetings أدناه)، فتُعاد الحالة الصحيحة فعليًا مع كل قراءة، بصرف
    النظر هل حُفظت القيمة الجديدة بقاعدة البيانات بهذا الطلب تحديدًا أو لا
    (القراءات وحدها — GET — لا تُنفّذ commit عمدًا؛ الحساب نفسه مشتق دائمًا
    من scheduled_at/scheduled_end_at الثابتين + الوقت الحالي، فهو صحيح على
    أي حال بكل قراءة قادمة، وتُحفَظ القيمة تلقائيًا بأول طلب كتابة يمر بنفس
    الاجتماع لاحقًا: تعديل/حذف/انضمام/مغادرة).

    قرار موثّق مع لاما 2026-09-05: يعمل فقط على الاجتماعات التي لها
    scheduled_end_at (اجتماعات جديدة بعد migration 0023) — الاجتماعات
    القديمة بلا هذا الحقل تبقى بسلوكها التاريخي (بلا تحويل تلقائي، القرار
    المؤجَّل الأصلي لمرحلة تكامل Teams ما زال ساريًا عليها فقط، راجعي رأس
    db/migrations/0018). لا يمس started_at/ended_at (حضور Agora فعلي، مفهوم
    منفصل تمامًا) ولا يمس status == recorded أبدًا (محجوزة لمرحلة تسجيل
    Teams مستقبلية).
    """
    if meeting.scheduled_end_at is None:
        return
    if meeting.status not in (MeetingStatus.upcoming, MeetingStatus.ongoing):
        return

    now = datetime.now(UTC)
    if now >= meeting.scheduled_end_at:
        meeting.status = MeetingStatus.finished
    elif now >= meeting.scheduled_at:
        meeting.status = MeetingStatus.ongoing
    else:
        meeting.status = MeetingStatus.upcoming


async def _load_meeting(db: AsyncSession, meeting_id: uuid.UUID) -> Meeting:
    result = await db.execute(select(Meeting).where(Meeting.meeting_id == meeting_id))
    meeting = result.scalar_one_or_none()
    if meeting is None or meeting.is_deleted:
        raise MeetingNotFoundError("الاجتماع غير موجود")
    _maybe_transition_status(meeting)
    return meeting


def _resolve_participants(committee: Committee, participant_ids: list[uuid.UUID]) -> list[User]:
    """
    يتحقق من أن كل مشارك مقترَح هو فعلًا عضو أو رئيس اللجنة — بنفس منطق
    committee_service._resolve_members (لا يُختار مشاركون من خارج اللجنة).
    تُستخدم فقط بـupdate_meeting الآن (تعديل يدوي بعد الإنشاء) — الإنشاء
    نفسه صار يستخدم _all_committee_members أدناه (راجعي create_meeting).
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


def _all_committee_members(committee: Committee) -> list[User]:
    """
    كل أعضاء اللجنة (الأعضاء العاديون + الرئيس لو موجود)، بلا أي اختيار
    يدوي — تُستخدم بـcreate_meeting (قرار موثّق مع لاما 2026-09-05: كل
    اجتماع داخل لجنة يشمل كل أعضائها تلقائيًا كمشاركين، وليس اختيارًا
    يدويًا كما كان بالتصميم السابق). نفس مصدر العضوية المستخدَم بـ
    _resolve_participants أعلاه (committee.members + committee.chair).
    """
    members = list(committee.members)
    if committee.chair is not None and committee.chair_user_id not in {m.user_id for m in members}:
        members.append(committee.chair)
    return members


# ============================== إنشاء/تعديل/حذف الاجتماع ==============================


async def create_meeting(
    db: AsyncSession,
    *,
    actor: User,
    committee_id: uuid.UUID,
    title: str,
    description: str | None,
    mode: str,
    location: str | None,
    scheduled_at: datetime,
    scheduled_end_at: datetime,
    agenda_items: list[dict],
) -> Meeting:
    """FR-MEET-001: إنشاء اجتماع جديد — يتطلب meetings.schedule (System Role أو Committee Role).
    كل أعضاء اللجنة يُضافون تلقائيًا كمشاركين (_all_committee_members) — بلا
    اختيار يدوي (قرار موثّق مع لاما 2026-09-05)."""
    committee = await _load_committee(db, committee_id)
    await _require_access(
        db, actor, committee, "meetings.schedule", "ليست لديك صلاحية جدولة اجتماع لهذه اللجنة"
    )

    participants = _all_committee_members(committee)

    meeting = Meeting(
        committee_id=committee_id,
        title=title,
        description=description,
        mode=mode,
        location=location,
        scheduled_at=scheduled_at,
        scheduled_end_at=scheduled_end_at,
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
    meetings = list(result.scalars().unique().all())
    for m in meetings:
        _maybe_transition_status(m)
    return meetings


async def update_meeting(
    db: AsyncSession,
    *,
    actor: User,
    meeting_id: uuid.UUID,
    title: str | None,
    description: str | None,
    mode: str | None,
    mode_set: bool,
    location: str | None,
    location_set: bool,
    scheduled_at: datetime | None,
    scheduled_end_at: datetime | None,
    participant_ids: list[uuid.UUID] | None,
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
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db, actor, committee, "meetings.update", "ليست لديك صلاحية تعديل هذا الاجتماع"
    )

    if meeting.status != MeetingStatus.upcoming:
        raise MeetingInvalidStateError("لا يمكن تعديل اجتماع بعد بدء انعقاده")

    effective_mode = mode if mode_set else meeting.mode
    effective_location = location if location_set else meeting.location
    if effective_mode == "in_person" and effective_location is None:
        raise ValueError("مكان الاجتماع إلزامي للاجتماع الحضوري")
    if effective_mode == "remote" and effective_location is not None:
        raise ValueError("لا يمكن تحديد مكان لاجتماع عن بُعد")

    effective_start = scheduled_at if scheduled_at is not None else meeting.scheduled_at
    effective_end = scheduled_end_at if scheduled_end_at is not None else meeting.scheduled_end_at
    if effective_end is not None and effective_end <= effective_start:
        raise ValueError("وقت نهاية الاجتماع يجب أن يكون بعد وقت البداية")

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
    if participant_ids is not None:
        meeting.participants = _resolve_participants(committee, participant_ids)

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
    return meeting, changes


async def delete_meeting(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> Meeting:
    """
    FR-MEET-004: حذف الاجتماع — يتطلب meetings.delete (Soft Delete). قرار
    موثّق مع لاما 2026-09-01: الحذف مسموح فقط قبل موعد الاجتماع
    (scheduled_at) — وليس status == upcoming فقط (اجتماع status لا يزال
    upcoming لحظة بدئه فعليًا بالضبط، بانتظار التحويل التلقائي بالحالة
    الفعلية من Teams — خارج نطاق هذا الـPhase، راجعي رأس
    db/migrations/0018_meetings_schema.sql ملاحظة 4)؛ فحص الوقت الفعلي
    مقابل scheduled_at هو الفاصل الموثوق الوحيد المتاح الآن.
    """
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db, actor, committee, "meetings.delete", "ليست لديك صلاحية حذف هذا الاجتماع"
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
    return meeting


class MeetingJoinToken:
    """معلومات الانضمام لجلسة Agora — تُبنى بطبقة الخدمة وتُعاد للـAPI كما
    هي (نفس نمط MeetingAttachmentUpload أدناه، لكن بالاتجاه المعاكس: خرج
    لا دخل)."""

    __slots__ = ("app_id", "channel", "token", "uid", "expires_at")

    def __init__(self, *, app_id: str, channel: str, token: str, uid: int, expires_at: int) -> None:
        self.app_id = app_id
        self.channel = channel
        self.token = token
        self.uid = uid
        self.expires_at = expires_at


# ============================== الانضمام لاجتماع عن بعد (Agora) ==============================
# غرفة الفيديو نفسها لا تُدار هنا — Agora فقط تصدر Token قصير العمر
# (app.core.agora_client)، والقناة (channel) هي meeting_id نصًا مباشرة (فريد
# أصلًا، بلا حاجة لعمود إضافي). meeting_attendance سطر تدقيقي منفصل عن
# meeting_participants (المدعوّون المخطّط لهم) — راجعي رأس
# db/migrations/0022_meetings_agora_video.sql للتفصيل الكامل، خصوصًا قرار عدم
# تعديل meetings.status من هذين الإجراءين.


async def join_meeting(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID
) -> tuple[Meeting, MeetingJoinToken]:
    """الانضمام لاجتماع عن بعد — يتطلب meetings.join (نفس نمط الوصول المزدوج
    System Role/Committee Role في كل عمليات هذا الملف). يصدر Token عبر
    app.core.agora_client، ويسجّل سطر حضور جديد بـmeeting_attendance."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db, actor, committee, "meetings.join", "ليست لديك صلاحية الانضمام لهذا الاجتماع"
    )

    if meeting.mode != MeetingMode.remote:
        raise MeetingInvalidStateError("هذا اجتماع حضوري، لا يملك غرفة اتصال مرئي")
    if meeting.status == MeetingStatus.finished:
        raise MeetingInvalidStateError("انتهى هذا الاجتماع بالفعل")

    uid = secrets.randbelow(900_000) + 100_000  # uid عشوائي لكل جلسة انضمام (32-bit آمن)
    token, expires_at = agora_client.generate_rtc_token(channel_name=str(meeting.meeting_id), uid=uid)

    db.add(MeetingAttendance(meeting_id=meeting.meeting_id, user_id=actor.user_id, agora_uid=uid))
    if meeting.started_at is None:
        meeting.started_at = datetime.now(UTC)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="join",
        target_type="meeting",
        target_id=meeting.meeting_id,
    )
    await db.flush()

    return meeting, MeetingJoinToken(
        app_id=agora_client.get_app_id(),
        channel=str(meeting.meeting_id),
        token=token,
        uid=uid,
        expires_at=expires_at,
    )


async def leave_meeting(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, agora_uid: int | None
) -> Meeting:
    """مغادرة اجتماع عن بعد — يقفل سطر الحضور المفتوح لهذا المستخدم (وuid
    الجلسة تحديدًا لو أُرسل، لتفادي إقفال جلسة أخرى مفتوحة لنفس المستخدم من
    تبويب/جهاز ثاني بالخطأ). فلترة user_id == actor.user_id بالتحديث أدناه
    تمنع إقفال حضور غيره أصلًا، بصرف النظر عن أي فحص صلاحية إضافي."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db, actor, committee, "meetings.join", "ليست لديك صلاحية مغادرة هذا الاجتماع"
    )

    stmt = (
        update(MeetingAttendance)
        .where(
            MeetingAttendance.meeting_id == meeting.meeting_id,
            MeetingAttendance.user_id == actor.user_id,
            MeetingAttendance.left_at.is_(None),
        )
        .values(left_at=datetime.now(UTC))
    )
    if agora_uid is not None:
        stmt = stmt.where(MeetingAttendance.agora_uid == agora_uid)
    await db.execute(stmt)

    remaining = await db.scalar(
        select(func.count())
        .select_from(MeetingAttendance)
        .where(
            MeetingAttendance.meeting_id == meeting.meeting_id,
            MeetingAttendance.left_at.is_(None),
        )
    )
    if not remaining:
        meeting.ended_at = datetime.now(UTC)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="leave",
        target_type="meeting",
        target_id=meeting.meeting_id,
    )
    await db.flush()
    return meeting


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


# ============================== مرفقات الاجتماع ==============================
# أول استخدام فعلي لـdocument_links (راجعي رأس db/migrations/0021 وdocstring
# app/models/document.py::DocumentLink) — الوثيقة الفعلية (Document) تُنشأ
# مباشرة هنا (وليس عبر document_service.create_document) لأن نموذج رؤية
# الوثائق العام هناك (is_public/إدارات/لجان/مستخدمون محددون + صلاحيات
# documents.*) غير ذي صلة بمرفقات الاجتماع إطلاقًا — الوصول هنا محكوم
# بالكامل بنفس منطق _has_access أعلاه (meetings.attachments.*)، تمامًا
# كبقية عمليات الاجتماع.


class MeetingAttachmentUpload:
    """حزمة بيانات ملف مرفوع — تُبنى بطبقة الـAPI من UploadFile/Form."""

    __slots__ = ("link_role", "file_name", "mime_type", "content")

    def __init__(self, *, link_role: str, file_name: str, mime_type: str, content: bytes) -> None:
        self.link_role = link_role
        self.file_name = file_name
        self.mime_type = mime_type
        self.content = content


async def _load_meeting_attachment(
    db: AsyncSession, *, meeting_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[Document, DocumentLink]:
    stmt = (
        select(Document, DocumentLink)
        .join(DocumentLink, DocumentLink.document_id == Document.document_id)
        .where(
            DocumentLink.linked_entity_type == "meeting",
            DocumentLink.linked_entity_id == meeting_id,
            DocumentLink.document_id == document_id,
            Document.deleted_at.is_(None),
        )
    )
    result = await db.execute(stmt)
    row = result.first()
    if row is None:
        raise MeetingAttachmentNotFoundError("المرفق غير موجود")
    return row[0], row[1]


async def add_meeting_attachment(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, upload: MeetingAttachmentUpload
) -> tuple[Document, DocumentLink]:
    """
    FR-MEET §3.1.3 (مرفقات) — يتطلب meetings.attachments.add. link_role
    إلزامي دائمًا ('presentation' أو 'attachment') — راجعي
    schemas/meeting.py::MeetingAttachmentLinkRole.
    """
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db,
        actor,
        committee,
        "meetings.attachments.add",
        "ليست لديك صلاحية إضافة مرفقات لهذا الاجتماع",
    )

    max_bytes = settings.MAX_DOCUMENT_UPLOAD_MB * 1024 * 1024
    if len(upload.content) == 0:
        raise ValueError("الملف فارغ")
    if len(upload.content) > max_bytes:
        raise ValueError(
            f"حجم الملف يتجاوز الحد المسموح ({settings.MAX_DOCUMENT_UPLOAD_MB} ميجابايت)"
        )

    document = Document(
        title=upload.file_name,
        file_name=upload.file_name,
        storage_path="",  # يُحدَّث أدناه بعد توليد document_id
        mime_type=upload.mime_type or "application/octet-stream",
        file_size_bytes=len(upload.content),
        is_public=False,
        uploaded_by=actor.user_id,
    )
    db.add(document)
    await db.flush()  # لتوليد document_id قبل بناء storage_path

    storage_path = f"meetings/{meeting_id}/{document.document_id}/{upload.file_name}"
    document.storage_path = storage_path

    try:
        await storage_client.upload_object(
            storage_path, upload.content, content_type=document.mime_type
        )
    except storage_client.StorageError:
        await db.rollback()
        raise

    link = DocumentLink(
        document_id=document.document_id,
        linked_entity_type="meeting",
        linked_entity_id=meeting_id,
        link_role=upload.link_role,
        linked_by=actor.user_id,
    )
    db.add(link)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="upload",
        target_type="meeting_attachment",
        target_id=document.document_id,
        metadata={
            "meeting_id": str(meeting_id),
            "link_role": upload.link_role,
            "file_name": upload.file_name,
        },
    )
    await db.commit()
    await db.refresh(document)
    await db.refresh(link)
    return document, link


async def list_meeting_attachments(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID
) -> list[tuple[Document, DocumentLink]]:
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db,
        actor,
        committee,
        "meetings.attachments.view",
        "ليست لديك صلاحية لعرض مرفقات هذا الاجتماع",
    )
    stmt = (
        select(Document, DocumentLink)
        .join(DocumentLink, DocumentLink.document_id == Document.document_id)
        .where(
            DocumentLink.linked_entity_type == "meeting",
            DocumentLink.linked_entity_id == meeting_id,
            Document.deleted_at.is_(None),
        )
        .order_by(DocumentLink.linked_at)
    )
    result = await db.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def get_meeting_attachment_download(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[Document, bytes]:
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db,
        actor,
        committee,
        "meetings.attachments.view",
        "ليست لديك صلاحية لعرض مرفقات هذا الاجتماع",
    )
    document, _link = await _load_meeting_attachment(db, meeting_id=meeting_id, document_id=document_id)
    content = await storage_client.download_object(document.storage_path)
    return document, content


async def delete_meeting_attachment(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, document_id: uuid.UUID
) -> None:
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db,
        actor,
        committee,
        "meetings.attachments.delete",
        "ليست لديك صلاحية حذف مرفقات هذا الاجتماع",
    )
    document, link = await _load_meeting_attachment(db, meeting_id=meeting_id, document_id=document_id)

    await db.delete(link)
    document.deleted_at = datetime.now(UTC)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="delete",
        target_type="meeting_attachment",
        target_id=document.document_id,
        metadata={"meeting_id": str(meeting_id)},
    )
    await db.commit()

    # حذف الملف الفعلي من التخزين Best-Effort — فشل هذه الخطوة تحديدًا لا
    # يجب أن يُرجع الحذف (البيانات الوصفية محذوفة فعليًا بقاعدة البيانات
    # أهم من تسريب مساحة تخزين، ويمكن تنظيفها لاحقًا يدويًا عند الحاجة).
    try:
        await storage_client.delete_object(document.storage_path)
    except storage_client.StorageError:
        pass
