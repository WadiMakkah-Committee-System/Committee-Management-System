"""
الهدف:
Pydantic Schemas الخاصة بالأدوار والصلاحيات (Roles & Permissions) — تسمح
لـ super_admin بإنشاء/تعديل/حذف أدوار وربطها بصلاحيات من الواجهة مباشرة،
دون أي حاجة لتعديل الكود أو قاعدة البيانات.

المسؤولية:
تحديد شكل بيانات الطلبات (إنشاء/تعديل دور) والردود (قائمة الأدوار مع عدد
الصلاحيات وعدد المستخدمين المرتبطين، وكتالوج الصلاحيات الكامل).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field


#: الأقسام التي يوجد لها بالفعل endpoint يتحقق من صلاحياتها فعليًا حاليًا.
#: بقية الأقسام (الاجتماعات...) موجودة في الكتالوج فقط تحضيرًا للمراحل
#: القادمة — is_enforced تسمح للواجهة بعرضها كـ "قريبًا" بدل تكرار هذه
#: القائمة يدويًا في كود الفرونت. "committees" أُضيفت بعد تفعيل Phase 2
#: (طلبات تشكيل اللجان — db/migrations/0009 + app/api/v1/committees.py).
ENFORCED_CATEGORIES = {"departments", "users", "committees", "job_titles"}


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    permission_id: uuid.UUID
    code: str
    category: str
    label_ar: str
    sort_order: int
    #: 'system' أو 'committee' — عمليًا كل صلاحيات الكتالوج الحالية
    #: kind='system' بعد حذف فئة "committee_roles" المصطنعة (مراجعة لاما
    #: 2026-09-01، راجعي db/migrations/0017_remove_committee_roles_category.sql):
    #: أدوار اللجان (رئيس/عضو) تختار الآن من نفس الصلاحيات النظامية
    #: الحقيقية تمامًا كأي دور آخر. العمود بقي بقاعدة البيانات لعدم كسر
    #: التوافق، لكن لا شيء يعتمد على قيمة 'committee' حاليًا.
    kind: str

    @computed_field  # type: ignore[misc]
    @property
    def is_enforced(self) -> bool:
        """
        هل هذه الصلاحية فيها فعليًا endpoint يتحقق منها، أم مجرد بيانات
        كتالوج تحضيرًا لمرحلة قادمة؟ تسمح للواجهة بعرضها كـ "قريبًا" بدون
        تكرار قائمة الأقسام/الأكواد المفعّلة يدويًا في كود الفرونت.
        """
        return self.category in ENFORCED_CATEGORIES


class RolePermissionOut(PermissionOut):
    """
    PermissionOut + نطاق الوصول (scope) الفعلي الممنوح لهذا الدور على هذه
    الصلاحية (own/department/all) — مراجعة لاما 2026-08-30: الصلاحية
    وحدها لا تحدد "على أي بيانات"؛ راجعي models/role.py (RolePermission).
    """

    scope: str


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None
    permission_codes: list[str] = Field(default_factory=list)
    #: {كود_الصلاحية: نطاقها} اختياري — أي كود غير مذكور هنا يأخذ 'all'
    #: افتراضيًا (راجعي role_service._sync_role_permissions).
    permission_scopes: dict[str, str] | None = None


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = None
    permission_codes: list[str] | None = None
    permission_scopes: dict[str, str] | None = None


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role_id: uuid.UUID
    name: str
    description: str | None
    is_system: bool
    is_super_admin: bool
    #: 'user' (دور نظامي، يظهر بقائمة الأدوار عند إنشاء مستخدم) أو
    #: 'committee' (رئيس اللجنة/عضو اللجنة — لا يظهر هناك إطلاقًا، قرار
    #: صريح لاما 2026-08-31). راجعي models/role.py وdb/migrations/0016.
    kind: str
    #: 'chair'/'member' لدوري اللجان الثابتين فقط، وNone لكل الأدوار
    #: النظامية — معرّف موثوق للواجهة بدل الاعتماد على name القابل للتعديل.
    committee_role_slug: str | None
    created_at: datetime
    updated_at: datetime


class RoleSummaryOut(BaseModel):
    """شكل مختصر للدور — يُستخدم مضمَّنًا داخل بيانات المستخدم (UserOut)."""

    model_config = ConfigDict(from_attributes=True)

    role_id: uuid.UUID
    name: str
    description: str | None
    is_super_admin: bool


class RoleDetailOut(RoleOut):
    """تفاصيل الدور الكاملة — تُستخدم في صفحة "الأدوار والصلاحيات"."""

    permissions: list[RolePermissionOut]
    permission_count: int
    user_count: int
