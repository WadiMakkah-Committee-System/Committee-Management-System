"""
الهدف:
نماذج ORM للدفعة 3 من تحسينات الاجتماع (migration 0044 — قرار لاما 2026-11-03):
- MeetingTranscriptSegment: جملة مكتملة من الترجمة النصية الحية.
- MeetingAgendaSession: فترة مناقشة بند (بداية/نهاية/مدة المؤقت المختارة).
تُستخدم لـ"وش فاتني؟" وإحصائيات الاجتماع.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MeetingTranscriptSegment(Base):
    __tablename__ = "meeting_transcript_segments"

    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.meeting_id", ondelete="CASCADE"), nullable=False
    )
    # مفتاح من جهاز الرئيس (وقت الجملة + المتحدث) — يمنع تكرار نفس الجملة.
    client_key: Mapped[str] = mapped_column(String(200), nullable=False)
    speaker_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    speaker_name: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    spoken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    agenda_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_agenda_items.agenda_item_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MeetingAgendaSession(Base):
    __tablename__ = "meeting_agenda_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.meeting_id", ondelete="CASCADE"), nullable=False
    )
    agenda_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_agenda_items.agenda_item_id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
