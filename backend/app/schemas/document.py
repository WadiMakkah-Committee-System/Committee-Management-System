"""
الهدف:
Pydantic Schemas الخاصة بوحدة "إدارة الوثائق" — تصنيفات الوثائق
(DocumentCategory) والوثائق نفسها (Document)، بما في ذلك نطاق الرؤية
المركّب (عام / إدارات محددة / لجان محددة / مستخدمون محددون).

المسؤولية:
التحقق من صحة المدخلات، وتحديد شكل البيانات المرجَعة للعميل. رفع الملف
نفسه لا يمر بـ Pydantic (multipart/form-data عبر UploadFile + Form) —
DocumentCreateForm هنا للتوثيق فقط (Swagger)، الفعلي في الـ Route مباشرة.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.document import DocumentStatus

# نستخدم Literal هنا (بدل استيراد DocumentCategoryScope من app.models.document
# مباشرة كما جرت العادة مع بقية Enums بالمشروع) لأن قيمة العضو "global_"
# تحمل شرطة سفلية لتفادي تعارضها مع الكلمة المحجوزة global في بايثون، بينما
# القيمة الفعلية بالـ API/القاعدة هي "global" بدونها — Literal يعكس شكل الـ
# API الصحيح مباشرة دون هذا الالتباس.
DocumentCategoryScope = Literal["global", "department"]


# ---------------------------------------------------------------------------
# تصنيفات الوثائق (Document Categories)
# ---------------------------------------------------------------------------


class DocumentCategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    scope: DocumentCategoryScope
    department_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _validate_scope_department(self) -> "DocumentCategoryCreate":
        if self.scope == "global" and self.department_id is not None:
            raise ValueError("التصنيف العام لا يجوز ربطه بإدارة")
        if self.scope == "department" and self.department_id is None:
            raise ValueError("التصنيف الخاص بإدارة يجب تحديد الإدارة له")
        return self


class DocumentCategoryUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=150)


class DocumentCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: uuid.UUID
    name: str
    scope: DocumentCategoryScope
    department_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    @field_validator("scope", mode="before")
    @classmethod
    def _coerce_scope(cls, value: object) -> object:
        """
        القيمة القادمة من الـ ORM هي app.models.document.DocumentCategoryScope
        (عضوها "global_" بقيمة "global") وليست str عادية — رغم إنها str
        فعليًا (str, Enum)، Pydantic v2 يرفضها ضد Literal["global",
        "department"] لأنه ما يعتبرها مطابقة تلقائيًا (literal_error). نحوّلها
        هنا صراحةً لقيمتها النصية (.value) قبل التحقق، بدل تغيير الـ Literal
        نفسه (راجعي التعليق فوق DocumentCategoryScope لسبب استخدام Literal).
        """
        return value.value if isinstance(value, Enum) else value


# ---------------------------------------------------------------------------
# الوثائق (Documents)
# ---------------------------------------------------------------------------


class DocumentUploaderOut(BaseModel):
    """شكل مختصر لبيانات رافع الوثيقة — يُستخدم مضمَّنًا داخل DocumentOut."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    first_name: str
    middle_name: str
    last_name: str


class DocumentVisibleDepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dep_id: uuid.UUID
    name: str


class DocumentVisibleCommitteeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    committee_id: uuid.UUID
    name: str


class DocumentVisibleUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    first_name: str
    middle_name: str
    last_name: str


class DocumentPublishTargetsOut(BaseModel):
    """
    الإدارات واللجان اللي يحق فعليًا للمستخدم الحالي إتاحة وثيقة لها عند
    الرفع (مبدأ أقل صلاحية ممكنة) — راجع document_service.get_publish_targets.
    """

    departments: list[DocumentVisibleDepartmentOut]
    committees: list[DocumentVisibleCommitteeOut]


class DocumentUpdate(BaseModel):
    """
    تعديل بيانات وثيقة موجودة (Metadata فقط — لا يوجد استبدال للملف نفسه
    في هذه المرحلة؛ لتغيير الملف تُرفع وثيقة جديدة). كل الحقول اختيارية:
    الحقل المتروك None لا يُعدَّل، وقوائم الرؤية (department_ids/...)
    عند إرسالها تستبدل القائمة القديمة بالكامل (قائمة فارغة = إزالة الكل).
    """

    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = None
    category_id: uuid.UUID | None = None
    is_public: bool | None = None
    department_ids: list[uuid.UUID] | None = None
    committee_ids: list[uuid.UUID] | None = None
    user_ids: list[uuid.UUID] | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    title: str
    description: str | None
    file_name: str
    mime_type: str
    file_size_bytes: int
    category: DocumentCategoryOut | None
    status: DocumentStatus
    is_public: bool
    uploader: DocumentUploaderOut
    visible_departments: list[DocumentVisibleDepartmentOut]
    visible_committees: list[DocumentVisibleCommitteeOut]
    visible_users: list[DocumentVisibleUserOut]
    created_at: datetime
    updated_at: datetime
