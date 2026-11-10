"""
طلبات دخول الضيوف للاجتماع (migration 0047 — قرار لاما 2026-11-10).

الضيف يفتح رابط الضيوف ← يكتب اسمه ← ينشأ طلب "منتظر" ← أي شخص داخل
الاجتماع يقبله أو يرفضه. عند القبول ينشأ حساب ضيف مؤقت (users.is_guest)
ويُربط بالطلب (user_id). الضيف يتابع طلبه برمز سري يُحفظ هنا مُجزّأً فقط.
راجعي services/meeting_guest_service.py لقواعد العمل كاملة.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MeetingGuestRequestStatus(str, enum.Enum):
    pending = "pending"
    admitted = "admitted"
    rejected = "rejected"
    cancelled = "cancelled"


class MeetingGuestRequest(Base):
    __tablename__ = "meeting_guest_requests"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.meeting_id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    request_secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[MeetingGuestRequestStatus] = mapped_column(
        SAEnum(MeetingGuestRequestStatus, name="meeting_guest_request_status", native_enum=True),
        nullable=False,
        server_default=MeetingGuestRequestStatus.pending.value,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
