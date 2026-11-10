"""
الهدف:
دخول ضيوف من خارج المنصة للاجتماع برابط عام (قرار لاما 2026-11-10 —
migration 0047).

⚠️ استثناء موثّق من NFR-SEC-001 (التحقق من الهوية قبل الوصول) ومن
FR-MEET-001/002 (الاجتماعات للأدمن/رئيس اللجنة/عضو اللجنة فقط) بقرار لاما.
التخفيف المطبَّق هنا:
- لا دخول بدون قبول صريح من شخص داخل الاجتماع.
- الضيف المقبول = حساب مؤقت (users.is_guest) فكل عملياته تُسجَّل باسمه
  (NFR-SEC-004)، بلا دور نظامي، ولا يسجل دخول بكلمة مرور.
- توكن الضيف محصور باجتماعه فقط (enforce_guest_scope — تُستدعى من
  core.dependencies.get_current_user لكل طلب، ومن socketio_server.connect).
- الرابط رمز عشوائي (ليس meeting_id)، قابل للتغيير، ويتوقف بانتهاء الاجتماع.
- حد أعلى للطلبات (لكل عنوان IP، ولكل اجتماع).

قواعد العمل (لاما 2026-11-10):
1) لكل اجتماع رابط ضيوف واحد يُنسخ ويُرسل لأشخاص محددين.
2) الضيف: اسمه ← فحص المايك والكاميرا (بالواجهة) ← ينتظر.
3) أي شخص داخل الاجتماع يقبله أو يرفضه (صلاحية meetings.join — يشمل
   الضيوف المقبولين أنفسهم، لأن الضيف يسوي كل ما يسويه العضو).
4) بعد القبول: صلاحيات "عضو اللجنة" كاملة داخل هذا الاجتماع فقط
   (guest_committee_codes)، ويظهر بجانب اسمه "ضيف".
5) يُكتب في المحضر "ضيف خارجي".

قرارات تصميم (Claude — قابلة للمراجعة):
- إنشاء الرابط ونسخه: meetings.join (أي عضو داخل الاجتماع يقدر يشاركه).
  تغيير الرابط (إيقاف القديم): meetings.update (رئيس اللجنة/المدير).
- الاجتماع الحضوري لا رابط ضيوف له (لا غرفة اتصال أصلًا).
- رابط الضيوف يعمل والاجتماع upcoming/ongoing فقط.
"""

import hashlib
import hmac
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import redis_client
from app.core.security import hash_password
from app.models.committee import Committee
from app.models.decision import Decision
from app.models.meeting import Meeting, MeetingMode, MeetingStatus
from app.models.meeting_guest import MeetingGuestRequest, MeetingGuestRequestStatus
from app.models.role import Permission, Role, RolePermission
from app.models.user import User, UserStatus
from app.services import audit_service
from app.services.meeting_service.access import _require_access
from app.services.meeting_service.errors import (
    MeetingForbiddenError,
    MeetingInvalidStateError,
    MeetingNotFoundError,
    MeetingValidationError,
)
from app.services.meeting_service.loading import load_meeting, sync_meeting_status

logger = logging.getLogger(__name__)

GUEST_ACTIVE_STATUSES = (MeetingStatus.upcoming, MeetingStatus.ongoing)
MAX_PENDING_PER_MEETING = 30
# حد طلبات الدخول لكل (عنوان IP، اجتماع) خلال نافذة زمنية.
IP_REQUEST_LIMIT = 8
IP_REQUEST_WINDOW_SECONDS = 600
# حد إجمالي لطلبات الدخول للاجتماع الواحد بنفس النافذة — لا يعتمد على عنوان
# IP إطلاقًا (X-Forwarded-For قابل للتزوير)، فيبقى سقفًا ثابتًا حتى لو تلاعب
# أحد بالعنوان (مراجعة PR #116).
MEETING_REQUEST_LIMIT = 60
# حدود عامة لكل عنوان IP على الراوتات العامة قبل أي استعلام بالقاعدة
# (نافذة دقيقة): صفحة الدعوة، طلب الدخول، متابعة الطلب (استطلاع كل 3 ثوانٍ)، الإلغاء.
PUBLIC_IP_LIMITS = {"invite": 60, "create": 20, "status": 90, "cancel": 20}
PUBLIC_IP_WINDOW_SECONDS = 60
DISPLAY_NAME_MIN = 2
DISPLAY_NAME_MAX = 60


class GuestRequestNotFoundError(Exception):
    """طلب دخول غير موجود أو رمزه السري غير مطابق — 404 (بدون كشف أيهما)."""


class GuestRateLimitError(Exception):
    """طلبات كثيرة من نفس الجهاز/لنفس الاجتماع — 429."""


# ============================== أدوات داخلية ==============================


def _new_link_token() -> str:
    return secrets.token_urlsafe(32)


def _hash_secret(secret: str) -> str:
    # الرمز السري عشوائي 256-bit — SHA-256 كافٍ (لا حاجة لـbcrypt البطيء هنا).
    return hashlib.sha256(secret.encode()).hexdigest()


def _clean_display_name(raw: str) -> str:
    name = re.sub(r"\s+", " ", (raw or "")).strip()
    if not (DISPLAY_NAME_MIN <= len(name) <= DISPLAY_NAME_MAX):
        raise MeetingValidationError(
            f"الاسم لازم يكون بين {DISPLAY_NAME_MIN} و{DISPLAY_NAME_MAX} حرفًا"
        )
    return name


def is_guest_meeting_active(meeting: Meeting) -> bool:
    sync_meeting_status(meeting)
    return not meeting.is_deleted and meeting.status in GUEST_ACTIVE_STATUSES


def _room(meeting_id: uuid.UUID | str) -> str:
    return f"meeting:{meeting_id}"


async def _emit(event: str, meeting_id: uuid.UUID, payload: dict) -> None:
    # استيراد متأخر: socketio_server يستورد خدمات الاجتماعات (تفادي دائرية).
    try:
        from app.core.socketio_server import sio

        await sio.emit(event, payload, room=_room(meeting_id))
    except Exception:  # noqa: BLE001 — البث تحسين فوري فقط، الواجهة تجلب دوريًا أيضًا
        logger.warning("meeting_guest_service: تعذّر بث %s", event, exc_info=True)


async def _load_meeting_by_token(db: AsyncSession, token: str) -> Meeting:
    if not token or len(token) > 64:
        raise MeetingNotFoundError("رابط الدعوة غير صالح")
    result = await db.execute(
        select(Meeting).where(Meeting.guest_link_token == token, Meeting.deleted_at.is_(None))
    )
    meeting = result.scalar_one_or_none()
    if meeting is None:
        raise MeetingNotFoundError("رابط الدعوة غير صالح أو تم إيقافه")
    return meeting


def _guest_link_supported(meeting: Meeting) -> bool:
    # اجتماعات Teams (مزوّد احتياطي محفوظ — قرار لاما 2026-11-04) لها قاعة
    # انتظار Teams الخاصة، وغرفتها بالمنصة تتطلب حساب Microsoft — رابط ضيوف
    # المنصة لاجتماعات Agora فقط (مراجعة PR #116).
    return meeting.mode == MeetingMode.remote and not meeting.teams_meeting_id


def _require_guest_link_usable(meeting: Meeting) -> None:
    if meeting.mode != MeetingMode.remote:
        raise MeetingInvalidStateError("هذا اجتماع حضوري — لا يمكن الانضمام له عن بُعد")
    if meeting.teams_meeting_id:
        raise MeetingInvalidStateError("اجتماعات Teams تستخدم رابط Teams نفسه لدعوة الضيوف")
    if not is_guest_meeting_active(meeting):
        raise MeetingInvalidStateError("انتهى هذا الاجتماع")


# ============================== رابط الضيوف (لمن داخل الاجتماع) ==============================


async def get_or_create_guest_link(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> str:
    meeting = await load_meeting(db, meeting_id)
    await _require_access(
        db, actor, meeting.committee, "meetings.join", "ليست لديك صلاحية مشاركة رابط هذا الاجتماع"
    )
    _require_guest_link_usable(meeting)
    if meeting.guest_link_token is None:
        meeting.guest_link_token = _new_link_token()
        await audit_service.log_action(
            db,
            actor_user_id=actor.user_id,
            action_type="update",
            target_type="meeting",
            target_id=meeting.meeting_id,
            metadata={"event": "guest_link_created"},
        )
        await db.commit()
    return meeting.guest_link_token


async def rotate_guest_link(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> str:
    """رابط جديد — الرابط السابق يتوقف فورًا (لو انتشر لأحد غير مقصود)."""
    meeting = await load_meeting(db, meeting_id)
    await _require_access(
        db, actor, meeting.committee, "meetings.update", "ليست لديك صلاحية تغيير رابط هذا الاجتماع"
    )
    _require_guest_link_usable(meeting)
    meeting.guest_link_token = _new_link_token()
    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="meeting",
        target_id=meeting.meeting_id,
        metadata={"event": "guest_link_rotated"},
    )
    await db.commit()
    return meeting.guest_link_token


# ============================== صفحة الدعوة العامة (بدون تسجيل دخول) ==============================


@dataclass
class PublicInvite:
    title: str
    committee_name: str | None
    scheduled_at: datetime
    scheduled_end_at: datetime | None
    status: MeetingStatus
    is_open: bool


async def get_public_invite(db: AsyncSession, *, token: str) -> PublicInvite:
    """أقل قدر من البيانات: العنوان واسم اللجنة والوقت فقط — لا أجندة ولا أعضاء."""
    meeting = await _load_meeting_by_token(db, token)
    committee_name = await db.scalar(
        select(Committee.name).where(Committee.committee_id == meeting.committee_id)
    )
    is_open = _guest_link_supported(meeting) and is_guest_meeting_active(meeting)
    return PublicInvite(
        title=meeting.title,
        committee_name=committee_name,
        scheduled_at=meeting.scheduled_at,
        scheduled_end_at=meeting.scheduled_end_at,
        status=meeting.status,
        is_open=is_open,
    )


async def _hit(key: str, limit: int, window_seconds: int) -> bool:
    """عدّاد Redis بنافذة ثابتة — True لو تجاوز الحد. تعطّل Redis لا يمنع الضيوف."""
    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, window_seconds)
    except Exception:  # noqa: BLE001
        logger.warning("meeting_guest_service: تعذّر فحص حد الطلبات (%s)", key, exc_info=True)
        return False
    return count > limit


async def check_public_rate_limit(endpoint: str, client_ip: str | None) -> None:
    """حد عام لكل IP على الراوتات العامة — يُستدعى قبل أي استعلام بالقاعدة."""
    if not client_ip:
        return
    if await _hit(f"guest_pub_rl:{endpoint}:{client_ip}", PUBLIC_IP_LIMITS[endpoint], PUBLIC_IP_WINDOW_SECONDS):
        raise GuestRateLimitError("طلبات كثيرة من هذا الجهاز — حاول بعد قليل")


async def _check_rate_limit(meeting_id: uuid.UUID, client_ip: str | None) -> None:
    if await _hit(f"guest_req_rl_meeting:{meeting_id}", MEETING_REQUEST_LIMIT, IP_REQUEST_WINDOW_SECONDS):
        raise GuestRateLimitError("طلبات دخول كثيرة لهذا الاجتماع — حاول بعد دقائق")
    if client_ip and await _hit(
        f"guest_req_rl:{meeting_id}:{client_ip}", IP_REQUEST_LIMIT, IP_REQUEST_WINDOW_SECONDS
    ):
        raise GuestRateLimitError("طلبات كثيرة من هذا الجهاز — حاول بعد دقائق")


async def create_guest_request(
    db: AsyncSession, *, token: str, display_name: str, client_ip: str | None
) -> tuple[MeetingGuestRequest, str]:
    """يرجع (الطلب، الرمز السري). الرمز يُعطى للضيف مرة واحدة ولا يُخزَّن إلا مُجزّأً."""
    meeting = await _load_meeting_by_token(db, token)
    _require_guest_link_usable(meeting)
    name = _clean_display_name(display_name)
    await _check_rate_limit(meeting.meeting_id, client_ip)

    pending = await db.scalar(
        select(func.count())
        .select_from(MeetingGuestRequest)
        .where(
            MeetingGuestRequest.meeting_id == meeting.meeting_id,
            MeetingGuestRequest.status == MeetingGuestRequestStatus.pending,
        )
    )
    if (pending or 0) >= MAX_PENDING_PER_MEETING:
        raise GuestRateLimitError("قاعة الانتظار ممتلئة حاليًا — حاول بعد قليل")

    secret = secrets.token_urlsafe(32)
    request = MeetingGuestRequest(
        meeting_id=meeting.meeting_id,
        display_name=name,
        request_secret_hash=_hash_secret(secret),
    )
    db.add(request)
    await db.flush()
    await audit_service.log_action(
        db,
        actor_user_id=None,
        action_type="create",
        target_type="meeting_guest_request",
        target_id=request.request_id,
        metadata={"meeting_id": str(meeting.meeting_id), "display_name": name},
    )
    await db.commit()
    await _emit(
        "guests.requested",
        meeting.meeting_id,
        {"request_id": str(request.request_id), "display_name": name},
    )
    return request, secret


async def _load_request_with_secret(
    db: AsyncSession, request_id: uuid.UUID, secret: str, *, for_update: bool = False
) -> MeetingGuestRequest:
    # التحقق من الرمز السري أولًا بلا قفل — طلب برمز خاطئ لا يقفل الصف أبدًا.
    secret_hash = await db.scalar(
        select(MeetingGuestRequest.request_secret_hash).where(MeetingGuestRequest.request_id == request_id)
    )
    if secret_hash is None or not hmac.compare_digest(secret_hash, _hash_secret(secret or "")):
        raise GuestRequestNotFoundError("طلب الدخول غير موجود")
    stmt = select(MeetingGuestRequest).where(MeetingGuestRequest.request_id == request_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one()


async def get_guest_request_status(
    db: AsyncSession, *, request_id: uuid.UUID, secret: str
) -> tuple[MeetingGuestRequest, User | None]:
    """
    حالة الطلب للضيف المنتظر (يُستدعى دوريًا من صفحة الانتظار). لو انتهى
    الاجتماع والطلب ما زال منتظرًا يتحوّل "ملغى". يرجع حساب الضيف لو مقبولًا
    ونشطًا (طبقة الـAPI تصدر له جلسة).
    """
    request = await _load_request_with_secret(db, request_id, secret, for_update=True)
    meeting = await db.get(Meeting, request.meeting_id)
    active = meeting is not None and is_guest_meeting_active(meeting)

    if request.status == MeetingGuestRequestStatus.pending and not active:
        request.status = MeetingGuestRequestStatus.cancelled
        await db.commit()
        return request, None

    if request.status == MeetingGuestRequestStatus.admitted and active and request.user_id:
        from app.services import user_service

        guest = await user_service.get_user(db, request.user_id)
        if guest is not None and guest.status == UserStatus.active:
            return request, guest
    return request, None


async def cancel_guest_request(db: AsyncSession, *, request_id: uuid.UUID, secret: str) -> None:
    request = await _load_request_with_secret(db, request_id, secret, for_update=True)
    if request.status != MeetingGuestRequestStatus.pending:
        return
    request.status = MeetingGuestRequestStatus.cancelled
    await db.commit()
    await _emit("guests.updated", request.meeting_id, {"request_id": str(request.request_id)})


# ============================== قاعة الانتظار (لمن داخل الاجتماع) ==============================


async def list_pending_requests(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID
) -> list[MeetingGuestRequest]:
    meeting = await load_meeting(db, meeting_id)
    await _require_access(
        db, actor, meeting.committee, "meetings.join", "ليست لديك صلاحية عرض قاعة الانتظار"
    )
    if not is_guest_meeting_active(meeting):
        return []
    result = await db.execute(
        select(MeetingGuestRequest)
        .where(
            MeetingGuestRequest.meeting_id == meeting_id,
            MeetingGuestRequest.status == MeetingGuestRequestStatus.pending,
        )
        .order_by(MeetingGuestRequest.created_at)
    )
    return list(result.scalars().all())


async def _create_guest_user(db: AsyncSession, *, request: MeetingGuestRequest) -> User:
    short = request.request_id.hex[:12]
    guest = User(
        first_name=request.display_name[:100],
        middle_name="",
        last_name="",
        username=f"guest_{short}",
        # نطاق .invalid محجوز (RFC 2606) — لا يستقبل بريدًا أبدًا.
        email=f"guest-{request.request_id}@guests.invalid",
        # كلمة مرور عشوائية لا يعرفها أحد — والدخول بكلمة المرور مرفوض للضيف أصلًا.
        password_hash=hash_password(secrets.token_urlsafe(32)),
        role_id=None,
        dep_id=None,
        status=UserStatus.active,
        must_change_password=False,
        is_guest=True,
        guest_meeting_id=request.meeting_id,
    )
    db.add(guest)
    await db.flush()
    return guest


async def decide_guest_request(
    db: AsyncSession,
    *,
    actor: User,
    meeting_id: uuid.UUID,
    request_id: uuid.UUID,
    admit: bool,
) -> MeetingGuestRequest:
    meeting = await load_meeting(db, meeting_id)
    await _require_access(
        db, actor, meeting.committee, "meetings.join", "ليست لديك صلاحية قبول الضيوف"
    )
    if not is_guest_meeting_active(meeting):
        raise MeetingInvalidStateError("انتهى هذا الاجتماع")

    # قفل الصف: شخصان يضغطان "قبول" بنفس اللحظة لا ينشئان حسابين.
    request = (
        await db.execute(
            select(MeetingGuestRequest)
            .where(
                MeetingGuestRequest.request_id == request_id,
                MeetingGuestRequest.meeting_id == meeting_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if request is None:
        raise GuestRequestNotFoundError("طلب الدخول غير موجود")
    if request.status != MeetingGuestRequestStatus.pending:
        raise MeetingInvalidStateError("تم البت في هذا الطلب مسبقًا أو ألغاه الضيف")

    # الحساب أولًا (flush) ثم كل حقول القرار معًا — قيود 0047 تفرض تلازم
    # الحالة/الحساب/من قرّر، وأي flush وسطي بحالة جزئية يُرفض.
    guest = await _create_guest_user(db, request=request) if admit else None
    request.decided_by = actor.user_id
    request.decided_at = datetime.now(UTC)
    if guest is not None:
        request.user_id = guest.user_id
        request.status = MeetingGuestRequestStatus.admitted
    else:
        request.status = MeetingGuestRequestStatus.rejected

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="approve" if admit else "reject",
        target_type="meeting_guest_request",
        target_id=request.request_id,
        metadata={
            "meeting_id": str(meeting_id),
            "display_name": request.display_name,
            "guest_user_id": str(request.user_id) if request.user_id else None,
        },
    )
    await db.commit()
    await _emit(
        "guests.updated",
        meeting_id,
        {
            "request_id": str(request.request_id),
            "status": request.status.value,
            "display_name": request.display_name,
            "decided_by_name": actor.full_name,
        },
    )
    return request


async def list_admitted_guests(db: AsyncSession, meeting_id: uuid.UUID) -> list[User]:
    result = await db.execute(
        select(User)
        .where(User.is_guest.is_(True), User.guest_meeting_id == meeting_id, User.deleted_at.is_(None))
        .order_by(User.created_at)
    )
    return list(result.scalars().all())


# ============================== صلاحيات الضيف ونطاقه ==============================


async def _member_role_codes(db: AsyncSession) -> set[str]:
    result = await db.execute(
        select(Permission.code)
        .select_from(Role)
        .join(RolePermission, RolePermission.role_id == Role.role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(Role.committee_role_slug == "member")
    )
    return set(result.scalars().all())


async def guest_committee_codes(
    db: AsyncSession, *, user_id: uuid.UUID, committee_id: uuid.UUID
) -> set[str]:
    """
    صلاحيات "عضو اللجنة" لضيف مقبول باجتماع تابع لهذه اللجنة — وإلا فارغة.
    يُستدعى فقط حين لا يملك المستخدم أي عضوية فعلية باللجنة (لا تكلفة على
    الأعضاء). حصر الضيف باجتماعه نفسه (وليس كل اجتماعات اللجنة) يتم في
    enforce_guest_scope / socketio connect.
    """
    found = await db.scalar(
        select(User.user_id)
        .join(Meeting, Meeting.meeting_id == User.guest_meeting_id)
        .where(
            User.user_id == user_id,
            User.is_guest.is_(True),
            User.deleted_at.is_(None),
            Meeting.committee_id == committee_id,
            Meeting.deleted_at.is_(None),
        )
    )
    if found is None:
        return set()
    return await _member_role_codes(db)


_UUID_RE = r"[0-9a-fA-F-]{36}"
_DECISION_PATH = re.compile(rf"^/api/v1/decisions/({_UUID_RE})(/.*)?$")


async def enforce_guest_scope(
    db: AsyncSession, *, user: User, method: str, path: str, query_params: dict[str, str]
) -> None:
    """
    يُستدعى لكل طلب HTTP من حساب ضيف (core.dependencies.get_current_user).
    يرمي GuestScopeError(401 لو انتهى الاجتماع، 403 لأي مسار خارج اجتماعه).
    """
    meeting = await db.get(Meeting, user.guest_meeting_id) if user.guest_meeting_id else None
    if meeting is None or not is_guest_meeting_active(meeting):
        raise GuestSessionEndedError("انتهى الاجتماع — شكرًا لحضورك")

    gm = str(meeting.meeting_id)
    if method == "GET" and path == "/api/v1/users/me":
        return
    if path == f"/api/v1/meetings/{gm}" or path.startswith(f"/api/v1/meetings/{gm}/"):
        return
    if method == "GET" and path == "/api/v1/decisions" and query_params.get("meeting_id") == gm:
        return
    match = _DECISION_PATH.match(path)
    if match:
        try:
            decision_id = uuid.UUID(match.group(1))
        except ValueError:
            decision_id = None
        if decision_id is not None:
            decision_meeting = await db.scalar(
                select(Decision.meeting_id).where(Decision.decision_id == decision_id)
            )
            if decision_meeting is not None and str(decision_meeting) == gm:
                return
    raise MeetingForbiddenError("حساب الضيف يقتصر على الاجتماع المدعو إليه فقط")


class GuestSessionEndedError(Exception):
    """انتهى اجتماع الضيف (أو حُذف) — جلسته لم تعد صالحة (401)."""
