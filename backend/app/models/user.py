"""
الهدف:
نموذج SQLAlchemy ORM لجدول users — يطابق تمامًا بنية الجدول الحقيقي بعد
db/migrations/0006_roles_permissions.sql (الدور أصبح role_id ديناميكيًا
بدل عمود Enum ثابت).

المسؤولية:
تمثيل صف واحد من جدول users، بما في ذلك الدور الديناميكي (role_id → جدول
roles)، حالة الحساب (user_status)، وحقول الأمان (failed_login_attempts,
locked_until, must_change_password).

ملاحظات أمنية:
- password_hash يُخزَّن كـ bcrypt hash فقط — لا يوجد أي حقل لكلمة مرور نصية.
- role_id يشير لجدول roles (قابل للإنشاء/التعديل من الواجهة) بدل Enum ثابت
  في قاعدة البيانات — أي دور جديد لا يحتاج أي هجرة (migration) أو تعديل كود.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm.base import NO_VALUE

from app.db.base import Base
from app.models.user_role import UserRole  # noqa: F401 — يسجّل الموديل لعلاقة assigned_roles (مراجع نصية)


class UserStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    username: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Object ID لحساب Microsoft 365 المرتبط (migration 0042) — يُحفظ عند أول
    # دخول بـMicrosoft، وكل دخول بعده لازم يطابقه. NULL = لم يُربط بعد.
    microsoft_object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # اختياري (migration 0014 — مراجعة لاما 2026-08-30): "عدم وجود دور لا
    # يعني أن المستخدم لا يستطيع تسجيل الدخول" — مستخدم بدون دور يصل
    # لبياناته الأساسية فقط (GET /users/me)، وصفر صلاحيات إضافية، لحين
    # تعيين دور له. راجعي permission_codes/permission_scopes/scope_for
    # أدناه — كلها آمنة مع role=None (تُرجع فارغ بدل انهيار).
    #
    # تعدد الأدوار (migration 0046): هذا العمود صار "الدور الحالي" (Active
    # Role) — أحد أدوار المستخدم المسندة في user_roles (مضمون بقيد قاعدة
    # البيانات users_active_role_assigned_fkey). كل فحوصات الصلاحيات تبقى
    # تقرأ هذا الدور وحده (role/permission_codes/scope_for)، فالمستخدم
    # متعدد الأدوار يشتغل بصلاحيات دوره الحالي فقط حتى يبدّله.
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.role_id"), nullable=True
    )
    dep_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.dep_id"), nullable=True
    )
    job_title_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_titles.job_title_id"), nullable=True
    )

    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, name="user_status", native_enum=True),
        nullable=False,
        server_default=UserStatus.active.value,
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    failed_login_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # حساب ضيف مؤقت من خارج المنصة (migration 0047 — قرار لاما 2026-11-10):
    # مربوط باجتماع واحد فقط، بلا دور نظامي، ولا يسجل دخول بكلمة مرور.
    # راجعي services/meeting_guest_service.py.
    is_guest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    guest_meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.meeting_id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    department: Mapped["Department | None"] = relationship(  # noqa: F821
        back_populates="users", foreign_keys=[dep_id]
    )
    role: Mapped["Role | None"] = relationship(back_populates="users", lazy="selectin")  # noqa: F821
    job_title: Mapped["JobTitle | None"] = relationship(  # noqa: F821
        foreign_keys=[job_title_id], lazy="selectin"
    )
    # كل الأدوار النظامية المسندة (migration 0046) — للقراءة فقط (viewonly):
    # الكتابة صراحةً عبر جدول user_roles بطبقة الخدمة. lazy="raise_on_sql"
    # عمدًا (وليس selectin كبقية العلاقات): لو كانت selectin، كل select(User)
    # بأي مكان بالنظام (القوائم، المصادقة بكل طلب...) يضيف استعلامًا إضافيًا
    # بلا داعٍ. هنا لا تُحمَّل إلا حين تُطلب صراحةً
    # (selectinload(User.assigned_roles))، وأي وصول لها بدون تحميل يرمي خطأ
    # واضحًا بدل استعلام خفي. للعرض استخدمي الخاصية roles أدناه (آمنة دائمًا).
    assigned_roles: Mapped[list["Role"]] = relationship(  # noqa: F821
        secondary="user_roles",
        primaryjoin="User.user_id == UserRole.user_id",
        secondaryjoin="UserRole.role_id == Role.role_id",
        # ترتيب الإسناد، ثم الاسم (أدوار نفس الحفظ تتشارك نفس الوقت).
        order_by="[UserRole.created_at, Role.name]",
        viewonly=True,
        lazy="raise_on_sql",
    )

    @property
    def roles(self) -> list | None:
        """
        الأدوار المسندة لو حُمِّلت مسبقًا بنفس الاستعلام، وإلا None — بدون
        أي استعلام إضافي أبدًا. يقرأها UserOut.roles: المسارات اللي تحتاج
        عرض كل الأدوار (قائمة المستخدمين، تفاصيل مستخدم، إنشاء/تعديل) تحمّلها
        صراحةً، والباقي يرجّع null بدل استعلام خفي.
        """
        loaded = sa_inspect(self).attrs.assigned_roles.loaded_value
        return None if loaded is NO_VALUE else list(loaded)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def is_super_admin(self) -> bool:
        return self.role is not None and self.role.is_super_admin

    @property
    def permission_codes(self) -> set[str]:
        """صلاحيات المستخدم الفعلية — مجموعة فارغة إن لم يُعيَّن له دور بعد."""
        return self.role.permission_codes if self.role is not None else set()

    @property
    def permission_scopes(self) -> dict[str, str]:
        return self.role.permission_scopes if self.role is not None else {}

    def scope_for(self, *codes: str) -> str | None:
        """راجعي Role.scope_for — نفس المنطق، آمن مع مستخدم بدون دور (تُرجع None)."""
        return self.role.scope_for(*codes) if self.role is not None else None

    def department_ids_for_scope(self, scope: str | None) -> set[uuid.UUID]:
        """
        الهدف:
        الإدارات اللي يغطيها نطاق صلاحية مرتبط بالإدارة لهذا المستخدم —
        نقطة واحدة لكل فحوصات النطاق بالنظام (بدل تكرار المقارنة بكل خدمة).

        المدخلات:
        - scope: نطاق الصلاحية (عادةً ناتج scope_for).

        المخرجات (set[UUID]):
        - department: {إدارته} فقط.
        - department_tree: {إدارته} + كل الإدارات التابعة النشطة لها
          (فارغة التوابع لو إدارته نفسها تابعة أو بلا توابع).
        - أي نطاق آخر (own/all/None)، أو مستخدم بلا إدارة: مجموعة فارغة —
          own وall لا يُحسبان بالإدارات أصلًا.

        التأثيرات الجانبية: لا شيء (حساب بالذاكرة).

        الاعتماديات / الأخطاء المحتملة:
        department_tree يقرأ department.child_dep_ids — محمَّل مسبقًا على مسار
        المصادقة (user_service._profile_options). مستخدم محمَّل بغير هذا
        المسار يرمي خطأ raiseload واضحًا بدل نتيجة خاطئة صامتة.
        """
        if self.dep_id is None or scope not in ("department", "department_tree"):
            return set()
        ids = {self.dep_id}
        if scope == "department_tree" and self.department is not None:
            ids.update(self.department.child_dep_ids or [])
        return ids

    def related_department_ids(self) -> set[uuid.UUID]:
        """
        إدارته + إدارتها الأم (لو كانت تابعة) + إداراتها التابعة (لو كانت أمًّا)
        — لرؤية ما يُشارَك على مستوى الإدارة (الوثائق وتصنيفاتها) عبر الهيكل
        بالاتجاهين (قرار لاما 2026-11-15). مستخدم بلا إدارة: مجموعة فارغة.
        يعتمد على department.child_dep_ids المحمَّل بمسار المصادقة (راجعي
        department_ids_for_scope).
        """
        if self.dep_id is None:
            return set()
        ids = {self.dep_id}
        if self.department is not None:
            if self.department.parent_dep_id is not None:
                ids.add(self.department.parent_dep_id)
            ids.update(self.department.child_dep_ids or [])
        return ids

    def department_and_parent_ids(self) -> set[uuid.UUID]:
        """
        إدارته + إدارتها الأم (لو كانت تابعة) — للأشياء المعرَّفة على مستوى
        الإدارة الأم وتشمل إداراتها التابعة تلقائيًا (تصنيفات الوثائق الخاصة
        بإدارة أم — طلب لاما 2026-11-16). مستخدم بلا إدارة: مجموعة فارغة.
        """
        if self.dep_id is None:
            return set()
        ids = {self.dep_id}
        if self.department is not None and self.department.parent_dep_id is not None:
            ids.add(self.department.parent_dep_id)
        return ids

    def scope_covers_department(self, scope: str | None, dep_id: uuid.UUID | None) -> bool:
        """
        هل نطاق مرتبط بالإدارة (department/department_tree) يغطي إدارة معيّنة؟
        dep_id = None (مثل لجنة رئيسها بلا إدارة) لا يُغطّى أبدًا. own/all
        يرجعان False هنا — يُفحصان بمكانهما كما كانا. راجعي
        department_ids_for_scope أعلاه.
        """
        return dep_id is not None and dep_id in self.department_ids_for_scope(scope)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.middle_name} {self.last_name}"

    @property
    def is_locked(self) -> bool:
        """هل الحساب مقفل حاليًا بسبب محاولات دخول فاشلة (FR-UM-019)؟"""
        return self.locked_until is not None and self.locked_until > datetime.now(
            self.locked_until.tzinfo
        )
