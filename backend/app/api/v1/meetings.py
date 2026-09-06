"""
الهدف:
راوتات REST لوحدة "إدارة الاجتماعات" (Phase 2). بدون أي تكامل مع
Microsoft Teams/Graph API وبدون خدمات الذكاء الاصطناعي — راجعي رأس
db/migrations/0018_meetings_schema.sql وapp/services/meeting_service.py
لتفصيل القرار الموثّق.

ملاحظة مهمة (لماذا لا تستخدم راوتات الإنشاء/التعديل/الحذف require_permission
على مستوى الراوت، بخلاف committees.py): التفويض هنا يعتمد على اللجنة
المحدَّدة بالطلب تحديدًا (Committee Role الخاص بعضوية actor في *تلك*
اللجنة بالذات) وليس فقط على دوره العام — فلا يمكن فحصه بمعزل عن تحميل
السجل نفسه أولًا. يُفرض بالكامل داخل meeting_service (دالة _require_access
هناك)، بنفس منطق الوصول المزدوج (System Role scope أو Committee Role
permission) المطبَّق في committee_service.get_committee — راجعي docstring
meeting_service.py للتفصيل الكامل بعد تحديث 2026-09-01 ("أدوار اللجان").
"""

import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import agora_client, storage_client
from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.meeting import (
    MeetingAgendaItemCreate,
    MeetingAgendaItemOut,
    MeetingAgendaItemUpdate,
    MeetingAttachmentOut,
    MeetingCreate,
    MeetingJoinOut,
    MeetingOut,
    MeetingUpdate,
)
from app.services import meeting_service, notification_service
from app.services.meeting_service import (
    AgendaItemNotFoundError,
    MeetingAttachmentNotFoundError,
    MeetingAttachmentUpload,
    MeetingForbiddenError,
    MeetingInvalidStateError,
    MeetingNotFoundError,
)

router = APIRouter(prefix="/meetings", tags=["meetings"])


def _handle_errors(exc: Exception) -> Exception:
    """يترجم استثناءات طبقة الخدمة إلى استجابات HTTP مناسبة، مركزيًا (بنفس نمط committees.py)."""
    if isinstance(exc, (MeetingNotFoundError, AgendaItemNotFoundError, MeetingAttachmentNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, MeetingForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, MeetingInvalidStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


def _storage_error_to_http(exc: storage_client.StorageError) -> HTTPException:
    if isinstance(exc, storage_client.StorageNotConfiguredError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="خدمة تخزين الملفات غير مُهيّأة بعد (راجع إعدادات SUPABASE_* بالبيئة)",
        )
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


def _agora_error_to_http(exc: agora_client.AgoraError) -> HTTPException:
    if isinstance(exc, agora_client.AgoraNotConfiguredError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="خدمة الاجتماعات المرئية غير مُهيّأة بعد (راجع إعدادات AGORA_* بالبيئة)",
        )
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("", response_model=MeetingOut, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingCreate,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
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
            scheduled_end_at=payload.scheduled_end_at,
            agenda_items=[item.model_dump() for item in payload.agenda_items],
        )
        await db.commit()
    except (MeetingNotFoundError, MeetingForbiddenError, ValueError) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc
    await db.refresh(meeting)
    # إشعار بريدي لأعضاء اللجنة كـBackgroundTask (بعد commit الناجح) — لا
    # يُبطئ استجابة إنشاء الاجتماع، ولا يُفشلها لو تعذّر إرسال البريد
    # (راجعي core/email_client.py وservices/notification_service.py).
    background_tasks.add_task(notification_service.notify_meeting_created, meeting)
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
    except (MeetingNotFoundError, MeetingForbiddenError) as exc:
        raise _handle_errors(exc) from exc
    return MeetingOut.model_validate(meeting)


@router.patch("/{meeting_id}", response_model=MeetingOut)
async def update_meeting(
    meeting_id: uuid.UUID,
    payload: MeetingUpdate,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> MeetingOut:
    try:
        meeting, changes = await meeting_service.update_meeting(
            db,
            actor=current_user,
            meeting_id=meeting_id,
            title=payload.title,
            description=payload.description,
            mode=payload.mode,
            mode_set="mode" in payload.model_fields_set,
            location=payload.location,
            location_set="location" in payload.model_fields_set,
            scheduled_at=payload.scheduled_at,
            scheduled_end_at=payload.scheduled_end_at,
            participant_ids=payload.participant_ids,
        )
        await db.commit()
    except (
        MeetingNotFoundError,
        MeetingForbiddenError,
        MeetingInvalidStateError,
        ValueError,
    ) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc
    await db.refresh(meeting)
    # إشعار بريدي لأعضاء اللجنة فقط لو تغيّر أحد "الحقول المهمة" (راجعي
    # docstring meeting_service.update_meeting وnotification_service.py) —
    # قرار لاما 2026-09-06. notify_meeting_updated نفسها لا ترسل شيئًا لو
    # changes فارغة، فالفحص هنا للوضوح فقط (تفادي جدولة Task فارغة).
    if changes:
        background_tasks.add_task(notification_service.notify_meeting_updated, meeting, changes)
    return MeetingOut.model_validate(meeting)


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(
    meeting_id: uuid.UUID,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        meeting = await meeting_service.delete_meeting(db, actor=current_user, meeting_id=meeting_id)
        await db.commit()
    except (MeetingNotFoundError, MeetingForbiddenError, MeetingInvalidStateError) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc
    # إشعار إلغاء لأعضاء اللجنة — meeting هنا لسه محمَّل بالكامل بالذاكرة
    # (committee/participants كلاهما lazy="selectin")، رغم إن db.commit()
    # صار قبله مباشرة — expire_on_commit=False بـdb/session.py يضمن بقاء
    # القيم المحمَّلة أصلًا صالحة بلا استعلام إضافي (راجعي notification_service.py).
    background_tasks.add_task(notification_service.notify_meeting_cancelled, meeting)


# ============================== الانضمام لاجتماع عن بعد (Agora) ==============================


@router.post("/{meeting_id}/join", response_model=MeetingJoinOut)
async def join_meeting(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingJoinOut:
    try:
        _meeting, join_info = await meeting_service.join_meeting(
            db, actor=current_user, meeting_id=meeting_id
        )
        await db.commit()
    except (MeetingNotFoundError, MeetingForbiddenError, MeetingInvalidStateError) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc
    except agora_client.AgoraError as exc:
        await db.rollback()
        raise _agora_error_to_http(exc) from exc
    return MeetingJoinOut(
        app_id=join_info.app_id,
        channel=join_info.channel,
        token=join_info.token,
        uid=join_info.uid,
        expires_at=join_info.expires_at,
    )


@router.post("/{meeting_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_meeting(
    meeting_id: uuid.UUID,
    current_user: CurrentUser,
    agora_uid: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await meeting_service.leave_meeting(
            db, actor=current_user, meeting_id=meeting_id, agora_uid=agora_uid
        )
        await db.commit()
    except (MeetingNotFoundError, MeetingForbiddenError) as exc:
        await db.rollback()
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
        await db.commit()
    except (MeetingNotFoundError, MeetingForbiddenError) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc
    await db.refresh(item)
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
        await db.commit()
    except (AgendaItemNotFoundError, MeetingNotFoundError, MeetingForbiddenError) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc
    await db.refresh(item)
    return MeetingAgendaItemOut.model_validate(item)


@router.delete("/agenda-items/{agenda_item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agenda_item(
    agenda_item_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    try:
        await meeting_service.delete_agenda_item(
            db, actor=current_user, agenda_item_id=agenda_item_id
        )
        await db.commit()
    except (AgendaItemNotFoundError, MeetingNotFoundError, MeetingForbiddenError) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc


# ============================== مرفقات الاجتماع ==============================
# رفع الملف عبر multipart/form-data (UploadFile + Form) وليس JSON — بنفس
# نمط POST /documents (راجعي api/v1/documents.py). بدون
# dependencies=[Depends(require_permission(...))] هنا عمدًا — التفويض هنا
# مزدوج (System Role scope أو Committee Role) ومرتبط باللجنة المحدَّدة،
# فيُفرض بالكامل داخل meeting_service (نفس سبب بقية راوترات هذا الملف).


@router.post(
    "/{meeting_id}/attachments",
    response_model=MeetingAttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_meeting_attachment(
    meeting_id: uuid.UUID,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    link_role: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> MeetingAttachmentOut:
    if link_role not in ("presentation", "attachment"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="link_role يجب أن يكون presentation أو attachment",
        )
    content = await file.read()
    try:
        document, link = await meeting_service.add_meeting_attachment(
            db,
            actor=current_user,
            meeting_id=meeting_id,
            upload=MeetingAttachmentUpload(
                link_role=link_role,
                file_name=file.filename or "unnamed",
                mime_type=file.content_type or "application/octet-stream",
                content=content,
            ),
        )
    except (MeetingNotFoundError, MeetingForbiddenError, ValueError) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc
    except storage_client.StorageError as exc:
        await db.rollback()
        raise _storage_error_to_http(exc) from exc
    return MeetingAttachmentOut(
        document_id=document.document_id,
        link_role=link.link_role,
        file_name=document.file_name,
        mime_type=document.mime_type,
        file_size_bytes=document.file_size_bytes,
        uploaded_by=document.uploader,
        linked_at=link.linked_at,
    )


@router.get("/{meeting_id}/attachments", response_model=list[MeetingAttachmentOut])
async def list_meeting_attachments(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[MeetingAttachmentOut]:
    try:
        rows = await meeting_service.list_meeting_attachments(
            db, actor=current_user, meeting_id=meeting_id
        )
    except (MeetingNotFoundError, MeetingForbiddenError) as exc:
        raise _handle_errors(exc) from exc
    return [
        MeetingAttachmentOut(
            document_id=document.document_id,
            link_role=link.link_role,
            file_name=document.file_name,
            mime_type=document.mime_type,
            file_size_bytes=document.file_size_bytes,
            uploaded_by=document.uploader,
            linked_at=link.linked_at,
        )
        for document, link in rows
    ]


@router.get("/{meeting_id}/attachments/{document_id}/download")
async def download_meeting_attachment(
    meeting_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        document, content = await meeting_service.get_meeting_attachment_download(
            db, actor=current_user, meeting_id=meeting_id, document_id=document_id
        )
    except (MeetingNotFoundError, MeetingForbiddenError, MeetingAttachmentNotFoundError) as exc:
        raise _handle_errors(exc) from exc
    except storage_client.StorageError as exc:
        raise _storage_error_to_http(exc) from exc
    return Response(
        content=content,
        media_type=document.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{document.file_name}"'},
    )


@router.delete("/{meeting_id}/attachments/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting_attachment(
    meeting_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await meeting_service.delete_meeting_attachment(
            db, actor=current_user, meeting_id=meeting_id, document_id=document_id
        )
    except (MeetingNotFoundError, MeetingForbiddenError, MeetingAttachmentNotFoundError) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc
