"""
الهدف:
Pydantic Schemas الخاصة بوحدة "الإشعارات" داخل النظام. راجعي رأس
db/migrations/0027_notifications_schema.sql للاجتهادات الموثّقة.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notification_id: uuid.UUID
    event_type: str
    title: str
    body: str | None
    related_entity_type: str | None
    related_entity_id: uuid.UUID | None
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class NotificationPageOut(BaseModel):
    """نفس نمط AuditLogPageOut (صفحات محدودة الحجم، لا تحميل كل الإشعارات دفعة واحدة)."""

    items: list[NotificationOut]
    total: int
    limit: int
    offset: int


class UnreadCountOut(BaseModel):
    """عداد الجرس بالـTopbar — استعلام مستقل خفيف، لا يحمّل قائمة الإشعارات نفسها."""

    unread_count: int
