"""
الهدف:
Pydantic Schemas الخاصة بالمستخدمين (Users) — تحدّد شكل بيانات الطلبات
والردود لواجهات إدارة المستخدمين (FR-UM-001 → FR-UM-006, FR-UM-011 →
FR-UM-022).

المسؤولية:
- التحقق من صحة المدخلات عند الإنشاء/التعديل، بما فيها سياسة كلمة المرور.
- ضمان عدم إرجاع password_hash أبدًا للعميل (UserOut لا يحتوي هذا الحقل).
- منع العميل من تمرير role أو dep_id بشكل يتجاوز صلاحياته — التحقق الفعلي
  من الصلاحية يتم في طبقة RBAC (core/dependencies.py) وخدمة المستخدمين،
  وليس هنا؛ هذا الملف مسؤول فقط عن شكل البيانات (Data Shape).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import validate_password_policy
from app.models.user import UserStatus
from app.schemas.department import DepartmentOut
from app.schemas.role import RoleSummaryOut


class UserCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role_id: uuid.UUID
    dep_id: uuid.UUID | None = None
    status: UserStatus = UserStatus.active

    @field_validator("password")
    @classmethod
    def _check_password_policy(cls, v: str) -> str:
        # FR-UM-015: 8 أحرف فأكثر + حرف كبير + حرف صغير + رقم
        if not validate_password_policy(v):
            raise ValueError(
                "كلمة المرور يجب أن تحتوي على 8 أحرف على الأقل، "
                "حرف كبير وحرف صغير ورقم واحد على الأقل"
            )
        return v


class UserUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    role_id: uuid.UUID | None = None
    dep_id: uuid.UUID | None = None


class UserOut(BaseModel):
    """
    شكل بيانات المستخدم المُرجَعة للعميل — تتضمّن بيانات إدارته كاملة
    (اسم + وصف) مضمَّنة مباشرة (department)، وليس مجرد dep_id، لتجنّب
    الحاجة لطلب منفصل لصفحة الإدارات فقط لمعرفة اسمها (قرار موثّق: بيانات
    الإدارة تظهر كجزء من بيانات المستخدم نفسه).
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    first_name: str
    middle_name: str
    last_name: str
    username: str
    email: str
    role: RoleSummaryOut
    dep_id: uuid.UUID | None
    department: DepartmentOut | None = None
    status: UserStatus
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserDetailOut(UserOut):
    """
    تفاصيل عضو مفصّلة — تُستخدم في نافذة/صفحة تفاصيل العضو، وتضيف قائمة
    الصلاحيات الفعلية المرتبطة بدوره (محسوبة من role_permissions).
    """

    permissions: list[str] = Field(default_factory=list)


# app.schemas.department.DepartmentDetailOut يشير إلى "UserOut" كـ Forward
# Reference (لتفادي Circular Import بين الملفين) — يُحل هنا بعد أن يصبح
# UserOut معرَّفًا فعليًا في هذا الموديول.
from app.schemas.department import DepartmentDetailOut  # noqa: E402

DepartmentDetailOut.model_rebuild(_types_namespace={"UserOut": UserOut})


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_password_policy(cls, v: str) -> str:
        if not validate_password_policy(v):
            raise ValueError(
                "كلمة المرور يجب أن تحتوي على 8 أحرف على الأقل، "
                "حرف كبير وحرف صغير ورقم واحد على الأقل"
            )
        return v
