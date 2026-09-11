"""
الهدف:
منطق العمل (Business Logic) لوحدة "إدارة الاجتماعات" — FR-MEET-001 →
FR-MEET-005 (SRS §3.1.1/3.1.2) + إدارة جدول الأعمال (§3.1.3) + مرفقات
الاجتماع (عرض تقديمي + مرفقات عامة، عبر document_links الموجود أصلًا).
بدون أي تكامل فعلي مع Microsoft Teams/Graph API — mode='remote' يمهّد
لتلك المرحلة فقط (راجعي app/models/meeting.py). الانضمام الفعلي
للاجتماعات عن بعد يتم عبر Agora (راجعي قسم join_meeting/leave_meeting
أدناه) — منفصل تمامًا عن تكامل Teams المؤجَّل.

التفويض (بعد "أدوار اللجان" — راجعي committee_service.py::
get_committee_role_permission_codes): الوصول = صلاحية على مستوى System
Role (own/department/all، من دور المستخدم العام) **أو** صلاحية على
مستوى Committee Role (رئيس اللجنة/عضو اللجنة — من دور عضويته بهذه اللجنة
تحديدًا، تُقرأ حيًا من role_permissions). لا شيء مكتوب بثبات بالكود —
يُضبط من شاشة "الأدوار والصلاحيات".

تحديثات 2026-09-01 (قرارات صاحبة المشروع):
- meeting_type (نص حر) → mode (عن بعد/حضوري) + location (إلزامي حضوري).
- المشاركون: لا يوجد اختيار يدوي بعد الآن — كل أعضاء اللجنة (بمن فيهم
  رئيسها) يُضافون تلقائيًا عند الإنشاء (create_meeting)، ولا اختيار يدوي
  عند التعديل أيضًا (participant_ids حُذف بالكامل من MeetingUpdate —
  راجعي schemas/meeting.py).
- حذف الاجتماع (delete_meeting) ممنوع بعد وقت انعقاده الفعلي (لا معنى
  لحذف اجتماع انتهى وقته) — قيد جديد لم يكن موجودًا سابقًا.
- مرفقات الاجتماع: قسمان مستقلان (kind: 'presentation' | 'attachment')،
  يُخزَّنان عبر document_service.create_document (نفس بنية تخزين وحدة
  الوثائق) ثم يُربطان بالاجتماع عبر document_links (linked_entity_type=
  'meeting_presentation'/'meeting_attachment'، linked_entity_id=meeting_id)
  — الجدول كان "جاهزًا بالقاعدة، غير مستخدَم بعد" (راجعي 0012)، وهذا أول
  استخدام فعلي له.

تحديث 2026-09-05/06 (قرارات موثّقة مع لاما — تكامل الفيديو + الإشعارات):
- scheduled_end_at إلزامي عند الإنشاء، ويقود التحويل التلقائي لحالة
  الاجتماع (upcoming/ongoing/finished) — راجعي sync_meeting_status.
- update_meeting/delete_meeting يُعيدان الاجتماع (بعد commit) لتستخدمه
  طبقة الـAPI بإرسال إشعار بريدي لأعضاء اللجنة (راجعي notification_service.py
  وapp/api/v1/meetings.py) — عند التعديل فقط لو تغيّر أحد "الحقول
  المهمة" (موعد البداية/النهاية/النوع/المكان).
"""

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core import agora_client, gemini_client, storage_client
from app.models.committee import Committee, committee_members
from app.models.document import Document, DocumentLink
from app.models.meeting import (
    Meeting,
    MeetingAgendaItem,
    MeetingAttendance,
    MeetingMode,
    MeetingStatus,
)
from app.models.decision import Decision, DecisionClassification
from app.models.meeting_draft import MeetingDraft, MeetingDraftStatus, MeetingRecording
from app.models.meeting_extracted_item import MeetingExtractedItem, MeetingExtractedItemStatus
from app.models.role import Permission, RolePermission
from app.models.task import Task
from app.models.user import User
from app.services import audit_service, committee_service, decision_service, document_service, task_service

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


def sync_meeting_status(meeting: Meeting) -> None:
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

    إصلاح 2026-09-09 (بلاغ لاما — فتحت اجتماعًا انتهى وقته المجدول من قسم
    المحاضر وظل يظهر "الاجتماع لم ينتهِ بعد"): كانت الدالة private
    (باسم _maybe_transition_status) ومستدعاة فقط داخل هذا الملف، بينما
    meeting_minutes_service._load_meeting (نسخة محلية منفصلة لجلب
    الاجتماع، بنفس نمط meeting_chat_service._load_meeting_and_committee)
    كانت تقرأ العمود status الخام من القاعدة مباشرة بلا أي تحويل — فتبقى
    عالقة على upcoming/ongoing حتى يمر طلب كتابة آخر على نفس الاجتماع
    (تعديل/انضمام...) يُشغّل هذه الدالة صدفة. حُوِّلت الآن لدالة عامة
    (بلا _) عمدًا لتصبح قابلة للاستيراد والاستدعاء من أي ملف خدمة آخر
    يحمّل Meeting ويعتمد على status الزمني — بدأ فعليًا بـ
    meeting_minutes_service._load_meeting (راجعيها). أي ملف مستقبلي
    يحمّل Meeting ويحتاج status صحيحًا زمنيًا (وليس فقط القيمة الخام
    بالقاعدة) يجب أن يستدعيها أيضًا بدل تكرار المنطق أو تجاهله — هذا
    بالضبط الفخ اللي وقعنا فيه هنا.
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
    sync_meeting_status(meeting)
    return meeting


def _all_committee_members(committee: Committee) -> list[User]:
    """
    كل أعضاء اللجنة (بمن فيهم رئيسها) — مصدر المشاركين التلقائي الوحيد
    عند إنشاء الاجتماع (راجعي docstring أعلى الملف). لا تكرار: الرئيس قد
    يكون أيضًا ضمن committee.members حسب لحظة الاستعلام، فنستبعد تكراره
    صراحة.
    """
    members = list(committee.members)
    if committee.chair is not None and committee.chair_user_id not in {m.user_id for m in members}:
        members.append(committee.chair)
    return members


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
    meetings = list(result.scalars().unique().all())
    for m in meetings:
        sync_meeting_status(m)
    return meetings


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
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
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
    meeting = await _load_meeting(db, meeting.meeting_id)
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
    await db.commit()
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
# (كان جاهزًا بالقاعدة منذ 0012، غير مستخدَم من أي API قبل الآن). التحميل
# (download) لا يمر عبر GET /documents/{document_id}/download العام، لأنه
# محمي بصلاحية Role نظامية ثابتة (documents.download) غالبًا لا يملكها
# عضو اللجنة العادي — بينما هو أصلًا يملك صلاحية meetings.attachments.view
# على مستوى دور اللجنة. لذلك get_attachment_download بالأسفل يعيد محتوى
# الملف مباشرة بعد التحقق من نفس صلاحية العرض، بمسار مخصص بوحدة الاجتماعات.


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


async def get_attachment_download(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[Document, bytes]:
    """يتطلب meetings.attachments.view — يرجع محتوى الملف الفعلي مباشرة (وليس
    عبر GET /documents، لأن ذلك يتطلب صلاحية documents.download المنفصلة
    التي لا يملكها أعضاء اللجنة غالبًا)."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db,
        actor,
        committee,
        "meetings.attachments.view",
        "ليست لديك صلاحية لعرض مرفقات هذا الاجتماع",
    )

    link_result = await db.execute(
        select(DocumentLink, Document)
        .join(Document, Document.document_id == DocumentLink.document_id)
        .where(
            DocumentLink.linked_entity_id == meeting_id,
            DocumentLink.document_id == document_id,
            DocumentLink.linked_entity_type.in_(_ATTACHMENT_LINK_TYPE.values()),
            Document.deleted_at.is_(None),
        )
    )
    row = link_result.first()
    if row is None:
        raise AttachmentNotFoundError("المرفق غير موجود ضمن هذا الاجتماع")
    document = row[1]
    content = await storage_client.download_object(document.storage_path)
    return document, content



# ============================== التسجيل الصوتي + المسودة (AI) ==============================
# راجعي رأس db/migrations/0025_meeting_recordings_and_drafts.sql للتصميم
# الكامل الموثّق (صلاحيات meetings.record_audio/draft.summarize/draft.view
# مزروعة أصلًا بكتالوج الصلاحيات منذ 0006). ملاحظة صلاحيات: meetings.summary.view
# محجوزة لعرض ملخّص مبسّط لعموم الأعضاء بمرحلة لاحقة — هذي المرحلة تكتفي
# بـmeetings.draft.view للوصول الكامل (رئيس اللجنة أساسًا).


class RecordingNotFoundError(Exception):
    """لا يوجد تسجيل صوتي مرفوع لهذا الاجتماع — تُترجَم إلى 404."""


class DraftNotFoundError(Exception):
    """لا توجد مسودة مولَّدة بعد لهذا الاجتماع — تُترجَم إلى 404."""


class ExtractedItemNotFoundError(Exception):
    """البند المستخرج غير موجود — تُترجَم إلى 404."""


async def upload_recording(
    db: AsyncSession,
    *,
    actor: User,
    meeting_id: uuid.UUID,
    file_name: str,
    mime_type: str,
    content: bytes,
    duration_seconds: int | None = None,
) -> MeetingRecording:
    """يتطلب meetings.record_audio. لا يمنع تكرار الرفع لنفس الاجتماع عمدًا
    (راجعي تعليق الجدول بالـmigration) — أحدث تسجيل هو المعتمَد ضمنيًا
    عند توليد المسودة (get_latest_recording أدناه)."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db,
        actor,
        committee,
        "meetings.record_audio",
        "ليست لديك صلاحية تسجيل هذا الاجتماع صوتيًا",
    )

    recording_id = uuid.uuid4()
    storage_path = f"meeting-recordings/{meeting_id}/{recording_id}_{file_name}"
    await storage_client.upload_object(storage_path, content, content_type=mime_type)

    recording = MeetingRecording(
        recording_id=recording_id,
        meeting_id=meeting_id,
        storage_path=storage_path,
        file_name=file_name,
        mime_type=mime_type,
        file_size_bytes=len(content),
        duration_seconds=duration_seconds,
        recorded_by=actor.user_id,
    )
    db.add(recording)
    await db.commit()
    await db.refresh(recording)
    return recording


async def get_latest_recording(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> MeetingRecording:
    """يتطلب meetings.record_audio — نفس صلاحية الرفع (من يقدر يسجّل يقدر
    يراجع/يحمّل التسجيل الخام)."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db, actor, committee, "meetings.record_audio", "ليست لديك صلاحية الوصول لتسجيل هذا الاجتماع"
    )

    result = await db.execute(
        select(MeetingRecording)
        .where(MeetingRecording.meeting_id == meeting_id, MeetingRecording.deleted_at.is_(None))
        .order_by(MeetingRecording.recorded_at.desc())
        .limit(1)
    )
    recording = result.scalar_one_or_none()
    if recording is None:
        raise RecordingNotFoundError("لا يوجد تسجيل صوتي لهذا الاجتماع بعد")
    return recording


async def download_recording(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> tuple[MeetingRecording, bytes]:
    """يتطلب meetings.record_audio — يرجع محتوى الملف الصوتي الفعلي (أحدث تسجيل)."""
    recording = await get_latest_recording(db, actor=actor, meeting_id=meeting_id)
    content = await storage_client.download_object(recording.storage_path)
    return recording, content


async def generate_draft(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> MeetingDraft:
    """يتطلب meetings.draft.summarize (FR-AI-001) — بشرط وجود تسجيل صوتي
    فعلي مسبقًا (MeetingValidationError إن لم يوجد، مطابقةً لنص المتطلب
    حرفيًا: "بشرط أن يكون التسجيل الصوتي متاح"). العملية مزامنة حاليًا
    (await مباشر لـgemini_client، بدون Background Job/Queue) — قرار
    مقصود لتبسيط هذي المرحلة الأولى؛ قابل للتحويل لاحقًا لو صارت مدة
    الانتظار مزعجة بالواجهة لاجتماعات طويلة جدًا."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db,
        actor,
        committee,
        "meetings.draft.summarize",
        "ليست لديك صلاحية تحويل تسجيل هذا الاجتماع إلى مسودة",
    )

    try:
        recording = await get_latest_recording(db, actor=actor, meeting_id=meeting_id)
    except RecordingNotFoundError as exc:
        raise MeetingValidationError(
            "لا يمكن توليد مسودة بدون تسجيل صوتي — يجب رفع تسجيل الاجتماع أولًا"
        ) from exc

    result = await db.execute(select(MeetingDraft).where(MeetingDraft.meeting_id == meeting_id))
    draft = result.scalar_one_or_none()
    if draft is None:
        draft = MeetingDraft(
            meeting_id=meeting_id,
            recording_id=recording.recording_id,
            generated_by=actor.user_id,
        )
        db.add(draft)
    else:
        draft.recording_id = recording.recording_id
        draft.generated_by = actor.user_id
    draft.status = MeetingDraftStatus.processing
    draft.error_message = None
    await db.commit()
    await db.refresh(draft)

    participant_names = [member.full_name for member in _all_committee_members(committee)]
    audio_content = await storage_client.download_object(recording.storage_path)

    try:
        generated = await gemini_client.generate_meeting_draft(
            meeting_title=meeting.title,
            participant_names=participant_names,
            audio_content=audio_content,
            audio_mime_type=recording.mime_type,
            audio_file_name=recording.file_name,
        )
    except gemini_client.GeminiError as exc:
        draft.status = MeetingDraftStatus.failed
        draft.error_message = str(exc)
        await db.commit()
        await db.refresh(draft)
        return draft

    draft.full_transcript = generated["full_transcript"]
    draft.summary = generated["summary"]
    draft.decisions = generated["decisions"]
    draft.action_items = generated["action_items"]
    draft.key_points = generated["key_points"]
    draft.recommendations = generated["recommendations"]
    draft.open_items = generated["open_items"]
    draft.compliance_notes = generated["compliance_notes"]
    draft.status = MeetingDraftStatus.completed
    draft.error_message = None
    draft.generated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(draft)
    return draft


async def get_draft(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> MeetingDraft:
    """يتطلب meetings.draft.view."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
    await _require_access(
        db, actor, committee, "meetings.draft.view", "ليست لديك صلاحية عرض مسودة هذا الاجتماع"
    )

    result = await db.execute(select(MeetingDraft).where(MeetingDraft.meeting_id == meeting_id))
    draft = result.scalar_one_or_none()
    if draft is None:
        raise DraftNotFoundError("لا توجد مسودة مولَّدة لهذا الاجتماع بعد")
    return draft

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
    """يتطلب meetings.draft.view."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
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
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
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
    await db.commit()
    return await _list_extracted_items_query(db, meeting_id)


async def add_manual_extracted_item(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, text: str
) -> MeetingExtractedItem:
    """FR-TASK-007/UC4: إضافة بند يدوي لقائمة البنود المعروضة."""
    meeting = await _load_meeting(db, meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
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
    await db.commit()
    await db.refresh(item)
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
    meeting = await _load_meeting(db, item.meeting_id)
    committee = await _load_committee(db, meeting.committee_id)
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
    meeting = await _load_meeting(db, item.meeting_id)

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
    await db.commit()
    await db.refresh(item)
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
    meeting = await _load_meeting(db, item.meeting_id)

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
    await db.commit()
    await db.refresh(item)
    return item, decision
