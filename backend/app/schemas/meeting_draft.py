"""
الهدف:
Pydantic Schemas لميزة "التسجيل الصوتي + المسودة بالذكاء الاصطناعي"
(meetings.record_audio/draft.summarize/draft.view) — راجعي رأس
db/migrations/0025_meeting_recordings_and_drafts.sql وapp/models/meeting_draft.py
للتصميم الكامل. مفروزة بملف مستقل عن schemas/meeting.py (بنفس نمط فصل
decision.py/task.py) لأنها ميزة فرعية مستقلة وليست جزءًا من CRUD
الاجتماع الأساسي.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.committee import CommitteeMemberUserOut


class MeetingRecordingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recording_id: uuid.UUID
    file_name: str
    mime_type: str
    file_size_bytes: int
    duration_seconds: int | None
    recorded_by: CommitteeMemberUserOut
    recorded_at: datetime


class TranscriptSegment(BaseModel):
    speaker: str
    start_time: str
    text: str


class DecisionDraftItem(BaseModel):
    text: str
    proposed_by: str | None = None
    approved: bool | None = None


class ActionItemDraftItem(BaseModel):
    text: str
    assignee: str | None = None
    due_date: str | None = None


class RecommendationDraftItem(BaseModel):
    text: str
    proposed_by: str | None = None


class OpenItemDraftItem(BaseModel):
    text: str
    raised_by: str | None = None


class ComplianceNoteDraftItem(BaseModel):
    text: str
    severity: str | None = None


MeetingDraftStatusOut = Literal["pending", "processing", "completed", "failed"]


class MeetingDraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    draft_id: uuid.UUID
    meeting_id: uuid.UUID
    status: MeetingDraftStatusOut
    error_message: str | None

    full_transcript: list[TranscriptSegment] | None
    summary: str | None
    decisions: list[DecisionDraftItem] | None
    action_items: list[ActionItemDraftItem] | None
    key_points: list[str] | None
    recommendations: list[RecommendationDraftItem] | None
    open_items: list[OpenItemDraftItem] | None
    compliance_notes: list[ComplianceNoteDraftItem] | None

    generated_by: CommitteeMemberUserOut
    generated_at: datetime | None
    created_at: datetime
    updated_at: datetime
