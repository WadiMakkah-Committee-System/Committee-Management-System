"""
الهدف:
Pydantic Schemas لرفع ملف المستخدمين (users.import — 2026-11-01).
لاحظي: كلمات المرور المؤقتة لا تظهر بأي استجابة — تُرسَل لبريد كل مستخدم فقط.
"""

import uuid

from pydantic import BaseModel


class ImportedUserOut(BaseModel):
    """مستخدم أُنشئ من صف بالملف (رقم الصف لمطابقته مع الملف الأصلي)."""

    row: int
    user_id: uuid.UUID
    full_name: str
    email: str
    username: str
    department: str | None
    role: str | None
    is_department_manager: bool


class ImportedDepartmentOut(BaseModel):
    """إدارة أُنشئت تلقائيًا لأنها لم تكن موجودة."""

    name: str
    code: str
    # إدارتها الأم (migration 0052 — null = بالمستوى الأعلى).
    parent_name: str | None = None


class UserImportResult(BaseModel):
    """
    استجابة نجاح POST /users/import (201).
    emails_queued: عدد رسائل بيانات الدخول المجدولة للإرسال بعد الحفظ.
    """

    created_count: int
    users: list[ImportedUserOut]
    departments_created: list[ImportedDepartmentOut]
    # مسميات وظيفية لم تكن موجودة وأُضيفت تلقائيًا (2026-11-01).
    job_titles_created: list[str] = []
    emails_queued: int
    # عدد التعيينات (إدارة + دور) المنشأة — قد يزيد على عدد المستخدمين.
    assignments_count: int = 0


class ImportPreviewAssignmentOut(BaseModel):
    department: str | None
    role: str | None


class ImportPreviewUserOut(BaseModel):
    """مستخدم سيُنشأ (أول صف له بالملف) مع كل تعييناته."""

    row: int
    full_name: str
    email: str
    primary_department: str | None
    assignments: list[ImportPreviewAssignmentOut]


class ImportPreviewDepartmentOut(BaseModel):
    """إدارة جديدة ستُنشأ تلقائيًا (parent_name = إدارتها الأم، null = بالمستوى الأعلى)."""

    name: str
    parent_name: str | None


class UserImportPreview(BaseModel):
    """
    استجابة POST /users/import/preview (200) — ملخص ما سيُنشأ، بلا أي كتابة.
    الواجهة تعرضه للتأكيد ثم ترسل نفس الملف لـPOST /users/import.
    """

    users_count: int
    assignments_count: int
    users: list[ImportPreviewUserOut]
    departments_to_create: list[ImportPreviewDepartmentOut]
    job_titles_to_create: list[str]


class ImportRowErrorOut(BaseModel):
    """خطأ بصف محدد (row = رقم الصف كما بالـExcel، field = اسم العمود)."""

    row: int
    field: str | None
    message: str
