"""
الهدف:
راوتات REST لوحدة "الإشعارات" داخل النظام — راجعي رأس
app/services/notification_service.py (قسم "استعلامات المستخدم على
إشعاراته") للتفويض والاجتهادات الموثّقة.

كل المسارات هنا خاصة بإشعارات المستخدم الحالي فقط (current_user) — لا
يوجد مسار لعرض إشعارات مستخدم آخر، حتى لسوبر أدمن (الإشعار كائن خاص
بصاحبه بطبيعته، لا يوجد داعٍ عملي لإدارة إشعارات الغير).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.notification import NotificationOut, NotificationPageOut, UnreadCountOut
from app.services import notification_service
from app.services.notification_service import (
    NotificationForbiddenError,
    NotificationNotFoundError,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _handle_errors(exc: Exception) -> Exception:
    if isinstance(exc, NotificationNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, NotificationForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    raise exc


@router.get("", response_model=NotificationPageOut)
async def list_notifications(
    current_user: CurrentUser,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> NotificationPageOut:
    items, total = await notification_service.list_notifications(
        db, actor=current_user, unread_only=unread_only, limit=limit, offset=offset
    )
    return NotificationPageOut(
        items=[NotificationOut.model_validate(n) for n in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/unread-count", response_model=UnreadCountOut)
async def get_unread_count(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UnreadCountOut:
    count = await notification_service.get_unread_count(db, actor=current_user)
    return UnreadCountOut(unread_count=count)


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> NotificationOut:
    try:
        notification = await notification_service.mark_as_read(
            db, actor=current_user, notification_id=notification_id
        )
    except (NotificationNotFoundError, NotificationForbiddenError) as exc:
        raise _handle_errors(exc) from exc
    return NotificationOut.model_validate(notification)


@router.post("/read-all", response_model=UnreadCountOut)
async def mark_all_notifications_read(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UnreadCountOut:
    await notification_service.mark_all_as_read(db, actor=current_user)
    return UnreadCountOut(unread_count=0)
