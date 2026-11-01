"""
الهدف:
Pydantic Schemas الخاصة بالمصادقة (Authentication) — تسجيل الدخول، تجديد
التوكن، ونسيت كلمة المرور (FR-UM-011 → FR-UM-020).
"""

from pydantic import BaseModel, EmailStr, Field

from app.core.security import validate_password_policy
from app.schemas.user import UserDetailOut
from pydantic import field_validator


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    must_change_password: bool = False
    # تحسين أداء 2026-10-25: رد تسجيل الدخول فقط يتضمن بيانات المستخدم بنفس
    # شكل GET /users/me — يوفّر على الواجهة طلبًا متتابعًا كاملًا بعد الدخول.
    # حقل إضافي اختياري: /auth/refresh يرجعه None، وأي عميل قديم يتجاهله.
    user: UserDetailOut | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


# رمز الاستعادة = 6 أرقام بالضبط (يولّده auth_service.request_password_reset).
_OTP_PATTERN = r"^\d{6}$"


class VerifyResetCodeRequest(BaseModel):
    """
    الهدف: جسم طلب POST /auth/verify-reset-code — التحقق من رمز الاستعادة
    كخطوة مستقلة قبل إدخال كلمة المرور الجديدة (FR-UM-018).
    """

    email: EmailStr
    otp_code: str = Field(pattern=_OTP_PATTERN)


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp_code: str = Field(pattern=_OTP_PATTERN)
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
