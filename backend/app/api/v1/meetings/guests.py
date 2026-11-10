"""
الهدف:
راوتات دخول الضيوف للاجتماع برابط عام (migration 0047 — قرار لاما 2026-11-10).
قواعد العمل والاستثناء الموثّق من NFR-SEC-001: راجعي رأس
app/services/meeting_guest_service.py.

قسمان:
1) لمن داخل الاجتماع (مصادَق — CurrentUser): رابط الضيوف وقاعة الانتظار.
   تحت /meetings/{meeting_id}/... (فيسمح بها enforce_guest_scope للضيف
   المقبول أيضًا — الضيف يقبل غيره مثل العضو).
2) عامة بدون تسجيل دخول (public_router): صفحة الدعوة، طلب الدخول، ومتابعته.
   تحت /public/... — لا تكشف إلا عنوان الاجتماع واسم اللجنة ووقته.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.meetings._errors import _SERVICE_ERRORS, _handle_errors
from app.core.dependencies import CurrentUser
from app.core.redis_client import create_session
from app.core.security import create_access_token, create_refresh_token
from app.db.session import get_db, writes_on_read
from app.schemas.meeting import (
    GuestJoinRequestCreatedOut,
    GuestJoinRequestIn,
    GuestLinkOut,
    GuestRequestSecretIn,
    GuestRequestStatusOut,
    MeetingGuestRequestOut,
    PublicMeetingInviteOut,
)
from app.services import meeting_guest_service
from app.services.meeting_guest_service import GuestRateLimitError, GuestRequestNotFoundError

router = APIRouter(prefix="/meetings", tags=["meeting-guests"])
public_router = APIRouter(prefix="/public", tags=["meeting-guests-public"])


def _guest_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, GuestRequestNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, GuestRateLimitError):
        return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    return _handle_errors(exc)


_ERRORS = (*_SERVICE_ERRORS, GuestRequestNotFoundError, GuestRateLimitError)


def _client_ip(request: Request) -> str | None:
    """
    عنوان العميل لحدود الطلبات. Render يمر عبر Cloudflare الذي يكتب
    CF-Connecting-IP/True-Client-IP بنفسه (يستبدل أي قيمة يرسلها العميل) —
    فتُقدَّم على X-Forwarded-For القابل للتزوير. ولأن العنوان قد يبقى قابلًا
    للتلاعب ببيئات أخرى، الخدمة تفرض أيضًا سقفًا لكل اجتماع لا يعتمد على
    العنوان إطلاقًا (MEETING_REQUEST_LIMIT) + حد المنتظرين (مراجعة PR #116).
    """
    for header in ("cf-connecting-ip", "true-client-ip"):
        value = request.headers.get(header)
        if value:
            return value.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.client.host if request.client else None


# ============================== لمن داخل الاجتماع ==============================


@router.get("/{meeting_id}/guest-link", response_model=GuestLinkOut)
@writes_on_read  # يُنشئ الرمز وسجل التدقيق أول مرة — معاملة واحدة كاملة
async def get_guest_link(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> GuestLinkOut:
    """رمز رابط الضيوف (يُنشأ أول مرة يُطلب فيها)."""
    try:
        token = await meeting_guest_service.get_or_create_guest_link(
            db, actor=current_user, meeting_id=meeting_id
        )
    except _ERRORS as exc:
        raise _guest_errors(exc) from exc
    return GuestLinkOut(token=token)


@router.post("/{meeting_id}/guest-link/rotate", response_model=GuestLinkOut)
async def rotate_guest_link(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> GuestLinkOut:
    """رابط جديد — السابق يتوقف فورًا."""
    try:
        token = await meeting_guest_service.rotate_guest_link(
            db, actor=current_user, meeting_id=meeting_id
        )
    except _ERRORS as exc:
        raise _guest_errors(exc) from exc
    return GuestLinkOut(token=token)


@router.get("/{meeting_id}/guest-requests", response_model=list[MeetingGuestRequestOut])
async def list_guest_requests(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[MeetingGuestRequestOut]:
    """الضيوف المنتظرون للقبول."""
    try:
        requests = await meeting_guest_service.list_pending_requests(
            db, actor=current_user, meeting_id=meeting_id
        )
    except _ERRORS as exc:
        raise _guest_errors(exc) from exc
    return [
        MeetingGuestRequestOut(
            request_id=r.request_id, display_name=r.display_name, status=r.status.value, created_at=r.created_at
        )
        for r in requests
    ]


async def _decide(
    meeting_id: uuid.UUID, request_id: uuid.UUID, current_user, db: AsyncSession, *, admit: bool
) -> MeetingGuestRequestOut:
    try:
        r = await meeting_guest_service.decide_guest_request(
            db, actor=current_user, meeting_id=meeting_id, request_id=request_id, admit=admit
        )
    except _ERRORS as exc:
        raise _guest_errors(exc) from exc
    return MeetingGuestRequestOut(
        request_id=r.request_id, display_name=r.display_name, status=r.status.value, created_at=r.created_at
    )


@router.post("/{meeting_id}/guest-requests/{request_id}/admit", response_model=MeetingGuestRequestOut)
async def admit_guest(
    meeting_id: uuid.UUID, request_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingGuestRequestOut:
    return await _decide(meeting_id, request_id, current_user, db, admit=True)


@router.post("/{meeting_id}/guest-requests/{request_id}/reject", response_model=MeetingGuestRequestOut)
async def reject_guest(
    meeting_id: uuid.UUID, request_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingGuestRequestOut:
    return await _decide(meeting_id, request_id, current_user, db, admit=False)


# ============================== عامة (بدون تسجيل دخول) ==============================


@public_router.get("/meeting-invites/{token}", response_model=PublicMeetingInviteOut)
async def get_public_invite(
    token: str, request: Request, db: AsyncSession = Depends(get_db)
) -> PublicMeetingInviteOut:
    try:
        await meeting_guest_service.check_public_rate_limit("invite", _client_ip(request))
        invite = await meeting_guest_service.get_public_invite(db, token=token)
    except _ERRORS as exc:
        raise _guest_errors(exc) from exc
    return PublicMeetingInviteOut(**invite.__dict__)


@public_router.post(
    "/meeting-invites/{token}/requests",
    response_model=GuestJoinRequestCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_guest_request(
    token: str, payload: GuestJoinRequestIn, request: Request, db: AsyncSession = Depends(get_db)
) -> GuestJoinRequestCreatedOut:
    try:
        await meeting_guest_service.check_public_rate_limit("create", _client_ip(request))
        created, secret = await meeting_guest_service.create_guest_request(
            db, token=token, display_name=payload.display_name, client_ip=_client_ip(request)
        )
    except _ERRORS as exc:
        raise _guest_errors(exc) from exc
    return GuestJoinRequestCreatedOut(request_id=created.request_id, secret=secret)


@public_router.post("/guest-requests/{request_id}/status", response_model=GuestRequestStatusOut)
async def guest_request_status(
    request_id: uuid.UUID, payload: GuestRequestSecretIn, request: Request, db: AsyncSession = Depends(get_db)
) -> GuestRequestStatusOut:
    """
    يُستدعى دوريًا من شاشة انتظار الضيف (POST حتى لا يظهر الرمز السري بالروابط/السجلات).
    عند القبول: جلسة جديدة للضيف (نفس آلية تسجيل الدخول — Redis + JWT) مع ملفه.
    """
    try:
        await meeting_guest_service.check_public_rate_limit("status", _client_ip(request))
        guest_request, guest = await meeting_guest_service.get_guest_request_status(
            db, request_id=request_id, secret=payload.secret
        )
    except _ERRORS as exc:
        raise _guest_errors(exc) from exc

    if guest is None:
        return GuestRequestStatusOut(status=guest_request.status.value)

    from app.api.v1.users import build_my_profile

    profile = await build_my_profile(db, guest)
    session_id = await create_session(guest.user_id)
    return GuestRequestStatusOut(
        status=guest_request.status.value,
        meeting_id=guest_request.meeting_id,
        access_token=create_access_token(guest.user_id, None, session_id),
        refresh_token=create_refresh_token(guest.user_id, session_id),
        user=profile,
    )


@public_router.post("/guest-requests/{request_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_guest_request(
    request_id: uuid.UUID, payload: GuestRequestSecretIn, request: Request, db: AsyncSession = Depends(get_db)
) -> None:
    try:
        await meeting_guest_service.check_public_rate_limit("cancel", _client_ip(request))
        await meeting_guest_service.cancel_guest_request(db, request_id=request_id, secret=payload.secret)
    except _ERRORS as exc:
        raise _guest_errors(exc) from exc
