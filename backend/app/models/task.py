"""
الهدف:
نموذج SQLAlchemy ORM لوحدة "إدارة المهام" — الإنشاء المباشر من واجهة
المهام فقط. يطابق بنية db/migrations/0024_tasks_schema.sql.

راجعي رأس ملف الـmigration نفسه لكل الاجتهادات الموثّقة (مسؤول واحد فقط
لكل مهمة، جدول task_assignment_history لتتبع إعادة التعيين "مسار
المهمة"، قفل التعديل/الحذف بحالة completed يُفرض بالـservice، بدون
AI-extraction أو ربط وثائق بهذه المرحلة).
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TaskStatus(str, enum.Enum):
    todo = "todo"
    in_progress = "in_progress"
    on_hold = "on_hold"
    completed = "completed"


class TaskPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Task(Base):
    __tablename__ = "tasks"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    committee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("committees.committee_id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="task_status", native_enum=True),
        nullable=False,
        server_default=TaskStatus.todo.value,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        SAEnum(TaskPriority, name="task_priority", native_enum=True),
        nullable=False,
        server_default=TaskPriority.medium.value,
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    # تذكير قبل الاستحقاق + تنبيه تأخر فوري لرئيس اللجنة (migration 0031)
    reminder_offset_days: Mapped[int] = mapped_column(nullable=False, server_default="1")
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    assignee_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
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
    assignee: Mapped["User"] = relationship(foreign_keys=[assignee_user_id], lazy="selectin")  # noqa: F821
    creator: Mapped["User"] = relationship(foreign_keys=[created_by], lazy="selectin")  # noqa: F821
    assignment_history: Mapped[list["TaskAssignmentHistory"]] = relationship(
        back_populates="task",
        order_by="TaskAssignmentHistory.changed_at",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class TaskAssignmentHistory(Base):
    """مسار المهمة (Task Trail) — صف واحد لكل إعادة تعيين فعلية للمسؤول."""

    __tablename__ = "task_assignment_history"

    history_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False
    )
    from_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True
    )
    to_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    changed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    task: Mapped["Task"] = relationship(back_populates="assignment_history")
    from_user: Mapped["User | None"] = relationship(foreign_keys=[from_user_id], lazy="selectin")  # noqa: F821
    to_user: Mapped["User"] = relationship(foreign_keys=[to_user_id], lazy="selectin")  # noqa: F821
    changer: Mapped["User"] = relationship(foreign_keys=[changed_by], lazy="selectin")  # noqa: F821
