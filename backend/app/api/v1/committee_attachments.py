"""
الهدف:
نقاط تصنيف "مرفقات اللجنة" بصفحة الوثائق (طلب لاما 2026-11-01) — ثلاث نقاط
مستقلة، كل واحدة تُستدعى فقط لما المستخدم يفتح مستواها (تحميل كسول):

- GET /documents/committee-attachments/committees            → لجاني
- GET /documents/committee-attachments/committees/{id}/meetings → أسماء اجتماعات اللجنة
- GET /documents/committee-attachments/meetings/{id}          → مرفقات اجتماع + حالة محضره

التنزيل يستخدم النقاط القائمة: /meetings/{id}/attachments/{doc}/download
للمرفقات، و/meetings/{id}/minutes/pdf للمحضر.

الصلاحيات: بوابة عرض الوثائق (نفس صفحة الوثائق) + فحوص اللجنة بطبقة الخدمة
(راجعي services/committee_attachments_service.py).

مسجَّل قبل documents.router بـrouter.py حتى لا يلتقطه مسار /documents/{document_id}.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.documents import _require_documents_view_access
from app.api.v1.meetings._errors import _SERVICE_ERRORS, _handle_errors
from app.api.v1.meetings.attachments import _attachment_out
from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.committee_attachments import (
    BundleAttachmentOut,
    CommitteeBriefOut,
    MeetingBriefOut,
    MeetingBundleOut,
)
from app.services import committee_attachments_service

router = APIRouter(prefix="/documents/committee-attachments", tags=["documents"])


@router.get("/committees", response_model=list[CommitteeBriefOut])
async def list_attachment_committees(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[CommitteeBriefOut]:
    """المستوى الأول: لجان المستخدم (الجارية ثم المنتهية) — الاسم والحالة فقط."""
    await _require_documents_view_access(db, current_user)
    committees = await committee_attachments_service.list_committees_brief(db, actor=current_user)
    return [CommitteeBriefOut(**vars(c)) for c in committees]


@router.get("/committees/{committee_id}/meetings", response_model=list[MeetingBriefOut])
async def list_attachment_committee_meetings(
    committee_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[MeetingBriefOut]:
    """بعد اختيار "مرفقات الاجتماعات": أسماء اجتماعات اللجنة ومواعيدها فقط."""
    await _require_documents_view_access(db, current_user)
    try:
        meetings = await committee_attachments_service.list_committee_meetings_brief(
            db, actor=current_user, committee_id=committee_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return [MeetingBriefOut(**vars(m)) for m in meetings]


@router.get("/meetings/{meeting_id}", response_model=MeetingBundleOut)
async def get_attachment_meeting_bundle(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingBundleOut:
    """بعد اختيار اجتماع: مرفقاته (مع عنوان البند لمرفقات البنود) + حالة محضره."""
    await _require_documents_view_access(db, current_user)
    try:
        bundle = await committee_attachments_service.get_meeting_bundle(
            db, actor=current_user, meeting_id=meeting_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return MeetingBundleOut(
        meeting_id=bundle.meeting_id,
        title=bundle.title,
        can_view_attachments=bundle.can_view_attachments,
        attachments=[
            BundleAttachmentOut(
                **_attachment_out(a.document, a.kind, a.linked_at, a.agenda_item_id).model_dump(),
                agenda_item_title=a.agenda_item_title,
            )
            for a in bundle.attachments
        ],
        can_view_minutes=bundle.can_view_minutes,
        minutes_available=bundle.minutes_available,
        minutes_stage=bundle.minutes_stage,
    )
