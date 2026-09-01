"""
الهدف:
Pydantic Schemas الخاصة بوحدة "إدارة الاجتماعات" (Phase 2 — Backend APIs).
تحدّد شكل بيانات الاجتماعات وجدول الأعمال والردود لواجهات FR-MEET-001 →
FR-MEET-005 (SRS §3.1.1/3.1.2) + إدارة جدول الأعمال (§3.1.3)، وتفصل شكل
الـAPI عن نموذج قاعدة البيانات (ORM) في app/models/meeting.py.

بدون Teams/AI في هذا الـPhase — لا حقول teams_join_url/summary هنا.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.meeting import MeetingStatus
from app.schemas.committee import CommitteeMemberUserOut


class MeetingAgendaItemCreate(BaseModel):
    """بند جدول أعمال — يُرسَل ضمن قائمة عند إنشاء/تعديل الاجتماع، أو منفردًا لاحقًا."""

    title: str = Field(min_length=2, max_length=255)
    description: str | None = None
    sort_order: int = 0


class MeetingAgendaItemUpdate(BaseModel):
    """تعديل جزئي لبند موجود — كل الحقول اختيارية."""

    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = None
    sort_order: int | None = None


class MeetingAgendaItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agenda_item_id: uuid.UUID
    meeting_id: uuid.UUID
    title: str
    description: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime


class MeetingCreate(BaseModel):
    """
    بيانات إنشاء اجتماع جديد (FR-MEET-001) — حصريًا لرئيس اللجنة المرتبط
    بـcommittee_id (يُتحقَّق منه بطبقة الخدمة عبر committee.chair_user_id،
    وليس هنا). بنود الأجندة اختيارية عند الإنشاء — يمكن إضافتها لاحقًا
    عبر /agenda-items (FR-MEET §3.1.3).
    """

    committee_id: uuid.UUID
    title: str = Field(min_length=2, max_length=255)
    description: str | None = None
    meeting_type: str | None = Field(default=None, max_length=100)
    scheduled_at: datetime
    participant_ids: list[uuid.UUID] = Field(min_length=1)
    agenda_items: list[MeetingAgendaItemCreate] = Field(default_factory=list)


class MeetingUpdate(BaseModel):
    """
    تعديل بيانات اجتماع قائم (FR-MEET-003) — قبل انعقاده فقط (يُفرض بطبقة
    الخدمة عبر status == upcoming، وليس هنا). كل الحقول اختيارية.
    """

    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = None
    meeting_type: str | None = Field(default=None, max_length=100)
    scheduled_at: datetime | None = None
    participant_ids: list[uuid.UUID] | None = None


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    meeting_id: uuid.UUID
    committee_id: uuid.UUID
    title: str
    description: str | None
    meeting_type: str | None
    scheduled_at: datetime
    status: MeetingStatus
    creator: CommitteeMemberUserOut
    participants: list[CommitteeMemberUserOut]
    agenda_items: list[MeetingAgendaItemOut]
    created_at: datetime
    updated_at: datetime
