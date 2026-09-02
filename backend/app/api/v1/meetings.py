"""
الهدف:
راوتات REST لوحدة "إدارة الاجتماعات" (Phase 2 + مرفقات الاجتماع). بدون
أي تكامل فعلي مع Microsoft Teams/Graph API — راجعي رأس
app/services/meeting_service.py لتفصيل القرار الموثّق.

ملاحظة مهمة (لماذا لا تستخدم راوتات الإنشاء/التعديل/الحذف require_permission
على مستوى الراوت، بخلاف committees.py): التفويض هنا يعتمد على اللجنة
المحدَّدة بالطلب تحديدًا (Committee Role الخاص بعضوية actor في *تلك*
اللجنة بالذات) وليس فقط على دوره العام — فلا يمكن فحصه بمعزل عن تحميل
السجل نفسه أولًا. يُفرض بالكامل داخل meeting_service.

ملاحظة تقنية: دوال meeting_service (create/update/delete_meeting،
add/update/delete_agenda_item، add/delete_attachment) تُنفّذ commit/rollback
داخليًا بنفسها الآن (بخلاف نمط committees.py الذي يترك الـcommit للراوت) —
ضروري لأن add_attachment يستدعي document_service.create_document الذي
يُنهي معاملته (transaction) الخاصة به بالكامل قبل أن يعود، فلا يمكن تأجيل
الـcommit لهذا الجزء إلى الراوت. طُبِّق نفس النمط على بقية دوال الوحدة
هنا للاتساق، بدل خلط الأسلوبين داخل نفس الملف.
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage_client
from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.committee import CommitteeMemberUserOut
from app.schemas.meeting import (
    MeetingAgendaItemCreate,
    MeetingAgendaItemOut,
    MeetingAgendaItemUpdate,
    MeetingAttachmentKind,
    MeetingAttachmentOut,
    MeetingCreate,
    MeetingOut,
    MeetingUpdate,
)
from app.services import meeting_service
from app.services.document_service import DocumentValidationError
from app.services.meeting_service import (
    AgendaItemNotFoundError,
    AttachmentNotFoundError,
    MeetingForbiddenError,
    MeetingInvalidStateError,
    MeetingNotFoundError,
    MeetingValidationError,
)

router = APIRouter(prefix="/meetings", tags=["meetings"])

_SERVICE_ERRORS = (
    MeetingNotFoundError,
    AgendaItemNotFoundError,
    AttachmentNotFoundError,
    MeetingForbiddenError,
    MeetingInvalidStateError,
    MeetingValidationError,
    DocumentValidationError,
    storage_client.StorageError,
)


def _handle_errors(exc: Exception) -> Exception:
    """يترجم استثناءات طبقة الخدمة إلى استجابات HTTP مناسبة، مركزيًا."""
    if isinstance(exc, (MeetingNotFoundError, AgendaItemNotFoundError, AttachmentNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, MeetingForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, MeetingInvalidStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (MeetingValidationError, DocumentValidationError, ValueError)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, storage_client.StorageError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="تعذّر رفع الملف، حاول مرة أخرى"
        )
    raise exc


@router.post("", response_model=MeetingOut, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingOut:
    try:
        meeting = await meeting_service.create_meeting(
            db,
            actor=current_user,
            committee_id=payload.committee_id,
            title=payload.title,
            description=payload.description,
            mode=payload.mode,
            location=payload.location,
            scheduled_at=payload.scheduled_at,
            agenda_items=[item.model_dump() for item in payload.agenda_items],
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return MeetingOut.model_validate(meeting)


@router.get("", response_model=list[MeetingOut])
async def list_meetings(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[MeetingOut]:
    meetings = await meeting_service.list_meetings(db, actor=current_user)
    return [MeetingOut.model_validate(m) for m in meetings]


@router.get("/{meeting_id}", response_model=MeetingOut)
async def get_meeting(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingOut:
    try:
        meeting = await meeting_service.get_meeting(db, meeting_id, actor=current_user)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return MeetingOut.model_validate(meeting)


@router.patch("/{meeting_id}", response_model=MeetingOut)
async def update_meeting(
    meeting_id: uuid.UUID,
    payload: MeetingUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingOut:
    try:
        meeting = await meeting_service.update_meeting(
            db,
            actor=current_user,
            meeting_id=meeting_id,
            title=payload.title,
            description=payload.description,
            mode=payload.mode,
            location=payload.location,
            scheduled_at=payload.scheduled_at,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return MeetingOut.model_validate(meeting)


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    try:
        await meeting_service.delete_meeting(db, actor=current_user, meeting_id=meeting_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc


@router.post(
    "/{meeting_id}/agenda-items",
    response_model=MeetingAgendaItemOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_agenda_item(
    meeting_id: uuid.UUID,
    payload: MeetingAgendaItemCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingAgendaItemOut:
    try:
        item = await meeting_service.add_agenda_item(
            db,
            actor=current_user,
            meeting_id=meeting_id,
            title=payload.title,
            description=payload.description,
            sort_order=payload.sort_order,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return MeetingAgendaItemOut.model_validate(item)


@router.patch("/agenda-items/{agenda_item_id}", response_model=MeetingAgendaItemOut)
async def update_agenda_item(
    agenda_item_id: uuid.UUID,
    payload: MeetingAgendaItemUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingAgendaItemOut:
    try:
        item = await meeting_service.update_agenda_item(
            db,
            actor=current_user,
            agenda_item_id=agenda_item_id,
            title=payload.title,
            description=payload.description,
            sort_order=payload.sort_order,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return MeetingAgendaItemOut.model_validate(item)


@router.delete("/agenda-items/{agenda_item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agenda_item(
    agenda_item_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    try:
        await meeting_service.delete_agenda_item(
            db, actor=current_user, agenda_item_id=agenda_item_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc


def _attachment_out(document, kind: str, linked_at) -> MeetingAttachmentOut:
    return MeetingAttachmentOut(
        document_id=document.document_id,
        kind=kind,
        title=document.title,
        file_name=document.file_name,
        mime_type=document.mime_type,
        file_size_bytes=document.file_size_bytes,
        uploaded_by=CommitteeMemberUserOut.model_validate(document.uploader),
        linked_at=linked_at,
    )


@router.post(
    "/{meeting_id}/attachments",
    response_model=MeetingAttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_meeting_attachment(
    meeting_id: uuid.UUID,
    current_user: CurrentUser,
    kind: MeetingAttachmentKind = Form(...),
    file: UploadFile = File(...),
    title: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> MeetingAttachmentOut:
    """
    رفع مرفق (kind='attachment') أو عرض تقديمي (kind='presentation')
    وربطه بالاجتماع مباشرة — multipart/form-data بنفس نمط
    POST /documents (documents.py)، وليس JSON، لأن الملف الفعلي يمر عبر
    الـBackend إلى Supabase Storage.
    """
    content = await file.read()
    try:
        document, linked_at = await meeting_service.add_attachment(
            db,
            actor=current_user,
            meeting_id=meeting_id,
            kind=kind,
            title=title or file.filename or "بدون عنوان",
            file_name=file.filename or "unnamed",
            mime_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return _attachment_out(document, kind, linked_at)


@router.get("/{meeting_id}/attachments", response_model=list[MeetingAttachmentOut])
async def list_meeting_attachments(
    meeting_id: uuid.UUID,
    current_user: CurrentUser,
    kind: MeetingAttachmentKind | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[MeetingAttachmentOut]:
    try:
        rows = await meeting_service.list_attachments(
            db, actor=current_user, meeting_id=meeting_id, kind=kind
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return [_attachment_out(document, k, linked_at) for document, k, linked_at in rows]


@router.delete(
    "/{meeting_id}/attachments/{document_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_meeting_attachment(
    meeting_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await meeting_service.delete_attachment(
            db, actor=current_user, meeting_id=meeting_id, document_id=document_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
