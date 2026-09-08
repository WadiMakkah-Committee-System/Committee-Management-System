"""
الهدف:
نموذج SQLAlchemy ORM لجدول notifications (الإشعارات داخل النظام) —
يطابق بنية db/migrations/0027_notifications_schema.sql.

راجعي رأس ملف الـmigration نفسه لكل الاجتهادات الموثّقة (النوعان
الممكنان للمستلم — فردي أو جماعي بالصلاحية وقت الحدث، event_type نصي حر
بدل Enum، related_entity_type/id بدون FK فعلي لأنها Polymorphic).

مصدر الحقيقة الوحيد لقائمة event_type المدعومة فعليًا هو
app/services/notification_service.py — لا تُكرَّر هنا كـEnum لتفادي
ازدواج المصدر (نفس سبب عدم وجود Enum بقاعدة البيانات، راجعي ملاحظة
التصميم رقم 2 برأس الـmigration).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )

    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    related_entity_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    recipient: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821
