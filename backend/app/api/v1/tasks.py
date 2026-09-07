"""
الهدف:
راوتات REST لوحدة "إدارة المهام". راجعي رأس app/services/task_service.py
للتفويض والاجتهادات الموثّقة.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.task import (
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
    background_tasks: BackgroundTasks,
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
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    background_tasks.add_task(
        notification_service.notify_task_created, task, actor_user_id=current_user.user_id
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
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    try:
        task = await task_service.update_status(
            db, actor=current_user, task_id=task_id, status=payload.status
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    background_tasks.add_task(
        notification_service.notify_task_status_changed, task, actor_user_id=current_user.user_id
    )
    return TaskOut.model_validate(task)


@router.post("/{task_id}/reassign", response_model=TaskOut)
async def reassign_task(
    task_id: uuid.UUID,
    payload: TaskReassign,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    try:
        task = await task_service.reassign_task(
            db, actor=current_user, task_id=task_id, assignee_user_id=payload.assignee_user_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    background_tasks.add_task(
        notification_service.notify_task_reassigned, task, actor_user_id=current_user.user_id
    )
    return TaskOut.model_validate(task)
