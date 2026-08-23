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

from pydantic import BaseModel, ConfigDict, Field


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


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    code: str | None = Field(default=None, min_length=1, max_length=20)
    description: str | None = None
    manager_user_id: uuid.UUID | None = None


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dep_id: uuid.UUID
    name: str
    code: str | None
    description: str | None
    manager: DepartmentManagerOut | None = None
    created_at: datetime
    updated_at: datetime


class DepartmentSummaryOut(DepartmentOut):
    """شكل الإدارة في قائمة الإدارات — يضيف عدد الأعضاء دون تحميل القائمة كاملة."""

    member_count: int


class DepartmentDetailOut(DepartmentOut):
    """تفاصيل إدارة واحدة — تُستخدم في صفحة "تفاصيل الإدارة"."""

    member_count: int
    members: list["UserOut"]  # noqa: F821 — يُحل عبر model_rebuild في schemas/user.py
