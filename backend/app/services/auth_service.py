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

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import TypeVar

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis_client import (
    create_session,
    invalidate_all_user_sessions,
    invalidate_session,
    redis_client,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User, UserStatus
from app.services import audit_service, user_service


T = TypeVar("T")


class AuthError(Exception):
    """خطأ مصادقة عام (بيانات خاطئة، حساب مقفل، حساب موقوف...)."""


async def authenticate(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    before_commit: Callable[[User], Awaitable[T]] | None = None,
) -> tuple[User, str, str, T | None]:
    """
    محاولة تسجيل دخول. عند النجاح تُرجع (المستخدم، access_token،
    refresh_token، ناتج before_commit). عند الفشل تُرجع AuthError برسالة
    عامة موحّدة.

    before_commit (اختياري): دالة قراءة تُنفَّذ داخل معاملة الدخول نفسها
    قبل commit (مثل بناء الملف الشخصي لرد الدخول) — لا يجوز أن تعدّل أي
    بيانات، فهي للقراءة فقط.
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

    if not await asyncio.to_thread(verify_password, password, user.password_hash):
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
    # بدون db.refresh(user) هنا (تحسين أداء 2026-10-24): القيم المحدَّثة
    # موجودة أصلًا بالكائن (expire_on_commit=False)، والـrefresh كان يحجز
    # اتصالًا جديدًا من الـpool (pre-ping) ويعيد تحميل المستخدم ودوره وكل
    # صلاحياته (4 استعلامات) رغم أن الاستجابة لا تحتاج منها شيئًا.

    # تحسين أداء 2026-10-28 (تسجيل الدخول):
    # - before_commit (بيانات الملف الشخصي لرد الدخول) يُنفَّذ داخل نفس
    #   المعاملة بدل معاملة قراءة ثانية بعد commit — توفير BEGIN/ROLLBACK.
    # - إنشاء الجلسة في Redis يتم بالتوازي مع commit بدل بعده. لو فشل commit
    #   يُرفع الخطأ كالسابق ولا تُصدَر أي توكنات؛ مفتاح الجلسة اليتيم ينتهي
    #   وحده بعد مدة الخمول (لا يمكن استخدامه بلا توكن موقَّع يحمل معرّفه).
    extra = await before_commit(user) if before_commit is not None else None
    session_id, _ = await asyncio.gather(create_session(user.user_id), db.commit())
    access_token = create_access_token(
        user.user_id, user.role.name if user.role else None, session_id
    )
    refresh_token = create_refresh_token(user.user_id, session_id)

    return user, access_token, refresh_token, extra


async def logout(session_id: str) -> None:
    """تسجيل الخروج — إبطال الجلسة فورًا في Redis."""
    await invalidate_session(session_id)


# --- نسيت كلمة المرور (FR-UM-018) ---------------------------------------
# تحديث 2026-10-31 (قرارات لاما): إرسال الرمز فعليًا بالبريد (طبقة الـAPI)،
# حد أقصى للمحاولات الخاطئة لكل رمز، مهلة بين طلبين لنفس البريد، خطوة
# تحقق مستقلة قبل تعيين كلمة المرور، إبطال كل جلسات المستخدم بعد الاستعادة،
# الحساب المقفل مؤقتًا يقدر يستعيد (ويُفك قفله)، والموقوف لا (بصمت).

# رسالة واحدة لكل حالات الفشل (بريد غير موجود/حساب موقوف/لا يوجد رمز/رمز
# منتهٍ/خاطئ/تجاوز المحاولات) — حتى لا تكشف الاستجابة أي شيء عن الحساب.
_RESET_GENERIC_ERROR = "رمز التحقق غير صحيح أو منتهي الصلاحية — اطلب رمزًا جديدًا إن تكرر الخطأ"

_RESET_COOLDOWN_KEY_PREFIX = "pwreset:cooldown:"
_RESET_ATTEMPTS_KEY_PREFIX = "pwreset:attempts:"

# hash ثابت لرمز وهمي — يُستخدم لموازنة زمن الاستجابة حين لا يوجد مستخدم/رمز،
# حتى لا يكشف فرق التوقيت (bcrypt بطيء عمدًا) وجود البريد من عدمه.
_DUMMY_OTP_HASH = hash_password("000000")


def _reset_attempts_key(token: PasswordResetToken) -> str:
    return f"{_RESET_ATTEMPTS_KEY_PREFIX}{token.token_id}"


async def request_password_reset(db: AsyncSession, *, email: str) -> tuple[User, str] | None:
    """
    الهدف:
    بدء تدفق نسيت كلمة المرور — FR-UM-018.

    المسؤولية:
    - فرض مهلة PASSWORD_RESET_RESEND_SECONDS بين طلبين لنفس البريد (Redis
      SET NX) — الطلب المتكرر داخل المهلة يُتجاهل بصمت.
    - إبطال أي رمز سابق غير مستخدم لنفس المستخدم (رمز فعّال واحد فقط).
    - توليد رمز OTP من 6 أرقام (secrets) وتخزين hash له فقط.

    المدخلات:
    - db: جلسة قاعدة البيانات.
    - email: str — البريد المُدخل (غير حساس لحالة الأحرف).

    المخرجات:
    - (user, otp_code) ليُرسَل الرمز الصريح بالبريد من طبقة الـAPI.
    - None: بريد غير مسجّل، أو حساب موقوف (suspended)، أو داخل مهلة إعادة
      الإرسال — بدون رفع خطأ، لمنع تعداد عناوين البريد (Email Enumeration).

    التأثيرات الجانبية:
    يكتب بقاعدة البيانات (password_reset_tokens) ومفتاح مهلة في Redis.

    ملاحظة: الحساب المقفل مؤقتًا (FR-UM-019) مسموح له — الاستعادة تفك القفل.
    """
    normalized_email = email.strip().lower()
    is_first_request = await redis_client.set(
        f"{_RESET_COOLDOWN_KEY_PREFIX}{normalized_email}",
        "1",
        ex=settings.PASSWORD_RESET_RESEND_SECONDS,
        nx=True,
    )
    if not is_first_request:
        return None

    user = await user_service.get_user_by_email(db, normalized_email)
    otp_code = f"{secrets.randbelow(1_000_000):06d}"
    # يُحسب الـhash دائمًا (حتى بدون مستخدم) لتوحيد زمن الاستجابة.
    otp_code_hash = await asyncio.to_thread(hash_password, otp_code)

    if user is None or user.status == UserStatus.suspended:
        return None

    now = datetime.now(timezone.utc)
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.user_id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    db.add(
        PasswordResetToken(
            user_id=user.user_id,
            otp_code_hash=otp_code_hash,
            expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_OTP_MINUTES),
        )
    )
    await db.commit()

    return user, otp_code


async def _check_reset_code(
    db: AsyncSession, *, email: str, otp_code: str
) -> tuple[User, PasswordResetToken]:
    """
    الهدف:
    التحقق من رمز الاستعادة — مشتركة بين خطوة التحقق وخطوة تعيين كلمة المرور.

    المسؤولية:
    - رفض البريد غير الموجود/الحساب الموقوف/عدم وجود رمز فعّال/رمز منتهٍ.
    - حد المحاولات: عدّاد ذرّي (Redis INCR) لكل رمز يُزاد *قبل* التحقق —
      حتى مع طلبات متوازية لا يمر أكثر من PASSWORD_RESET_MAX_ATTEMPTS تخمينًا
      خاطئًا. عند تجاوز الحد يُبطَل الرمز نهائيًا (used_at) ويجب طلب رمز جديد.
      المحاولة الصحيحة تُرجِع العدّاد (DECR) فلا تُحتسب — لأن نفس الرمز
      الصحيح يُرسل مرتين (خطوة التحقق ثم خطوة التعيين).

    المدخلات: email، otp_code.
    المخرجات: (user, token) عند النجاح.
    الأخطاء: AuthError برسالة عامة موحّدة لكل حالات الفشل.
    التأثيرات الجانبية: عدّاد Redis، وقد يكتب used_at عند تجاوز الحد.
    """
    user = await user_service.get_user_by_email(db, email.strip().lower())
    token: PasswordResetToken | None = None
    if user is not None and user.status != UserStatus.suspended:
        result = await db.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.user_id == user.user_id, PasswordResetToken.used_at.is_(None))
            .order_by(PasswordResetToken.created_at.desc())
            .limit(1)
        )
        token = result.scalars().first()

    if user is None or token is None or token.is_expired:
        await asyncio.to_thread(verify_password, otp_code, _DUMMY_OTP_HASH)
        raise AuthError(_RESET_GENERIC_ERROR)

    attempts_key = _reset_attempts_key(token)
    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.incr(attempts_key)
        pipe.expire(attempts_key, timedelta(minutes=settings.PASSWORD_RESET_OTP_MINUTES))
        attempts, _ = await pipe.execute()

    if attempts > settings.PASSWORD_RESET_MAX_ATTEMPTS:
        token.used_at = datetime.now(timezone.utc)
        await db.commit()
        raise AuthError(_RESET_GENERIC_ERROR)

    if not await asyncio.to_thread(verify_password, otp_code, token.otp_code_hash):
        if attempts >= settings.PASSWORD_RESET_MAX_ATTEMPTS:
            # آخر محاولة مسموحة وفشلت — إبطال فوري بدل انتظار محاولة إضافية.
            token.used_at = datetime.now(timezone.utc)
            await db.commit()
        raise AuthError(_RESET_GENERIC_ERROR)

    await redis_client.decr(attempts_key)
    return user, token


async def verify_reset_code(db: AsyncSession, *, email: str, otp_code: str) -> None:
    """
    الهدف:
    خطوة تحقق مستقلة من رمز الاستعادة قبل عرض خانات كلمة المرور الجديدة
    (قرار لاما 2026-10-31). لا تستهلك الرمز — يبقى صالحًا لخطوة التعيين.

    المدخلات: email، otp_code. المخرجات: None.
    الأخطاء: AuthError (رسالة عامة) — تُحتسب المحاولة الخاطئة ضمن الحد.
    """
    await _check_reset_code(db, email=email, otp_code=otp_code)


async def reset_password(
    db: AsyncSession, *, email: str, otp_code: str, new_password: str
) -> None:
    """
    الهدف:
    تعيين كلمة مرور جديدة بعد التحقق من رمز الاستعادة — FR-UM-018.

    المسؤولية:
    - إعادة التحقق من الرمز (لا ثقة بأن العميل مرّ بخطوة التحقق فعلًا).
    - تعيين كلمة المرور (bcrypt) وإلغاء must_change_password.
    - فك قفل الحساب المؤقت (FR-UM-019) — من يثبت ملكية البريد يستعيد حسابه.
    - استهلاك الرمز (used_at) وتسجيل العملية في audit_logs.
    - بعد الـcommit: إبطال كل جلسات المستخدم على كل الأجهزة.

    المدخلات: email، otp_code، new_password (سياسة كلمة المرور مُطبَّقة
    مسبقًا بطبقة الـSchema).
    الأخطاء: AuthError برسالة عامة عند فشل التحقق.
    التأثيرات الجانبية: يكتب users/password_reset_tokens/audit_logs، ويحذف
    جلسات المستخدم من Redis.
    """
    user, token = await _check_reset_code(db, email=email, otp_code=otp_code)

    user.password_hash = await asyncio.to_thread(hash_password, new_password)
    user.must_change_password = False
    user.failed_login_attempts = 0
    user.locked_until = None
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

    await redis_client.delete(_reset_attempts_key(token))
    await invalidate_all_user_sessions(user.user_id)


async def change_password(
    db: AsyncSession, *, user: User, current_password: str, new_password: str
) -> None:
    """تغيير كلمة المرور من داخل الحساب (يتطلب معرفة كلمة المرور الحالية)."""
    if not await asyncio.to_thread(verify_password, current_password, user.password_hash):
        raise AuthError("كلمة المرور الحالية غير صحيحة")

    user.password_hash = await asyncio.to_thread(hash_password, new_password)
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
