"""
الهدف:
نموذج SQLAlchemy ORM لجدول departments — يطابق تمامًا بنية الجدول الحقيقي
في db/migrations/0002_create_departments.sql (تم التحقق عبر Supabase MCP
list_tables على القاعدة الفعلية).

المسؤولية:
تمثيل صف واحد من جدول departments ككائن بايثون، مع العلاقة العكسية مع
users (إدارة واحدة لديها عدة مستخدمين).

ملاحظات:
- Soft Delete عبر deleted_at (NULLABLE) — لا يوجد حذف فعلي (DELETE) لهذا
  الجدول في منطق التطبيق أبدًا؛ الحذف = تعيين deleted_at = now().
- التفرد الفعلي على name يُطبَّق عبر partial unique index في القاعدة
  (uq_departments_name_active) وليس عبر SQLAlchemy.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Department(Base):
    __tablename__ = "departments"

    dep_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    manager_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True
    )

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    users: Mapped[list["User"]] = relationship(  # noqa: F821
        back_populates="department", foreign_keys="User.dep_id"
    )
    manager: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[manager_user_id], lazy="selectin"
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
