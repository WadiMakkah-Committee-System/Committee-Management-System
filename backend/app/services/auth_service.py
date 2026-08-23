"""
الهدف:
منطق العمل الخاص بالمصادقة (تسجيل الدخول/الخروج، تجديد التوكن، نسيت كلمة
المرور) — FR-UM-011 → FR-UM-020.

المسؤولية:
- تسجيل الدخول مع فرض سياسة قفل الحساب بعد محاولات فاشلة متكررة
  (FR-UM-019: 5 محاولات → قفل 15 دقيقة).
- إصدار Access/Refresh Tokens + إنشاء جلسة في Redis.
- تجديد Access Token عبر Refresh Token صالح.
- تسجيل الخروج (إبطال الجلسة في Redis).
- تدفق نسيت كلمة المرور عبر OTP (FR-UM-018).

ملاحظات أمنية:
- لا تُكشف تفاصيل عن سبب فشل الدخول (مستخدم غير موجود VS كلمة مرور خاطئة)
  للعميل — نفس رسالة الخطأ العامة في الحالتين، لمنع تعداد أسماء المستخدمين
  (User Enumeration).
- كل محاولة دخول فاشلة/ناجحة تُسجَّل في audit_logs.
"""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis_client import create_session, invalidate_session
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User, UserStatus
from app.services import audit_service, user_service


class AuthError(Exception):
    """خطأ مصادقة عام (بيانات خاطئة، حساب مقفل، حساب موقوف...)."""


async def authenticate(
    db: AsyncSession, *, username: str, password: str
) -> tuple[User, str, str]:
    """
    محاولة تسجيل دخول. عند النجاح تُرجع (المستخدم، access_token،
    refresh_token). عند الفشل تُرجع AuthError برسالة عامة موحّدة.
    """
    user = await user_service.get_user_by_username(db, username)

    generic_error = AuthError("اسم المستخدم أو كلمة المرور غير صحيحة")

    if user is None:
        raise generic_error

    if user.is_locked:
        raise AuthError(
            "الحساب مقفل مؤقتًا بسبب محاولات دخول فاشلة متكررة، حاول لاحقًا"
        )

    if user.status == UserStatus.suspended:
        raise AuthError("الحساب موقوف — تواصل مع مسؤول النظام")

    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.ACCOUNT_LOCKOUT_MINUTES
            )
            user.failed_login_attempts = 0

        await audit_service.log_action(
            db,
            actor_user_id=user.user_id,
            action_type="update",
            target_type="user",
            target_id=user.user_id,
            metadata={"event": "login_failed"},
        )
        await db.commit()
        raise generic_error

    # نجاح تسجيل الدخول: إعادة تصفير عداد المحاولات الفاشلة
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)

    await audit_service.log_action(
        db,
        actor_user_id=user.user_id,
        action_type="update",
        target_type="user",
        target_id=user.user_id,
        metadata={"event": "login_success"},
    )
    await db.commit()
    await db.refresh(user)

    session_id = await create_session(user.user_id)
    access_token = create_access_token(user.user_id, user.role.name, session_id)
    refresh_token = create_refresh_token(user.user_id, session_id)

    return user, access_token, refresh_token


async def logout(session_id: str) -> None:
    """تسجيل الخروج — إبطال الجلسة فورًا في Redis."""
    await invalidate_session(session_id)


async def request_password_reset(db: AsyncSession, *, email: str) -> str | None:
    """
    بدء تدفق نسيت كلمة المرور — FR-UM-018. تُنشئ رمز OTP (6 أرقام)، تُخزّن
    hash له فقط، وتُرجع الرمز الصريح ليُرسَل عبر البريد (إرسال البريد
    الفعلي مسؤولية طبقة أعلى/مهمة لاحقة — هنا فقط توليد وتخزين الرمز).

    ترجع None إذا لم يوجد مستخدم بهذا البريد، لكن دون رفع خطأ — لمنع
    تعداد عناوين البريد المسجَّلة (Email Enumeration) من طرف مهاجم.
    """
    user = await user_service.get_user_by_email(db, email)
    if user is None:
        return None

    otp_code = f"{secrets.randbelow(1_000_000):06d}"
    token = PasswordResetToken(
        user_id=user.user_id,
        otp_code_hash=hash_password(otp_code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    db.add(token)
    await db.commit()

    return otp_code


async def reset_password(
    db: AsyncSession, *, email: str, otp_code: str, new_password: str
) -> None:
    """التحقق من رمز OTP وتعيين كلمة مرور جديدة. يرفع AuthError عند الفشل."""
    from sqlalchemy import select

    user = await user_service.get_user_by_email(db, email)
    if user is None:
        raise AuthError("رمز التحقق غير صحيح أو منتهي الصلاحية")

    result = await db.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.user_id, PasswordResetToken.used_at.is_(None))
        .order_by(PasswordResetToken.created_at.desc())
    )
    token = result.scalars().first()

    if token is None or token.is_expired or not verify_password(otp_code, token.otp_code_hash):
        raise AuthError("رمز التحقق غير صحيح أو منتهي الصلاحية")

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    token.used_at = datetime.now(timezone.utc)

    await audit_service.log_action(
        db,
        actor_user_id=user.user_id,
        action_type="update",
        target_type="user",
        target_id=user.user_id,
        metadata={"event": "password_reset"},
    )

    await db.commit()


async def change_password(
    db: AsyncSession, *, user: User, current_password: str, new_password: str
) -> None:
    """تغيير كلمة المرور من داخل الحساب (يتطلب معرفة كلمة المرور الحالية)."""
    if not verify_password(current_password, user.password_hash):
        raise AuthError("كلمة المرور الحالية غير صحيحة")

    user.password_hash = hash_password(new_password)
    user.must_change_password = False

    await audit_service.log_action(
        db,
        actor_user_id=user.user_id,
        action_type="update",
        target_type="user",
        target_id=user.user_id,
        metadata={"event": "password_changed"},
    )

    await db.commit()
