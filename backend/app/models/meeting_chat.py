"""
الهدف:
نموذج SQLAlchemy ORM لـ"محادثة الاجتماع" داخل غرفة الاجتماع اللحظية —
راجعي رأس db/migrations/0026_meeting_realtime.sql للتصميم الكامل
(لماذا تُحفَظ الرسائل بخلاف أحداث رفع اليد العابرة، ولماذا WebSocket).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MeetingChatMessage(Base):
    __tablename__ = "meeting_chat_messages"

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.meeting_id"), nullable=False
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    sender: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821
