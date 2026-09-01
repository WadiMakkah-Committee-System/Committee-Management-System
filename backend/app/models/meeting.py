"""
الهدف:
نموذج SQLAlchemy ORM لوحدة "إدارة الاجتماعات" — يطابق بنية
db/migrations/0018_meetings_schema.sql. Phase 1 (Database Schema +
Models فقط)، بدون أي منطق عمل أو API — راجعي app/services/meeting_service.py
لذلك (Phase 2).

المسؤولية:
تمثيل الاجتماع (Meeting)، مشاركيه (meeting_participants)، وبنود جدول
أعماله (MeetingAgendaItem).

ملاحظات تصميم مهمة:
- لا يوجد هنا أي نموذج "مرفق اجتماع" — المرفقات تُربط عبر document_links
  الموجود أصلًا (linked_entity_type='meeting') وليس بجدول/نموذج مكرَّر.
  راجعي ملاحظة التصميم (1) بأعلى ملف الـmigration نفسه.
- committee: علاقة lazy="selectin" بنفس نمط User.role/Committee.chair —
  تضمن توفر committee.chair_user_id وcommittee.members دون استعلام إضافي
  صريح بكل خدمة تحتاج التحقق من رئاسة/عضوية اللجنة (meeting_service.py
  سيحتاج هذا في كل عملية تقريبًا: من يقدر ينشئ/يعدّل/يحذف/يشاهد).
- created_by للتتبع فقط، وليس مصدر تفويض — راجعي ملاحظة (2) بالـmigration.
- teams_meeting_id/teams_join_url موجودان بالنموذج (nullable) لمطابقة
  الجدول فقط — لا أي منطق يقرأهما أو يكتب فيهما في هذا الـPhase.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
import enum


class MeetingStatus(str, enum.Enum):
    upcoming = "upcoming"
    ongoing = "ongoing"
    finished = "finished"
    recorded = "recorded"


# مشاركو الاجتماع — جدول وسيط بسيط (meeting_id, user_id)، بنفس نمط
# committee_members/committee_formation_request_members.
meeting_participants = Table(
    "meeting_participants",
    Base.metadata,
    Column(
        "meeting_id",
        UUID(as_uuid=True),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.user_id"), primary_key=True),
    Column("added_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


class Meeting(Base):
    __tablename__ = "meetings"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    committee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("committees.committee_id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    meeting_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[MeetingStatus] = mapped_column(
        SAEnum(MeetingStatus, name="meeting_status", native_enum=True),
        nullable=False,
        server_default=MeetingStatus.upcoming.value,
    )

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )

    # محجوزان لمرحلة تكامل Microsoft Teams القادمة — غير مستخدَمين بعد.
    teams_meeting_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    teams_join_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    committee: Mapped["Committee"] = relationship(lazy="selectin")  # noqa: F821
    creator: Mapped["User"] = relationship(foreign_keys=[created_by], lazy="selectin")  # noqa: F821
    participants: Mapped[list["User"]] = relationship(  # noqa: F821
        secondary=meeting_participants, lazy="selectin"
    )
    agenda_items: Mapped[list["MeetingAgendaItem"]] = relationship(
        back_populates="meeting",
        order_by="MeetingAgendaItem.sort_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class MeetingAgendaItem(Base):
    __tablename__ = "meeting_agenda_items"

    agenda_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.meeting_id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    meeting: Mapped["Meeting"] = relationship(back_populates="agenda_items")
