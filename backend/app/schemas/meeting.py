"""
الهدف:
Pydantic Schemas الخاصة بوحدة "إدارة الاجتماعات" (Phase 2 — Backend APIs).
تحدّد شكل بيانات الاجتماعات وجدول الأعمال والمرفقات والردود لواجهات
FR-MEET-001 → FR-MEET-005 (SRS §3.1.1/3.1.2) + إدارة جدول الأعمال
(§3.1.3)، وتفصل شكل الـAPI عن نموذج قاعدة البيانات (ORM) في
app/models/meeting.py.

بدون تكامل Teams/AI فعلي في هذا الـPhase — لا حقول teams_join_url/summary
هنا، رغم أن mode='remote' يمهّد لتلك المرحلة (راجعي app/models/meeting.py).

تحديث 2026-09-01 (قرارات صاحبة المشروع):
- meeting_type (نص حر) → mode (عن بعد/حضوري) + location (إلزامي لو حضوري).
- participant_ids حُذف من MeetingCreate/MeetingUpdate بالكامل — المشاركون
  الآن كل أعضاء اللجنة تلقائيًا (يُشتقّون بطبقة الخدمة)، بدون أي اختيار
  يدوي (راجعي meeting_service.create_meeting).
- مرفقات الاجتماع (عرض تقديمي + مرفقات عامة) — عبر document_links
  الموجود أصلًا، وليس حقلًا هنا (تُرفع كـmultipart/form-data منفصلة بعد
  إنشاء الاجتماع، راجعي app/api/v1/meetings.py::upload_meeting_attachment).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.meeting import MeetingMode, MeetingStatus
from app.schemas.committee import CommitteeMemberUserOut

# نوعا مرفقات الاجتماع — يقابلان بالضبط قيمتَي linked_entity_type
# المستخدمتين بجدول document_links (راجعي meeting_service.py):
# 'meeting_presentation' و'meeting_attachment'.
MeetingAttachmentKind = Literal["presentation", "attachment"]


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
    بـcommittee_id (يُتحقَّق منه بطبقة الخدمة، وليس هنا). بنود الأجندة
    اختيارية عند الإنشاء — يمكن إضافتها لاحقًا عبر /agenda-items
    (FR-MEET §3.1.3). لا يوجد حقل مشاركين — يُشتقّون تلقائيًا من عضوية
    اللجنة (راجعي docstring أعلى الملف).
    """

    committee_id: uuid.UUID
    title: str = Field(min_length=2, max_length=255)
    description: str | None = None
    mode: MeetingMode
    location: str | None = Field(default=None, max_length=255)
    scheduled_at: datetime
    agenda_items: list[MeetingAgendaItemCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _location_required_when_in_person(self) -> "MeetingCreate":
        if self.mode == MeetingMode.in_person and not (self.location or "").strip():
            raise ValueError("مكان الاجتماع إلزامي عند اختيار اجتماع حضوري")
        if self.mode == MeetingMode.remote:
            self.location = None
        return self


class MeetingUpdate(BaseModel):
    """
    تعديل بيانات اجتماع قائم (FR-MEET-003) — قبل انعقاده فقط (يُفرض بطبقة
    الخدمة عبر status == upcoming، وليس هنا). كل الحقول اختيارية.
    """

    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = None
    mode: MeetingMode | None = None
    location: str | None = Field(default=None, max_length=255)
    scheduled_at: datetime | None = None

    @model_validator(mode="after")
    def _location_required_when_in_person(self) -> "MeetingUpdate":
        if self.mode == MeetingMode.in_person and not (self.location or "").strip():
            raise ValueError("مكان الاجتماع إلزامي عند اختيار اجتماع حضوري")
        return self


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    meeting_id: uuid.UUID
    committee_id: uuid.UUID
    title: str
    description: str | None
    mode: MeetingMode
    location: str | None
    scheduled_at: datetime
    status: MeetingStatus
    creator: CommitteeMemberUserOut
    participants: list[CommitteeMemberUserOut]
    agenda_items: list[MeetingAgendaItemOut]
    created_at: datetime
    updated_at: datetime


class MeetingAttachmentOut(BaseModel):
    """
    ملف مرتبط باجتماع (عرض تقديمي أو مرفق عام) — تجميعة من Document +
    document_links (راجعي meeting_service.list_attachments). document_id
    هو نفسه معرّف الوثيقة بوحدة "إدارة الوثائق" (documents.py) — يمكن
    استخدامه مباشرة مع GET /documents/{document_id}/download.
    """

    document_id: uuid.UUID
    kind: MeetingAttachmentKind
    title: str
    file_name: str
    mime_type: str
    file_size_bytes: int
    uploaded_by: CommitteeMemberUserOut
    linked_at: datetime
