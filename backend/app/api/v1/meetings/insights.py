"""
الهدف: راوتات الدفعة 3 من تحسينات الاجتماع (migration 0044 — قرار لاما 2026-11-03):
حفظ الترجمة النصية الحية، "وش فاتني؟"، وإحصائيات الاجتماع.
راجعي app/services/meeting_service/insights.py للقواعد.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import gemini_client
from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.meeting import (
    AgendaStatOut,
    CatchUpIn,
    CatchUpOut,
    MeetingInsightsOut,
    SpeakerStatOut,
    TranscriptSegmentsIn,
    TranscriptSegmentsSavedOut,
)
from app.services import meeting_service

from app.api.v1.meetings._errors import _SERVICE_ERRORS, _handle_errors

router = APIRouter(prefix="/meetings", tags=["meetings"])
logger = logging.getLogger(__name__)


@router.post("/{meeting_id}/transcript/segments", response_model=TranscriptSegmentsSavedOut)
async def save_transcript_segments(
    meeting_id: uuid.UUID,
    payload: TranscriptSegmentsIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TranscriptSegmentsSavedOut:
    """
    حفظ دفعة جمل مكتملة من الترجمة النصية الحية (جهاز رئيس اللجنة كل ثواني).
    - Authorization: meetings.agenda.item.update. المكرر (نفس client_key) يُتجاهل.
    """
    try:
        saved = await meeting_service.save_transcript_segments(
            db,
            actor=current_user,
            meeting_id=meeting_id,
            segments=[meeting_service.TranscriptSegmentIn(**s.model_dump()) for s in payload.segments],
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return TranscriptSegmentsSavedOut(saved=saved)


@router.post("/{meeting_id}/catch-up", response_model=CatchUpOut)
async def catch_up(
    meeting_id: uuid.UUID, payload: CatchUpIn, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> CatchUpOut:
    """
    "وش فاتني؟" — ملخص آخر دقائق من الاجتماع (Gemini).
    - Authorization: meetings.join. 200: {summary|null, segments}. 502: فشل Gemini. 503: غير مهيّأ.
    """
    try:
        summary, count = await meeting_service.meeting_catch_up(
            db, actor=current_user, meeting_id=meeting_id, minutes=payload.minutes
        )
    except gemini_client.GeminiNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="الذكاء الاصطناعي غير مهيّأ") from exc
    except gemini_client.GeminiError as exc:
        logger.warning("catch-up Gemini error: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="تعذّر تجهيز الملخص، حاول بعد قليل") from exc
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return CatchUpOut(summary=summary, segments=count)


@router.get("/{meeting_id}/insights", response_model=MeetingInsightsOut)
async def get_meeting_insights(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingInsightsOut:
    """
    إحصائيات الاجتماع: المدة، نسبة الحضور، مدة كلام كل متحدث (تقديرية)، ووقت كل بند.
    - Authorization: meetings.view.
    """
    try:
        data = await meeting_service.meeting_insights(db, actor=current_user, meeting_id=meeting_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return MeetingInsightsOut(
        duration_seconds=data.duration_seconds,
        attended_members=data.attended_members,
        total_members=data.total_members,
        speakers=[SpeakerStatOut(**s.__dict__) for s in data.speakers],
        agenda=[AgendaStatOut(**a.__dict__) for a in data.agenda],
        has_transcript=data.has_transcript,
    )
