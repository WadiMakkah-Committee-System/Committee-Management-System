"""
راوتات الرجوع لـAgora (قرار لاما 2026-11-04):
- الانضمام لغرفة Agora (توكن قصير العمر).
- التسجيل الصوتي لكل الأعضاء على دفعات (بدء / رفع قطعة / إيقاف / الحالة).

كل التفويض داخل طبقة الخدمة — راجعي app/services/meeting_service/agora.py
وrecording_sessions.py. أحداث التسجيل تُبث لغرفة الاجتماع (recording.state)
عشان مؤشر "جاري التسجيل" يظهر عند كل الحضور.
"""

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.socketio_server import sio
from app.db.session import get_db
from app.schemas.meeting import (
    AgoraJoinOut,
    RecordingChunkOut,
    RecordingSessionStartIn,
    RecordingSessionStopOut,
    RecordingStateOut,
)
from app.services import meeting_service
from app.services.meeting_service.recording_sessions import MAX_CHUNK_BYTES

from app.api.v1.meetings._errors import _SERVICE_ERRORS, _handle_errors

router = APIRouter(prefix="/meetings", tags=["meetings"])


async def broadcast_recording_state(meeting_id: uuid.UUID, state: meeting_service.RecordingState) -> None:
    """يبث حالة التسجيل لغرفة الاجتماع (Socket.IO). best-effort."""
    await sio.emit("recording.state", state.as_dict(), room=f"meeting:{meeting_id}")


@router.post("/{meeting_id}/agora/join", response_model=AgoraJoinOut)
async def join_agora(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> AgoraJoinOut:
    """
    توكن دخول غرفة Agora.
    - Authorization: meetings.join على لجنة الاجتماع.
    - 200: {app_id, channel, token, account, expires_at}.
    - 409: حضوري / مربوط بـTeams / انتهى. 503: مفاتيح Agora ناقصة بالخادم.
    """
    try:
        info = await meeting_service.join_agora(db, actor=current_user, meeting_id=meeting_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return AgoraJoinOut(
        app_id=info.app_id,
        channel=info.channel,
        token=info.token,
        account=info.account,
        expires_at=info.expires_at,
    )


@router.get("/{meeting_id}/recording-sessions/state", response_model=RecordingStateOut)
async def get_recording_state(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> RecordingStateOut:
    """حالة التسجيل الحالية — meetings.join."""
    try:
        state = await meeting_service.get_recording_state(db, actor=current_user, meeting_id=meeting_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return RecordingStateOut(**state.as_dict())


@router.post(
    "/{meeting_id}/recording-sessions", response_model=RecordingStateOut, status_code=status.HTTP_201_CREATED
)
async def start_recording(
    meeting_id: uuid.UUID,
    payload: RecordingSessionStartIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> RecordingStateOut:
    """
    بدء التسجيل (زر "تسجيل").
    - Authorization: meetings.record_audio (رئيس اللجنة).
    - 201: الحالة (session_id للرفع). 400: صيغة غير مدعومة.
    """
    try:
        _session, state = await meeting_service.start_recording_session(
            db, actor=current_user, meeting_id=meeting_id, mime_type=payload.mime_type
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    await broadcast_recording_state(meeting_id, state)
    return RecordingStateOut(**state.as_dict())


@router.put("/{meeting_id}/recording-sessions/{session_id}/chunks/{seq}", response_model=RecordingChunkOut)
async def upload_recording_chunk(
    meeting_id: uuid.UUID,
    session_id: uuid.UUID,
    seq: int,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> RecordingChunkOut:
    """
    رفع قطعة صوت (جسم الطلب = بايتات القطعة كما هي من MediaRecorder).
    - Authorization: صاحب الجلسة فقط.
    - 400: ترتيب/حجم غير صحيح. 409: الجلسة انتهت. 413: القطعة كبيرة.
    """
    content = bytearray()
    async for part in request.stream():
        content.extend(part)
        if len(content) > MAX_CHUNK_BYTES:
            from fastapi import HTTPException

            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="حجم القطعة أكبر من المسموح")
    try:
        session = await meeting_service.upload_recording_chunk(
            db, actor=current_user, meeting_id=meeting_id, session_id=session_id, seq=seq, content=bytes(content)
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return RecordingChunkOut(last_seq=session.last_seq)


@router.post("/{meeting_id}/recording-sessions/{session_id}/stop", response_model=RecordingSessionStopOut)
async def stop_recording(
    meeting_id: uuid.UUID,
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> RecordingSessionStopOut:
    """
    إيقاف التسجيل ودمج القطع بملف واحد (يدخل مسار المسودة).
    - Authorization: meetings.record_audio.
    - 200: {status: finalized|failed, recording_id, error_message}.
    """
    try:
        session, state = await meeting_service.stop_recording_session(
            db, actor=current_user, meeting_id=meeting_id, session_id=session_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    await broadcast_recording_state(meeting_id, state)
    return RecordingSessionStopOut(
        status=session.status, recording_id=session.recording_id, error_message=session.error_message
    )
