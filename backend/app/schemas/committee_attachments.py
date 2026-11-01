"""
مخططات تصنيف "مرفقات اللجنة" بالوثائق — خفيفة عمدًا: كل مستوى يرجع حقول
شاشته فقط (راجعي رأس services/committee_attachments_service.py).
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.meeting import MeetingAttachmentOut


class CommitteeBriefOut(BaseModel):
    committee_id: uuid.UUID
    name: str
    end_date: date | None
    is_ended: bool


class MeetingBriefOut(BaseModel):
    meeting_id: uuid.UUID
    title: str
    scheduled_at: datetime


class BundleAttachmentOut(MeetingAttachmentOut):
    # عنوان البند لمرفقات البنود (kind='agenda') فقط.
    agenda_item_title: str | None = None


class MeetingBundleOut(BaseModel):
    meeting_id: uuid.UUID
    title: str
    # False = لا يملك عرض المرفقات (يملك المحضر فقط) — الواجهة تخفي القسم بدل "لا توجد مرفقات".
    can_view_attachments: bool
    attachments: list[BundleAttachmentOut]
    # المحضر: موجود ومرحلته فقط — الملف نفسه عبر GET /meetings/{id}/minutes/pdf عند الطلب.
    can_view_minutes: bool
    minutes_available: bool
    minutes_stage: str | None
