"""
الهدف:
Pydantic Schemas الخاصة بالمصادقة (Authentication) — تسجيل الدخول، تجديد
التوكن، ونسيت كلمة المرور (FR-UM-011 → FR-UM-020).
"""

from pydantic import BaseModel, EmailStr, Field

from app.core.security import validate_password_policy
from pydantic import field_validator


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp_code: str = Field(min_length=4, max_length=10)
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
