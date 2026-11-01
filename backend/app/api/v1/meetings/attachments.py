"""مرفقات الاجتماع (رفع/عرض/تحميل/حذف)."""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.committee import CommitteeMemberUserOut
from app.schemas.meeting import (
    MeetingAttachmentKind,
    MeetingAttachmentOut,
)
from app.core.background import run_detached
from app.services import meeting_service, notification_service

from app.api.v1.meetings._errors import _SERVICE_ERRORS, _handle_errors

router = APIRouter(prefix="/meetings", tags=["meetings"])


def _attachment_out(document, kind: str, linked_at, agenda_item_id=None) -> MeetingAttachmentOut:
    return MeetingAttachmentOut(
        document_id=document.document_id,
        kind=kind,
        agenda_item_id=agenda_item_id,
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
    return [_attachment_out(document, k, linked_at, item_id) for document, k, linked_at, item_id in rows]


@router.get("/{meeting_id}/attachments/{document_id}/download")
async def download_meeting_attachment(
    meeting_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    تنزيل محتوى المرفق مباشرة — مسار مخصص بوحدة الاجتماعات (وليس عبر
    GET /documents/{document_id}/download العام) لأن ذلك المسار محمي
    بصلاحية Role نظامية ثابتة (documents.download) لا يملكها عضو اللجنة
    العادي غالبًا، بينما هنا يكفي أن يملك meetings.attachments.view على
    نفس اللجنة (راجعي meeting_service.get_attachment_download).
    """
    try:
        document, content = await meeting_service.get_attachment_download(
            db, actor=current_user, meeting_id=meeting_id, document_id=document_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return Response(
        content=content,
        media_type=document.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{document.file_name}"'},
    )


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


@router.post(
    "/{meeting_id}/agenda-items/{agenda_item_id}/attachments",
    response_model=list[MeetingAttachmentOut],
    status_code=status.HTTP_201_CREATED,
)
async def upload_agenda_item_attachments(
    meeting_id: uuid.UUID,
    agenda_item_id: uuid.UUID,
    current_user: CurrentUser,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
) -> list[MeetingAttachmentOut]:
    """
    POST /meetings/{meeting_id}/agenda-items/{agenda_item_id}/attachments
    (multipart: files متعددة) — طلب لاما 2026-11-01: مرفقات لكل بند.

    الصلاحية: meetings.attachments.add على لجنة الاجتماع (نفس مرفقات الاجتماع).
    201: المرفقات المضافة (kind='agenda'). 404: البند ليس ضمن هذا الاجتماع.
    400: ملف فارغ/أكبر من الحد. 403: بلا صلاحية.
    التأثير الجانبي: بعد الحفظ، بريد واحد لمشاركي الاجتماع بالملفات (حتى 10
    ميجا إجمالًا، والباقي باسمه + رابط) + إشعار داخل النظام (run_detached).
    """
    contents = [(f.filename or "ملف", f.content_type or "application/octet-stream", await f.read()) for f in files]
    try:
        item, created = await meeting_service.add_agenda_item_attachments(
            db, actor=current_user, meeting_id=meeting_id, agenda_item_id=agenda_item_id, files=contents
        )
        meeting = await meeting_service.get_meeting(db, actor=current_user, meeting_id=meeting_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc

    run_detached(
        notification_service.notify_agenda_item_attachments_added(
            meeting,
            item.title,
            [
                notification_service.MeetingEmailFile(
                    filename=name, content=content, mime_type=mime, agenda_item_id=agenda_item_id
                )
                for name, mime, content in contents
            ],
            actor_user_id=current_user.user_id,
        )
    )
    return [_attachment_out(document, "agenda", linked_at, agenda_item_id) for document, linked_at in created]
