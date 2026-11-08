"""
الهدف:
نموذج SQLAlchemy ORM لجدول user_roles — يطابق db/migrations/0046_user_roles.sql.

المسؤولية:
تمثيل إسناد دور نظامي واحد لمستخدم واحد (many-to-many بين users و roles).
المستخدم قد يحمل دورًا واحدًا أو أكثر؛ دوره "الحالي" (Active Role) هو
users.role_id، ويضمن قيد قاعدة البيانات users_active_role_assigned_fkey أنه
دائمًا أحد أدواره هنا.

ملاحظات:
- الكتابة على هذا الجدول تتم صراحةً عبر user_service (_replace_user_roles /
  assign_initial_role) — وليس عبر تعديل مجموعة User.assigned_roles (تلك
  علاقة للقراءة فقط viewonly=True).
- أدوار اللجان (roles.kind = 'committee') ممنوعة هنا بـTrigger في قاعدة
  البيانات، وبفحص صريح بطبقة الخدمة قبلها برسالة واضحة.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.role_id"), primary_key=True
    )
    # من أسند الدور — NULL لصفوف التعبئة الرجعية بـmigration 0046.
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
