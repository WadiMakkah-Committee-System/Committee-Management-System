"""
راوتات تكامل Microsoft Teams للاجتماعات عن بعد (migration 0041) — راجعي
رأس app/services/meeting_service/teams.py لقواعد العمل كاملة.

كل التفويض داخل طبقة الخدمة (نفس نمط بقية راوتات الاجتماعات): الصلاحية
مرتبطة بلجنة الاجتماع تحديدًا (System Role أو Committee Role).
"""

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.meeting import TeamsCallTokenIn, TeamsCallTokenOut, TeamsJoinOut, TeamsKnownGuestOut, TeamsRecordingOut
from app.services import meeting_service

from app.api.v1.meetings._errors import _SERVICE_ERRORS, _handle_errors

router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.get("/{meeting_id}/teams/join", response_model=TeamsJoinOut)
async def get_teams_join_url(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> TeamsJoinOut:
    """
    رابط الانضمام لاجتماع Teams.

    - Authentication: JWT إلزامي.
    - Authorization: meetings.join على لجنة الاجتماع.
    - 200: {join_url}.
    - 403: لا يملك الصلاحية. 404: الاجتماع غير موجود.
    - 409: اجتماع حضوري، أو غير مربوط بـTeams، أو انتهى.
    """
    try:
        join_url = await meeting_service.get_teams_join_url(db, actor=current_user, meeting_id=meeting_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return TeamsJoinOut(join_url=join_url)


@router.post("/{meeting_id}/teams/call-token", response_model=TeamsCallTokenOut)
async def get_teams_call_token(
    meeting_id: uuid.UUID,
    current_user: CurrentUser,
    payload: TeamsCallTokenIn | None = None,
    db: AsyncSession = Depends(get_db),
) -> TeamsCallTokenOut:
    """
    تجربة (poc/acs-teams-embed): بيانات الانضمام لاجتماع Teams من داخل واجهة
    المنصة عبر Azure Communication Services.

    - Authentication: JWT إلزامي. Authorization: meetings.join على لجنة الاجتماع.
    - Body اختياري: {microsoft_token} — لو أُرسل يدخل المستخدم بحسابه في
      Microsoft 365 (identity="teams_user")، وإلا كضيف (identity="guest").
    - 200: {token, expires_on, join_url, display_name, identity}.
    - 403 / 404 / 409 كما بـ/teams/join، و403 أيضًا لو رُفض توكن Microsoft.
      502: فشل ACS. 503: ACS غير مهيّأ.
    POST (لا GET) لأن كل طلب ينشئ هوية ACS جديدة (ليس عملية قراءة).
    """
    try:
        token, join_url, display_name, identity = await meeting_service.get_teams_call_token(
            db,
            actor=current_user,
            meeting_id=meeting_id,
            microsoft_token=payload.microsoft_token if payload else None,
            microsoft_object_id=payload.microsoft_object_id if payload else None,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return TeamsCallTokenOut(
        token=token.token,
        expires_on=token.expires_on,
        join_url=join_url,
        display_name=display_name,
        identity=identity,
    )


@router.get("/{meeting_id}/teams/known-guests", response_model=list[TeamsKnownGuestOut])
async def list_teams_known_guests(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[TeamsKnownGuestOut]:
    """
    ضيوف الاجتماع اللي دخلوا من المنصة (أعضاء مصرّح لهم) — جهاز الموظف الداخل
    بحساب Microsoft يقبلهم من قاعة الانتظار تلقائيًا (قرار لاما 2026-11-03).

    - Authorization: meetings.join على لجنة الاجتماع.
    - 200: قائمة {acs_user_id, user_id, display_name} (قد تكون فارغة).
    - 403 / 404 / 409 كما بـ/teams/join.
    """
    try:
        guests = await meeting_service.list_teams_known_guests(db, actor=current_user, meeting_id=meeting_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return [TeamsKnownGuestOut(acs_user_id=g.acs_user_id, user_id=g.user_id, display_name=g.display_name) for g in guests]


@router.get("/{meeting_id}/teams/recordings", response_model=list[TeamsRecordingOut])
async def list_teams_recordings(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[TeamsRecordingOut]:
    """
    قائمة تسجيلات Teams للاجتماع (مرتبة زمنيًا).

    - Authorization: meetings.record_audio على لجنة الاجتماع.
    - 200: قائمة (قد تكون فارغة: لم يُسجَّل، أو انتهت مدة احتفاظ Teams).
    - 403 / 404 / 409 كما أعلاه. 502: فشل Microsoft Graph. 503: التكامل غير مهيّأ.
    """
    try:
        recordings = await meeting_service.list_teams_recordings(db, actor=current_user, meeting_id=meeting_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return [TeamsRecordingOut(recording_id=r.artifact_id, created_at=r.created_at) for r in recordings]


@router.get("/{meeting_id}/teams/recordings/{recording_id}/content")
async def download_teams_recording(
    meeting_id: uuid.UUID,
    recording_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    محتوى تسجيل Teams — يُبث عبر الباك-إند تدريجيًا (بلا تخزين نسخة عندنا،
    وبلا تحميل الملف كاملًا بالذاكرة).

    - Authorization: meetings.record_audio على لجنة الاجتماع.
    - 200: الملف (video/mp4 عادة).
    - 404: التسجيل غير موجود لهذا الاجتماع في Teams. بقية الرموز كما أعلاه.
    """
    try:
        stream = await meeting_service.open_teams_recording(
            db, actor=current_user, meeting_id=meeting_id, recording_id=recording_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    headers = {"Content-Disposition": f'attachment; filename="meeting-{meeting_id}.mp4"'}
    if stream.content_length:
        headers["Content-Length"] = stream.content_length
    return StreamingResponse(stream.chunks, media_type=stream.content_type, headers=headers)
