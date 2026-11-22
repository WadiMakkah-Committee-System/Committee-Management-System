"""
الهدف:
نموذج SQLAlchemy ORM لجدول user_department_roles — يطابق
db/migrations/0052_user_department_roles.sql.

المسؤولية:
تمثيل "تعيين" واحد: دور نظامي مسند لمستخدم، على إدارة محددة. المستخدم قد
يحمل أكثر من تعيين (أكثر من إدارة، وبدور مختلف في كل إدارة).

ملاحظات:
- (user_id, role_id) مربوط بـuser_roles بـON DELETE CASCADE: إزالة الدور من
  المستخدم تزيل تعييناته. والدور لازم يكون مسندًا (user_roles) قبل تعيينه.
- الكتابة صراحةً عبر app/services/user_assignment_service.py.
- دور مسند بلا أي صف هنا = نطاقه على الإدارة الأساسية (users.dep_id).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserDepartmentRole(Base):
    __tablename__ = "user_department_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "role_id"],
            ["user_roles.user_id", "user_roles.role_id"],
            ondelete="CASCADE",
            name="user_department_roles_role_assigned_fkey",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    dep_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.dep_id"), primary_key=True
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # للعرض فقط (اسم الإدارة والدور بجدول التعيينات) — تُحمَّل صراحةً.
    department: Mapped["Department"] = relationship(lazy="raise_on_sql")  # noqa: F821
    role: Mapped["Role"] = relationship(  # noqa: F821
        primaryjoin="foreign(UserDepartmentRole.role_id) == Role.role_id",
        viewonly=True,
        lazy="raise_on_sql",
    )


# --------------------------------------------------------------------------
# User.department_assignment_rows — كل تعيينات المستخدم كـJSONB بنفس استعلام
# المستخدم (scalar subquery، بلا رحلة شبكة إضافية على مسار المصادقة):
# [{"role_id", "dep_id", "parent_dep_id", "child_dep_ids": [...]}, ...]
# للإدارات غير المحذوفة فقط. تحسب منه User.department_ids_for_scope وأخواتها
# النطاق بالذاكرة. deferred + raiseload: يُحمَّل فقط بـ
# undefer(User.department_assignment_rows) (user_service._profile_options).
# مُعرَّف هنا (وليس بـuser.py) لأنه يحتاج جدولي التعيينات والإدارات؛
# app/models/__init__.py يستورد هذا الملف دائمًا.
# --------------------------------------------------------------------------
from sqlalchemy import and_, literal_column, select, type_coerce  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.orm import column_property  # noqa: E402

from app.models.department import Department  # noqa: E402
from app.models.user import User  # noqa: E402

_udr = UserDepartmentRole.__table__.alias("udr_scope")
_udr_dep = Department.__table__.alias("udr_scope_dep")
_udr_child = Department.__table__.alias("udr_scope_child")

_children = (
    select(func.coalesce(func.jsonb_agg(_udr_child.c.dep_id), literal_column("'[]'::jsonb")))
    .where(_udr_child.c.parent_dep_id == _udr_dep.c.dep_id, _udr_child.c.deleted_at.is_(None))
    .correlate(_udr_dep)
    .scalar_subquery()
)
_row = func.jsonb_build_object(
    "role_id", _udr.c.role_id,
    "dep_id", _udr_dep.c.dep_id,
    "parent_dep_id", _udr_dep.c.parent_dep_id,
    "child_dep_ids", _children,
)
User.department_assignment_rows = column_property(
    type_coerce(
        select(func.coalesce(func.jsonb_agg(_row), literal_column("'[]'::jsonb")))
        .select_from(
            _udr.join(_udr_dep, and_(_udr_dep.c.dep_id == _udr.c.dep_id, _udr_dep.c.deleted_at.is_(None)))
        )
        .where(_udr.c.user_id == User.__table__.c.user_id)
        .correlate_except(_udr, _udr_dep)
        .scalar_subquery(),
        JSONB,
    ),
    deferred=True,
    raiseload=True,
)
