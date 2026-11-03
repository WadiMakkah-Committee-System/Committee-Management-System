"""
الهدف:
نموذج ORM لجلسات حضور اجتماع Teams المدمج (migration 0043 — قرار لاما 2026-11-03).
كل صف = جلسة واحدة: من لحظة دخول العضو للاجتماع فعليًا (بعد القبول من قاعة
الانتظار) إلى خروجه. دخل وطلع أكثر من مرة ⇒ أكثر من صف.

last_seen_at: آخر نبضة من جهازه — لو انقطع بدون تسجيل خروج، تُعتبر الجلسة
منتهية عندها (راجعي meeting_service/attendance.py).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MeetingAttendance(Base):
    __tablename__ = "meeting_attendance"

    attendance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.meeting_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821
