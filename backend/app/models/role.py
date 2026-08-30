"""
الهدف:
نموذج SQLAlchemy ORM لجداول roles و permissions و role_permissions —
يطابق بنية db/migrations/0006_roles_permissions.sql + 0014_permission_scopes_and_role_optional.sql.

المسؤولية:
تمثيل الأدوار الديناميكية القابلة للإنشاء/التعديل/الحذف من الواجهة (بدون
أي تعديل على الكود)، وربطها بمجموعة الصلاحيات الخاصة بكل دور — كل منح
(دور، صلاحية) يحمل الآن نطاق وصول (scope) مستقل أيضًا.

ملاحظات:
- is_system: يُعلَّم الأدوار الخمسة الأساسية (super_admin, admin, ...)
  للعرض فقط بالواجهة ("نظامي") — قرار عمل موثّق: فُكّت عنها الحماية
  بالكامل (تعديل الاسم والحذف)، فلم يعد هذا الحقل يفرض أي قيد فعلي على
  مستوى الخدمة (role_service)؛ الحماية الوحيدة المتبقية هي عدم وجود
  مستخدمين مرتبطين بالدور عند الحذف.
- is_super_admin: دور واحد فقط في كل النظام يحمل هذه العلامة — يُستخدم
  كمرجع لحماية "آخر مستخدم بصلاحية كاملة" بدل الاعتماد على مقارنة اسم
  نصي ثابت (كان user.role == UserRole.super_admin سابقًا). لا يُستخدم
  للتجاوز التلقائي للصلاحيات (قرار موثّق 2026-08-27) — فقط لحماية شاشة
  "الأدوار والصلاحيات" نفسها (require_super_admin) من القفل الكامل.

مراجعة لاما 2026-08-30 (فصل الصلاحية عن نطاق الوصول):
role_permissions تحوّل من جدول ربط بسيط (Table عادي عبر secondary=) إلى
Association Object حقيقي (RolePermission) — لأنه صار يحمل عمود إضافي
(scope) لكل صف، ولا يمكن التعبير عن هذا عبر نمط secondary= البسيط (نفس
السبب اللي خلانا نضيف chair_user_id كعمود مستقل بدل تعديل الجدول الوسيط
بـmigration 0013 — الفرق هنا إن البيانات الإضافية على الجدول الوسيط
نفسه، فالحل الصحيح Association Object حسب توثيق SQLAlchemy الرسمي).

Role.permissions لم تعد Relationship قابلة للإسناد المباشر (role.permissions
= [...])  — صارت Property للقراءة فقط مبنية على role_permission_links.
لتعديل صلاحيات دور استخدمي role_service._sync_role_permissions (يدير
role_permission_links مباشرة، صف بصف، مع نطاق كل واحدة).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

#: نطاقات الوصول المدعومة حاليًا — راجعي db/migrations/0014 للتفاصيل
#: الكاملة. قائمة بسيطة (وليست Enum بقاعدة البيانات) لسهولة إضافة نطاق
#: جديد مستقبلًا بـmigration بسيط (ALTER CONSTRAINT) دون تعديل Enum.
VALID_SCOPES = ("own", "department", "all")

#: ترتيب "الاتساع" من الأوسع للأضيق — يُستخدم فقط عند امتلاك الدور نفس
#: الصلاحية عبر أكواد بديلة متعددة (راجعي Role.scope_for أدناه).
_SCOPE_BREADTH_ORDER = ("all", "department", "own")


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


class RolePermission(Base):
    """
    Association Object لجدول role_permissions — يربط دورًا بصلاحية مع
    نطاق وصول مستقل (scope) لكل ربط. راجعي docstring أعلى الملف والتعليق
    فوق VALID_SCOPES لتفاصيل التصميم الكاملة.
    """

    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.role_id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("permissions.permission_id", ondelete="CASCADE"),
        primary_key=True,
    )
    # own/department/all — راجعي db/migrations/0014 للتعريف الكامل.
    scope: Mapped[str] = mapped_column(String(20), nullable=False, server_default="all")

    permission: Mapped[Permission] = relationship(lazy="selectin")


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

    role_permission_links: Mapped[list[RolePermission]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )
    users: Mapped[list["User"]] = relationship(back_populates="role")  # noqa: F821

    @property
    def permissions(self) -> list[Permission]:
        """
        قائمة الصلاحيات المسطّحة (بدون نطاق) — للتوافق مع الاستخدامات
        التي لا تحتاج النطاق (عدّاد الصلاحيات بصفحة الأدوار، تسلسل
        RoleDetailOut.permissions الأساسي). للحصول على النطاق استخدمي
        permission_scopes/scope_for أدناه، ولتعديل الصلاحيات استخدمي
        role_service._sync_role_permissions (هذه Property للقراءة فقط).
        """
        return [link.permission for link in self.role_permission_links]

    @property
    def permission_codes(self) -> set[str]:
        return {link.permission.code for link in self.role_permission_links}

    @property
    def permission_scopes(self) -> dict[str, str]:
        """{كود_الصلاحية: نطاقها} لهذا الدور — كود غير موجود هنا = الدور لا يملكه إطلاقًا."""
        return {link.permission.code: link.scope for link in self.role_permission_links}

    def scope_for(self, *codes: str) -> str | None:
        """
        أوسع نطاق يملكه الدور بين عدّة أكواد صلاحية بديلة — بنفس منطق
        require_permission (يكفي امتلاك واحد منها). يُرجع None لو لا
        يملك أي كود منها إطلاقًا. مثال: scope_for("committees.request.create",
        "committees.request.update") تُرجع أوسع نطاق بين الاثنين لو ملك
        كلاهما، أو نطاق الوحيد المملوك لو ملك واحدًا فقط.
        """
        scopes = self.permission_scopes
        owned = {scopes[c] for c in codes if c in scopes}
        if not owned:
            return None
        for candidate in _SCOPE_BREADTH_ORDER:
            if candidate in owned:
                return candidate
        return None
