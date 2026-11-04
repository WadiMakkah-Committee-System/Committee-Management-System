"""
الهدف (migration 0045 — الرجوع لـAgora، قرار لاما 2026-11-04):
نموذج ORM لجلسة تسجيل صوتي تُرفع على دفعات أثناء الاجتماع.
القطع نفسها ملفات بالتخزين؛ هذا السجل يتابع حالتها لين تُدمج بملف واحد
(meeting_recordings) — راجعي app/services/meeting_service/recording_sessions.py.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

RECORDING_SESSION_ACTIVE = "recording"
RECORDING_SESSION_FINALIZED = "finalized"
RECORDING_SESSION_FAILED = "failed"


class MeetingRecordingSession(Base):
    __tablename__ = "meeting_recording_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.meeting_id", ondelete="CASCADE"), nullable=False
    )
    started_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # recording / finalized / failed (قيد CHECK بالقاعدة).
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=RECORDING_SESSION_ACTIVE)
    # رقم آخر قطعة وصلت (تبدأ من 0) — -1 = ما وصل شي بعد.
    last_seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default="-1")
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_chunk_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recording_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_recordings.recording_id", ondelete="SET NULL"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    starter: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821
