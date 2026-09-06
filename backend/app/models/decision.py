"""
الهدف:
نموذج SQLAlchemy ORM لوحدة "إدارة القرارات" — القرارات المستقلة فقط
(تُصدَر مباشرة من واجهة القرارات) — يطابق بنية
db/migrations/0021_decisions_schema.sql. بدون القرارات المستخرجة من
اجتماع بالذكاء الاصطناعي (تُبنى لاحقًا مع تكامل AI/Teams).

راجعي رأس ملف الـmigration نفسه لكل الاجتهادات الموثّقة (التعديل/الحذف
يُمنعان من فتح التصويت، موعد التصويت الاختياري، بدون تذكيرات، المنفذون
من أعضاء اللجنة فقط، بدون ربط وثائق بهذه المرحلة).
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, String, Table, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DecisionClassification(str, enum.Enum):
    final = "final"
    voting = "voting"


class DecisionStatus(str, enum.Enum):
    pending = "pending"
    voting = "voting"
    approved = "approved"
    rejected = "rejected"


class DecisionVoteChoice(str, enum.Enum):
    approve = "approve"
    reject = "reject"


# المنفذون — من أعضاء اللجنة فقط (بمن فيهم رئيسها).
decision_assignees = Table(
    "decision_assignees",
    Base.metadata,
    Column(
        "decision_id",
        UUID(as_uuid=True),
        ForeignKey("decisions.decision_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.user_id"), primary_key=True),
    Column("added_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


class DecisionVote(Base):
    __tablename__ = "decision_votes"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.decision_id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), primary_key=True
    )
    choice: Mapped[DecisionVoteChoice] = mapped_column(
        SAEnum(DecisionVoteChoice, name="decision_vote_choice", native_enum=True), nullable=False
    )
    voted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    voter: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821


class Decision(Base):
    __tablename__ = "decisions"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    committee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("committees.committee_id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    classification: Mapped[DecisionClassification] = mapped_column(
        SAEnum(DecisionClassification, name="decision_classification", native_enum=True),
        nullable=False,
    )
    status: Mapped[DecisionStatus] = mapped_column(
        SAEnum(DecisionStatus, name="decision_status", native_enum=True),
        nullable=False,
        server_default=DecisionStatus.pending.value,
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    voting_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voting_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voting_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    committee: Mapped["Committee"] = relationship(lazy="selectin")  # noqa: F821
    creator: Mapped["User"] = relationship(foreign_keys=[created_by], lazy="selectin")  # noqa: F821
    assignees: Mapped[list["User"]] = relationship(  # noqa: F821
        secondary=decision_assignees, lazy="selectin"
    )
    votes: Mapped[list["DecisionVote"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
