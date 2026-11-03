"""
الهدف: راوتات الحضور التلقائي لاجتماعات Teams المدمجة (migration 0043 — قرار لاما 2026-11-03).
راجعي app/services/meeting_service/attendance.py للقواعد.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.committee import CommitteeMemberUserOut
from app.schemas.meeting import (
    MeetingAttendanceHeartbeatOut,
    MeetingAttendanceRowOut,
    MeetingAttendanceSessionOut,
)
from app.services import meeting_service

from app.api.v1.meetings._errors import _SERVICE_ERRORS, _handle_errors

router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.post(
    "/{meeting_id}/attendance", response_model=MeetingAttendanceSessionOut, status_code=status.HTTP_201_CREATED
)
async def start_attendance(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingAttendanceSessionOut:
    """
    بداية جلسة حضور — الواجهة تناديها لحظة دخول العضو الفعلي للاجتماع.
    - Authorization: meetings.join. 201: {attendance_id}. 403/404/409.
    """
    try:
        session = await meeting_service.start_attendance_session(db, actor=current_user, meeting_id=meeting_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return MeetingAttendanceSessionOut(attendance_id=session.attendance_id)


@router.post("/{meeting_id}/attendance/{attendance_id}/heartbeat", response_model=MeetingAttendanceHeartbeatOut)
async def attendance_heartbeat(
    meeting_id: uuid.UUID, attendance_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingAttendanceHeartbeatOut:
    """نبضة "لسا داخل" (كل دقيقة تقريبًا). جلسات المستخدم نفسه فقط."""
    active = await meeting_service.attendance_heartbeat(
        db, actor=current_user, meeting_id=meeting_id, attendance_id=attendance_id
    )
    return MeetingAttendanceHeartbeatOut(active=active)


@router.post("/{meeting_id}/attendance/{attendance_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def end_attendance(
    meeting_id: uuid.UUID, attendance_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    """خروج العضو من الاجتماع (مغادرة/إغلاق الصفحة). جلسات المستخدم نفسه فقط."""
    await meeting_service.end_attendance_session(
        db, actor=current_user, meeting_id=meeting_id, attendance_id=attendance_id
    )


@router.get("/{meeting_id}/attendance", response_model=list[MeetingAttendanceRowOut])
async def list_attendance(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[MeetingAttendanceRowOut]:
    """
    جدول الحضور (لكل عضو: أول دخول، آخر خروج، إجمالي المدة، عدد مرات الدخول).
    - Authorization: meetings.view. 200: قائمة مرتبة بأول دخول.
    """
    try:
        rows = await meeting_service.attendance_summary(db, actor=current_user, meeting_id=meeting_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return [
        MeetingAttendanceRowOut(
            user=CommitteeMemberUserOut.model_validate(r.user),
            first_joined_at=r.first_joined_at,
            last_left_at=r.last_left_at,
            total_seconds=r.total_seconds,
            sessions=r.sessions,
        )
        for r in rows
    ]
