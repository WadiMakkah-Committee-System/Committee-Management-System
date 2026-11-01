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


class UserImportResult(BaseModel):
    """
    استجابة نجاح POST /users/import (201).
    emails_queued: عدد رسائل بيانات الدخول المجدولة للإرسال بعد الحفظ.
    """

    created_count: int
    users: list[ImportedUserOut]
    departments_created: list[ImportedDepartmentOut]
    emails_queued: int


class ImportRowErrorOut(BaseModel):
    """خطأ بصف محدد (row = رقم الصف كما بالـExcel، field = اسم العمود)."""

    row: int
    field: str | None
    message: str
