"""
الهدف:
راوتات REST لوحدة "إدارة المهام". راجعي رأس app/services/task_service.py
للتفويض والاجتهادات الموثّقة.
"""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.documents import _content_disposition
from app.core.background import run_detached
from app.core.committee_period import CommitteePeriodError
from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.committee import CommitteeMemberUserOut
from app.schemas.task import (
    TaskActivityEntry,
    TaskAttachmentOut,
    TaskCreate,
    TaskOut,
    TaskReassign,
    TaskStatusUpdate,
    TaskUpdate,
)
from app.services import notification_service, task_service
from app.services.task_service import (
    TaskForbiddenError,
    TaskInvalidStateError,
    TaskNotFoundError,
    TaskValidationError,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])

_SERVICE_ERRORS = (
    TaskNotFoundError,
    TaskForbiddenError,
    TaskInvalidStateError,
    TaskValidationError,
    # إصلاح 2026-09-14 — راجعي نفس التعليق الكامل بـmeetings.py: كانت
    # مفقودة هنا كمان، فأي تاريخ مهمة خارج فترة عمل اللجنة يسبّب 500.
    CommitteePeriodError,
)


def _handle_errors(exc: Exception) -> Exception:
    if isinstance(exc, TaskNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, TaskForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, TaskInvalidStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (TaskValidationError, ValueError)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    try:
        task = await task_service.create_task(
            db,
            actor=current_user,
            committee_id=payload.committee_id,
            title=payload.title,
            start_date=payload.start_date,
            end_date=payload.end_date,
            assignee_user_id=payload.assignee_user_id,
            priority=payload.priority,
            reminder_offset_days=payload.reminder_offset_days,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    run_detached(
        notification_service.notify_task_created(task, actor_user_id=current_user.user_id)
    )
    return TaskOut.model_validate(task)


@router.get("", response_model=list[TaskOut])
async def list_tasks(current_user: CurrentUser, db: AsyncSession = Depends(get_db)) -> list[TaskOut]:
    tasks = await task_service.list_tasks(db, actor=current_user)
    return [TaskOut.model_validate(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> TaskOut:
    try:
        task = await task_service.get_task(db, task_id, actor=current_user)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return TaskOut.model_validate(task)


@router.get("/{task_id}/activity", response_model=list[TaskActivityEntry])
async def get_task_activity(
    task_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[TaskActivityEntry]:
    """مسار المهمة الموحَّد (إعادة إسناد + تغييرات حالة/أولوية/بيانات) — راجعي task_service.get_task_activity."""
    try:
        return await task_service.get_task_activity(db, actor=current_user, task_id=task_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    try:
        task = await task_service.update_task(
            db,
            actor=current_user,
            task_id=task_id,
            title=payload.title,
            start_date=payload.start_date,
            end_date=payload.end_date,
            priority=payload.priority,
            reminder_offset_days=payload.reminder_offset_days,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return TaskOut.model_validate(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    try:
        await task_service.delete_task(db, actor=current_user, task_id=task_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc


@router.post("/{task_id}/status", response_model=TaskOut)
async def update_task_status(
    task_id: uuid.UUID,
    payload: TaskStatusUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    try:
        task = await task_service.update_status(
            db, actor=current_user, task_id=task_id, status=payload.status
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    run_detached(
        notification_service.notify_task_status_changed(task, actor_user_id=current_user.user_id)
    )
    return TaskOut.model_validate(task)


@router.post("/{task_id}/reassign", response_model=TaskOut)
async def reassign_task(
    task_id: uuid.UUID,
    payload: TaskReassign,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    try:
        task = await task_service.reassign_task(
            db, actor=current_user, task_id=task_id, assignee_user_id=payload.assignee_user_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    run_detached(
        notification_service.notify_task_reassigned(task, actor_user_id=current_user.user_id)
    )
    return TaskOut.model_validate(task)


def _attachment_out(document, linked_at) -> TaskAttachmentOut:
    return TaskAttachmentOut(
        document_id=document.document_id,
        title=document.title,
        file_name=document.file_name,
        mime_type=document.mime_type,
        file_size_bytes=document.file_size_bytes,
        uploaded_by=CommitteeMemberUserOut.model_validate(document.uploader),
        linked_at=linked_at,
    )


@router.post(
    "/{task_id}/attachments",
    response_model=TaskAttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_task_attachment(
    task_id: uuid.UUID,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> TaskAttachmentOut:
    """
    مرفق اختياري بالمهمة (طلب صاحبة المشروع 2026-11-01) — رئيسة اللجنة
    عند الإنشاء عادةً (استدعاء منفصل بعد POST /tasks، نفس نمط مرفقات
    الاجتماعات)، أو المسؤول عن المهمة لاحقًا (يقدر يرفع أكثر من ملف).
    multipart/form-data لأن الملف يمر عبر الـBackend إلى Supabase Storage.
    """
    content = await file.read()
    try:
        document, linked_at = await task_service.add_attachment(
            db,
            actor=current_user,
            task_id=task_id,
            title=file.filename or "بدون عنوان",
            file_name=file.filename or "unnamed",
            mime_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return _attachment_out(document, linked_at)


@router.get("/{task_id}/attachments", response_model=list[TaskAttachmentOut])
async def list_task_attachments(
    task_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[TaskAttachmentOut]:
    try:
        rows = await task_service.list_attachments(db, actor=current_user, task_id=task_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return [_attachment_out(document, linked_at) for document, linked_at in rows]


@router.get("/{task_id}/attachments/{document_id}/download")
async def download_task_attachment(
    task_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        document, content = await task_service.get_attachment_download(
            db, actor=current_user, task_id=task_id, document_id=document_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return Response(
        content=content,
        media_type=document.mime_type,
        # الاسم عربي غالبًا — _content_disposition (RFC 5987) من documents.py
        # (إصلاح 2026-11-02: نفس خلل الأحرف العربية بـContent-Disposition
        # المُصلَح سابقًا لمرفقات الاجتماعات، لكنه فات هذا المسار).
        headers={"Content-Disposition": _content_disposition(document.file_name)},
    )


@router.delete(
    "/{task_id}/attachments/{document_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_task_attachment(
    task_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await task_service.delete_attachment(
            db, actor=current_user, task_id=task_id, document_id=document_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
