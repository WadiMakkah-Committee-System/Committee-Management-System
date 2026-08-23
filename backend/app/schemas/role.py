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
#: بقية الأقسام (اللجان، الاجتماعات...) موجودة في الكتالوج فقط تحضيرًا
#: للمراحل القادمة — is_enforced تسمح للواجهة بعرضها كـ "قريبًا" بدل
#: تكرار هذه القائمة يدويًا في كود الفرونت.
ENFORCED_CATEGORIES = {"departments", "users"}


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    permission_id: uuid.UUID
    code: str
    category: str
    label_ar: str
    sort_order: int

    @computed_field  # type: ignore[misc]
    @property
    def is_enforced(self) -> bool:
        """
        هل هذا القسم فيه فعليًا endpoint يتحقق من الصلاحية، أم مجرد بيانات
        كتالوج تحضيرًا لمرحلة قادمة؟ تسمح للواجهة بعرض "قريبًا" بدون تكرار
        قائمة الأقسام المفعّلة يدويًا في كود الفرونت.
        """
        return self.category in ENFORCED_CATEGORIES


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None
    permission_codes: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = None
    permission_codes: list[str] | None = None


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role_id: uuid.UUID
    name: str
    description: str | None
    is_system: bool
    is_super_admin: bool
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

    permissions: list[PermissionOut]
    permission_count: int
    user_count: int
