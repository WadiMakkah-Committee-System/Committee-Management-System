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
- هيكل المستويين (migration 0048 — قرار لاما 2026-11-15): parent_dep_id
  يربط الإدارة التابعة بإدارتها الأم. NULL = إدارة أم (أو إدارة مستقلة
  بلا إدارات تابعة). قواعد الهيكل مفروضة بـtrigger في القاعدة نفسها
  (enforce_department_hierarchy)، والخدمة تتحقق منها مسبقًا برسائل واضحة.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func, literal_column, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

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
    parent_dep_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.dep_id"), nullable=True
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

    @property
    def is_parent_level(self) -> bool:
        """هل الإدارة في المستوى الأعلى (بلا إدارة أم)؟ — يُسمح فقط لهذا المستوى بأن يكون تحته إدارات."""
        return self.parent_dep_id is None


# معرّفات الإدارات التابعة النشطة لهذه الإدارة — subquery مرتبط داخل نفس
# استعلام الإدارة (بلا رحلة شبكة إضافية). يُستخدم لحساب نطاق
# "department_tree" (إدارته وما تحتها) بفحوصات الصلاحيات المتزامنة.
# deferred + raiseload عمدًا: لا يُحسب إلا حين يُطلب صراحةً
# (undefer(Department.child_dep_ids) — مسار المصادقة بـuser_service.
# _profile_options)، وأي وصول له بدون تحميل يرمي خطأ واضحًا بدل استعلام
# خفي أو نتيجة خاطئة صامتة.
# alias على مستوى الجدول (Core) وليس aliased(Department): aliased يفرض تهيئة
# كل الـmappers وقت الاستيراد قبل تعريف بقية الموديلات.
_child_department = Department.__table__.alias("child_department")
Department.child_dep_ids = column_property(
    select(func.coalesce(func.array_agg(_child_department.c.dep_id), literal_column("'{}'::uuid[]")))
    .where(
        _child_department.c.parent_dep_id == Department.dep_id,
        _child_department.c.deleted_at.is_(None),
    )
    .correlate_except(_child_department)
    .scalar_subquery(),
    deferred=True,
    raiseload=True,
)
