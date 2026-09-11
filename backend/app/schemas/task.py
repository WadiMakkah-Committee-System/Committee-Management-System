"""
الهدف:
Pydantic Schemas الخاصة بوحدة "إدارة المهام". راجعي رأس
db/migrations/0024_tasks_schema.sql للاجتهادات الموثّقة.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.task import TaskPriority, TaskStatus
from app.schemas.committee import CommitteeMemberUserOut


class TaskCreate(BaseModel):
    """إنشاء مهمة جديدة — مسؤول واحد فقط (قرار صاحبة المشروع 2026-09-06)."""

    committee_id: uuid.UUID
    title: str = Field(min_length=2, max_length=255)
    start_date: date
    end_date: date
    assignee_user_id: uuid.UUID
    priority: TaskPriority = TaskPriority.medium
    # عدد الأيام قبل end_date لإرسال تذكير للمسؤول عن المهمة (افتراضي يوم واحد،
    # اختياري لرئيس اللجنة يغيّره — طلب صاحبة المشروع 2026-09-11)
    reminder_offset_days: int = Field(default=1, ge=0, le=30)

    @model_validator(mode="after")
    def _end_after_start(self) -> "TaskCreate":
        if self.end_date < self.start_date:
            raise ValueError("تاريخ نهاية المهمة يجب أن يكون بعد تاريخ البداية أو يساويه")
        return self


class TaskUpdate(BaseModel):
    """تعديل بيانات مهمة — ممنوع إذا كانت الحالة completed (يُفرض بالـservice)."""

    title: str | None = Field(default=None, min_length=2, max_length=255)
    start_date: date | None = None
    end_date: date | None = None
    priority: TaskPriority | None = None
    reminder_offset_days: int | None = Field(default=None, ge=0, le=30)


class TaskStatusUpdate(BaseModel):
    """تحديث حالة المهمة — متاح للمسؤول الحالي عنها، أو رئيس اللجنة."""

    status: TaskStatus


class TaskReassign(BaseModel):
    """إعادة إسناد المهمة لمسؤول آخر — يسجَّل تلقائيًا بمسار المهمة (Task Trail)."""

    assignee_user_id: uuid.UUID


class TaskAssignmentHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    history_id: uuid.UUID
    from_user: CommitteeMemberUserOut | None
    to_user: CommitteeMemberUserOut
    changer: CommitteeMemberUserOut
    changed_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: uuid.UUID
    committee_id: uuid.UUID
    title: str
    status: TaskStatus
    priority: TaskPriority
    start_date: date
    end_date: date
    reminder_offset_days: int
    assignee: CommitteeMemberUserOut
    creator: CommitteeMemberUserOut
    assignment_history: list[TaskAssignmentHistoryOut]
    created_at: datetime
    updated_at: datetime


class TaskActivityEntry(BaseModel):
    """
    سطر واحد بمسار المهمة الموحَّد (طلب صاحبة المشروع 2026-09-11، بعد
    بحث في الأنظمة العالمية — Jira/ClickUp يدمجان كل التغييرات بخط زمني
    واحد، بخلاف اقتصار مسار المهمة سابقًا على إعادة الإسناد فقط). يُبنى
    بدمج task_assignment_history + audit_logs (target_type="task") معًا
    — راجعي task_service.get_task_activity. label جاهز للعرض مباشرة
    (يُبنى بالباك-إند، بنفس نمط نصوص notification_service.py).
    """

    entry_type: str  # "reassigned" | "status_changed" | "priority_changed" | "details_updated"
    label: str
    actor: CommitteeMemberUserOut | None
    occurred_at: datetime
