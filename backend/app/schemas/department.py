"""
الهدف:
Pydantic Schemas الخاصة بالإدارات (Departments) — تحدّد شكل بيانات
الطلبات (Request) والردود (Response) لواجهات إدارة الإدارات (FR-UM-007 →
FR-UM-010)، وتفصل شكل الـ API عن نموذج قاعدة البيانات (ORM).

المسؤولية:
التحقق من صحة المدخلات (طول الاسم مثلًا) وتحديد الحقول المسموح إرجاعها
للعميل (لا نُرجع deleted_at إلا عند الحاجة الإدارية مثلًا).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DepartmentManagerOut(BaseModel):
    """شكل مختصر لبيانات المسؤول عن الإدارة — يُستخدم مضمَّنًا داخل DepartmentOut."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    first_name: str
    middle_name: str
    last_name: str
    email: str


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    code: str = Field(min_length=1, max_length=20)
    description: str | None = None
    manager_user_id: uuid.UUID
    # أعضاء الإدارة من نفس نموذج الإنشاء (طلب صاحبة المشروع 2026-10-29) —
    # اختياري؛ المسؤول يُضاف تلقائيًا دائمًا فلا حاجة لتكراره هنا. من كان
    # بإدارة أخرى يُنقَل إليها (نفس قاعدة المسؤول القائمة).
    member_user_ids: list[uuid.UUID] = Field(default_factory=list)
    # هيكل المستويين (migration 0048): اختياري — الإدارة الأم اللي تتبعها
    # الإدارة الجديدة. None = إدارة بالمستوى الأعلى.
    parent_dep_id: uuid.UUID | None = None

    @field_validator("member_user_ids")
    @classmethod
    def _no_duplicate_members(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(v)) != len(v):
            raise ValueError("لا يمكن تكرار نفس العضو أكثر من مرة")
        return v


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    code: str | None = Field(default=None, min_length=1, max_length=20)
    description: str | None = None
    manager_user_id: uuid.UUID | None = None
    # migration 0048: غياب الحقل = بلا تغيير، null صريح = فكّ الإدارة من أمها
    # (تُميَّز عبر model_fields_set بطبقة الـAPI)، معرّف = نقلها تحت تلك الأم.
    parent_dep_id: uuid.UUID | None = None


class DepartmentRefOut(BaseModel):
    """مرجع مختصر لإدارة (المعرّف والاسم والرمز) — للإدارة الأم بصفحة التفاصيل."""

    model_config = ConfigDict(from_attributes=True)

    dep_id: uuid.UUID
    name: str
    code: str | None


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dep_id: uuid.UUID
    name: str
    code: str | None
    description: str | None
    manager: DepartmentManagerOut | None = None
    # migration 0048: الإدارة الأم (null = إدارة بالمستوى الأعلى) — تبني منه
    # الواجهة شجرة الإدارات من قائمة واحدة.
    parent_dep_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class DepartmentSummaryOut(DepartmentOut):
    """شكل الإدارة في قائمة الإدارات — يضيف عدد الأعضاء دون تحميل القائمة كاملة."""

    member_count: int


class DepartmentDetailOut(DepartmentOut):
    """تفاصيل إدارة واحدة — تُستخدم في صفحة "تفاصيل الإدارة"."""

    member_count: int
    members: list["UserOut"]  # noqa: F821 — يُحل عبر model_rebuild في schemas/user.py
    # هيكل المستويين (migration 0048): الإدارة الأم (لو كانت هذه تابعة)،
    # والإدارات التابعة مع عدد أعضاء كل منها (لو كانت هذه أمًّا).
    parent: DepartmentRefOut | None = None
    children: list[DepartmentSummaryOut] = Field(default_factory=list)
