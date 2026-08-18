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


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: str | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = None


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dep_id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
