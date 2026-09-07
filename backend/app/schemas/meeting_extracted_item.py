"""
الهدف:
Pydantic Schemas لـ"البنود المستخرجة من الاجتماع" — راجعي رأس
app/models/meeting_extracted_item.py وdb/migrations/0028 للتصميم الكامل.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.decision import DecisionClassification
from app.schemas.committee import CommitteeMemberUserOut

MeetingExtractedItemSourceOut = Literal["ai", "manual"]
MeetingExtractedItemStatusOut = Literal["pending", "assigned_task", "assigned_decision"]


class MeetingExtractedItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: uuid.UUID
    meeting_id: uuid.UUID
    text: str
    source: MeetingExtractedItemSourceOut
    status: MeetingExtractedItemStatusOut
    linked_task_id: uuid.UUID | None
    linked_decision_id: uuid.UUID | None
    created_by: CommitteeMemberUserOut
    created_at: datetime
    updated_at: datetime


class ExtractedItemManualCreate(BaseModel):
    """إضافة بند يدوي لقائمة البنود المستخرجة (FR-TASK-007/UC4)."""

    text: str = Field(min_length=2, max_length=500)


class ExtractedItemAssignAsTask(BaseModel):
    """تعيين بند كمهمة (FR-TASK-010/011 + UC7/UC8) — نفس حقول إنشاء مهمة
    عادية (راجعي schemas/task.py: TaskCreate) بدون committee_id (يُشتق من
    اجتماع البند). title اختياري: افتراضيًا نص البند نفسه، قابل للتعديل
    من رئيس اللجنة قبل الحفظ."""

    title: str | None = Field(default=None, min_length=2, max_length=255)
    start_date: date
    end_date: date
    assignee_user_id: uuid.UUID


class ExtractedItemAssignAsDecision(BaseModel):
    """تعيين بند كقرار (FR-DEC-004 + UC7) — نفس حقول إنشاء قرار عادي
    (راجعي schemas/decision.py: DecisionCreate) بدون committee_id/meeting_id
    (يُشتقان من اجتماع البند تلقائيًا). title اختياري كما بالمهمة."""

    title: str | None = Field(default=None, min_length=2, max_length=255)
    classification: DecisionClassification
    start_date: date
    end_date: date
