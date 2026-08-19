"""
الهدف:
تجميع كل منطق الأمان الحساس (تشفير كلمات المرور، توليد/التحقق من JWT،
التحقق من سياسة كلمة المرور) في مكان واحد، بدل تكراره داخل الخدمات.

المسؤولية:
- تشفير والتحقق من كلمات المرور عبر bcrypt (لا يُخزَّن أي نص صريح أبدًا).
- توليد والتحقق من Access/Refresh JWT Tokens.
- التحقق من سياسة كلمة المرور (FR-UM-015): 8 أحرف فأكثر، حرف كبير، حرف
  صغير، ورقم واحد على الأقل.

الاعتماديات:
bcrypt لتشفير كلمات المرور، python-jose لتوليد/فك تشفير JWT،
app.core.config لقراءة الإعدادات (JWT_SECRET, الخوارزمية، مدة الصلاحية).

ملاحظات أمنية:
- JWT_SECRET لا يظهر هنا كنص صريح — يُقرأ فقط من settings (متغيرات بيئة).
- التوكن يحمل "type" (access/refresh) لمنع استخدام Refresh Token كأنه
  Access Token والعكس.
- لا يوجد أي منطق RBAC هنا عمدًا — هذا الملف مسؤول فقط عن الهوية
  (Authentication)، أما التفويض (Authorization/RBAC) ففي core/dependencies.py.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

# =====================================================================
# كلمات المرور (Hashing)
# =====================================================================


def hash_password(plain_password: str) -> str:
    """تشفير كلمة مرور نصية عبر bcrypt وإرجاع الـ hash كنص جاهز للتخزين."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """التحقق من تطابق كلمة مرور نصية مع hash مخزَّن مسبقًا."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except ValueError:
        # hash تالف أو بصيغة غير صالحة — يُعامَل كعدم تطابق، وليس كخطأ نظام
        return False


# سياسة كلمة المرور — FR-UM-015: 8 أحرف على الأقل، حرف كبير، حرف صغير، رقم
_PASSWORD_POLICY_RE = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$"
)


def validate_password_policy(plain_password: str) -> bool:
    """
    التحقق من أن كلمة المرور تطابق السياسة الإلزامية (FR-UM-015):
    8 أحرف فأكثر + حرف كبير واحد على الأقل + حرف صغير واحد على الأقل +
    رقم واحد على الأقل.
    """
    return bool(_PASSWORD_POLICY_RE.match(plain_password))


# =====================================================================
# JWT (Access / Refresh Tokens)
# =====================================================================

TokenType = Literal["access", "refresh"]


def _create_token(
    subject: UUID,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """دالة داخلية مشتركة لبناء وتوقيع أي JWT (access أو refresh)."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: UUID, role: str, session_id: str) -> str:
    """
    توليد Access Token قصير المدى.

    يحمل الدور (role) و session_id داخل التوكن نفسه بشكل مقروء فقط
    للتسهيل على الواجهة الأمامية (عرض/توجيه) — لكن هذا لا يُعتمد عليه أبدًا
    لفرض الصلاحيات؛ RBAC الفعلي يتحقق من قاعدة البيانات في كل طلب
    (قاعدة "لا تثق بأي بيانات دور/هوية قادمة من العميل" في CLAUDE.md).
    """
    return _create_token(
        subject=user_id,
        token_type="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        extra_claims={"role": role, "sid": session_id},
    )


def create_refresh_token(user_id: UUID, session_id: str) -> str:
    """توليد Refresh Token طويل المدى، يُستخدم فقط لإصدار Access Token جديد."""
    return _create_token(
        subject=user_id,
        token_type="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        extra_claims={"sid": session_id},
    )


class InvalidTokenError(Exception):
    """يُرفع عند فشل فك تشفير/التحقق من التوكن، أو عدم تطابق النوع المتوقع."""


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """
    فك تشفير والتحقق من صلاحية توكن JWT، مع التأكد من أن نوعه (access/refresh)
    يطابق المتوقع. يرفع InvalidTokenError عند أي مشكلة (توقيع، انتهاء صلاحية،
    نوع خاطئ) بدل تسريب تفاصيل جوز مكتبة jose للطبقات الأعلى.
    """
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as exc:
        raise InvalidTokenError("Token invalid or expired") from exc

    if payload.get("type") != expected_type:
        raise InvalidTokenError(f"Expected a '{expected_type}' token")

    return payload
