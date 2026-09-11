"""
الهدف:
نماذج SQLAlchemy ORM لوحدة "المحاضر" (SRS §7) — راجعي رأس
db/migrations/0029_meeting_minutes.sql للتصميم الكامل والقرارات
الموثّقة (آلة الحالة، القوالب الثابتة، لماذا reviewers/signatures
جدولان حقيقيان بخلاف sections الحرة).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MeetingMinutesStage(str, enum.Enum):
    none = "none"
    preparing = "preparing"
    review = "review"
    approval = "approval"
    signature = "signature"
    completed = "completed"


class MeetingMinutesReviewStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    returned = "returned"


class MeetingMinutes(Base):
    __tablename__ = "meeting_minutes"

    minutes_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # 'executive' | 'formal' | 'detailed' — راجعي MINUTES_TEMPLATES بـ
    # app/services/meeting_minutes_service.py للتعريف الثابت الكامل.
    template_id: Mapped[str | None] = mapped_column(String(20), nullable=True)

    stage: Mapped[MeetingMinutesStage] = mapped_column(
        SAEnum(MeetingMinutesStage, name="meeting_minutes_stage", native_enum=True),
        nullable=False,
        server_default=MeetingMinutesStage.none.value,
    )

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )

    # [{id, title, body, order}] — تُنسخ من القالب لحظة اختياره، ثم حرة
    # التعديل/الإضافة/الحذف بدون أي أثر على تعريف القالب (طلب لمى الصريح).
    sections: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, server_default="[]")

    sent_to_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_for_signature_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    owner: Mapped["User | None"] = relationship(lazy="selectin")  # noqa: F821
    reviewers: Mapped[list["MeetingMinutesReviewer"]] = relationship(
        back_populates="minutes",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="MeetingMinutesReviewer.created_at",
    )
    signatures: Mapped[list["MeetingMinutesSignature"]] = relationship(
        back_populates="minutes",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="MeetingMinutesSignature.created_at",
    )


class MeetingMinutesReviewer(Base):
    __tablename__ = "meeting_minutes_reviewers"
    __table_args__ = (UniqueConstraint("minutes_id", "user_id"),)

    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    minutes_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_minutes.minutes_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[MeetingMinutesReviewStatus] = mapped_column(
        SAEnum(MeetingMinutesReviewStatus, name="meeting_minutes_review_status", native_enum=True),
        nullable=False,
        server_default=MeetingMinutesReviewStatus.pending.value,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    minutes: Mapped["MeetingMinutes"] = relationship(back_populates="reviewers")
    user: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821


class MeetingMinutesSignature(Base):
    __tablename__ = "meeting_minutes_signatures"
    __table_args__ = (UniqueConstraint("minutes_id", "user_id"),)

    signature_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    minutes_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_minutes.minutes_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    # صورة Base64 (PNG) من مكتبة توقيع بالفرونت-إند (react-signature-canvas)
    # — توقيع فعلي مرسوم، وليس مجرد علم "تم" (قرار لمى الصريح).
    signature_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    minutes: Mapped["MeetingMinutes"] = relationship(back_populates="signatures")
    user: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821
