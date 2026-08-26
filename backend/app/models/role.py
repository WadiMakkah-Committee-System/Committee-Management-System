"""
الهدف:
نموذج SQLAlchemy ORM لجدولي roles و role_permissions — يطابق بنية
db/migrations/0006_roles_permissions.sql.

المسؤولية:
تمثيل الأدوار الديناميكية القابلة للإنشاء/التعديل/الحذف من الواجهة (بدون
أي تعديل على الكود)، وربطها بمجموعة الصلاحيات الخاصة بكل دور عبر جدول
وسيط (role_permissions).

ملاحظات:
- is_system: يُعلَّم الأدوار الخمسة الأساسية (super_admin, admin, ...)
  للعرض فقط بالواجهة ("نظامي") — قرار عمل موثّق: فُكّت عنها الحماية
  بالكامل (تعديل الاسم والحذف)، فلم يعد هذا الحقل يفرض أي قيد فعلي على
  مستوى الخدمة (role_service)؛ الحماية الوحيدة المتبقية هي عدم وجود
  مستخدمين مرتبطين بالدور عند الحذف.
- is_super_admin: دور واحد فقط في كل النظام يحمل هذه العلامة — يُستخدم
  كمرجع لحماية "آخر مستخدم بصلاحية كاملة" بدل الاعتماد على مقارنة اسم
  نصي ثابت (كان user.role == UserRole.super_admin سابقًا).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Table, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.role_id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        UUID(as_uuid=True),
        ForeignKey("permissions.permission_id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Permission(Base):
    __tablename__ = "permissions"

    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    label_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Role(Base):
    __tablename__ = "roles"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_super_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    permissions: Mapped[list[Permission]] = relationship(secondary=role_permissions, lazy="selectin")
    users: Mapped[list["User"]] = relationship(back_populates="role")  # noqa: F821

    @property
    def permission_codes(self) -> set[str]:
        return {p.code for p in self.permissions}
