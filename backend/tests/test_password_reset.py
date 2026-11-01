"""
الهدف:
اختبارات تدفق نسيت كلمة المرور عبر OTP بالبريد — FR-UM-018 (تحديث
2026-10-31): إرسال الرمز، منع تعداد البريد، مهلة إعادة الإرسال، خطوة
التحقق المستقلة، حد المحاولات، انتهاء الصلاحية، إبطال الجلسات بعد
الاستعادة، فك قفل الحساب المؤقت، ورفض الحساب الموقوف.

ملاحظة: البريد لا يُرسل فعليًا — notify_password_reset_code مُستبدَلة
بدالة تلتقط الرمز (fixture sent_codes)، ومفاتيح pwreset:* تُمسح من Redis
قبل كل اختبار (conftest لا يفرّغ Redis).
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core import background
from app.core.config import settings
from app.core.redis_client import redis_client
from app.db.session import AsyncSessionLocal
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User, UserStatus
from app.services import notification_service

EMAIL = "super_admin_test@example.com"
NEW_PASSWORD = "NewStrong1"
FORGOT = "/api/v1/auth/forgot-password"
VERIFY = "/api/v1/auth/verify-reset-code"
RESET = "/api/v1/auth/reset-password"
LOGIN = "/api/v1/auth/login"


@pytest_asyncio.fixture(autouse=True)
async def _clear_reset_keys() -> None:
    """يمسح مفاتيح المهلة والمحاولات من أي اختبار سابق (Redis مشترك)."""
    async for key in redis_client.scan_iter("pwreset:*"):
        await redis_client.delete(key)


@pytest.fixture
def sent_codes(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """يستبدل إرسال بريد الرمز بدالة تلتقط (البريد، الرمز) بدل الإرسال الفعلي."""
    sent: list[dict] = []

    async def fake_notify(*, email: str, first_name: str | None, otp_code: str, expires_minutes: int) -> None:
        sent.append({"email": email, "otp_code": otp_code, "expires_minutes": expires_minutes})

    monkeypatch.setattr(notification_service, "notify_password_reset_code", fake_notify)
    return sent


async def _flush_background() -> None:
    """ينتظر مهام run_detached (إرسال البريد) قبل فحص sent_codes."""
    pending = list(background._pending_tasks)
    if pending:
        import asyncio

        await asyncio.wait(pending, timeout=5)


async def _request_code(client: AsyncClient, sent_codes: list[dict], email: str = EMAIL) -> str:
    response = await client.post(FORGOT, json={"email": email})
    assert response.status_code == 204, response.text
    await _flush_background()
    assert sent_codes, "لم يُرسَل أي رمز"
    return sent_codes[-1]["otp_code"]


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


async def test_forgot_password_sends_code_to_registered_email(
    client: AsyncClient, super_admin_user, sent_codes
) -> None:
    code = await _request_code(client, sent_codes, email="SUPER_ADMIN_TEST@example.com")
    assert len(sent_codes) == 1
    assert sent_codes[0]["email"] == EMAIL
    assert len(code) == 6 and code.isdigit()
    assert sent_codes[0]["expires_minutes"] == settings.PASSWORD_RESET_OTP_MINUTES

    async with AsyncSessionLocal() as db:
        tokens = (await db.execute(select(PasswordResetToken))).scalars().all()
    assert len(tokens) == 1
    assert tokens[0].otp_code_hash != code  # الرمز لا يُخزَّن صريحًا


async def test_forgot_password_unknown_email_same_response_no_email(
    client: AsyncClient, super_admin_user, sent_codes
) -> None:
    response = await client.post(FORGOT, json={"email": "nobody@example.com"})
    assert response.status_code == 204
    await _flush_background()
    assert sent_codes == []


async def test_forgot_password_invalid_email_format(client: AsyncClient, sent_codes) -> None:
    response = await client.post(FORGOT, json={"email": "not-an-email"})
    assert response.status_code == 422


async def test_forgot_password_suspended_user_gets_no_code(
    client: AsyncClient, super_admin_user, sent_codes
) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(User).where(User.user_id == super_admin_user.user_id).values(status=UserStatus.suspended)
        )
        await db.commit()

    response = await client.post(FORGOT, json={"email": EMAIL})
    assert response.status_code == 204
    await _flush_background()
    assert sent_codes == []


async def test_forgot_password_resend_cooldown(client: AsyncClient, super_admin_user, sent_codes) -> None:
    await _request_code(client, sent_codes)
    again = await client.post(FORGOT, json={"email": EMAIL})
    assert again.status_code == 204
    await _flush_background()
    assert len(sent_codes) == 1  # الطلب الثاني داخل المهلة تُجوهل بصمت


async def test_new_request_invalidates_previous_code(client: AsyncClient, super_admin_user, sent_codes) -> None:
    first = await _request_code(client, sent_codes)
    await redis_client.delete(f"pwreset:cooldown:{EMAIL}")  # محاكاة انتهاء المهلة
    second = await _request_code(client, sent_codes)
    assert len(sent_codes) == 2

    if first != second:
        old = await client.post(VERIFY, json={"email": EMAIL, "otp_code": first})
        assert old.status_code == 400
    new = await client.post(VERIFY, json={"email": EMAIL, "otp_code": second})
    assert new.status_code == 204


async def test_full_flow_verify_then_reset(client: AsyncClient, super_admin_user, sent_codes) -> None:
    code = await _request_code(client, sent_codes)

    verify = await client.post(VERIFY, json={"email": EMAIL, "otp_code": code})
    assert verify.status_code == 204
    # التحقق لا يستهلك الرمز — يبقى صالحًا لخطوة التعيين
    reset = await client.post(RESET, json={"email": EMAIL, "otp_code": code, "new_password": NEW_PASSWORD})
    assert reset.status_code == 204, reset.text

    old_login = await client.post(LOGIN, json={"username": "super_admin_test", "password": "StrongPass1"})
    assert old_login.status_code == 401
    new_login = await client.post(LOGIN, json={"username": "super_admin_test", "password": NEW_PASSWORD})
    assert new_login.status_code == 200

    # الرمز يُستخدم مرة واحدة فقط
    reuse = await client.post(RESET, json={"email": EMAIL, "otp_code": code, "new_password": "Another1Pass"})
    assert reuse.status_code == 400


async def test_wrong_code_generic_error(client: AsyncClient, super_admin_user, sent_codes) -> None:
    code = await _request_code(client, sent_codes)
    wrong = await client.post(VERIFY, json={"email": EMAIL, "otp_code": _wrong(code)})
    unknown = await client.post(VERIFY, json={"email": "nobody@example.com", "otp_code": code})
    assert wrong.status_code == unknown.status_code == 400
    assert wrong.json()["detail"] == unknown.json()["detail"]  # لا كشف لوجود البريد


async def test_code_invalidated_after_max_wrong_attempts(
    client: AsyncClient, super_admin_user, sent_codes
) -> None:
    code = await _request_code(client, sent_codes)
    for _ in range(settings.PASSWORD_RESET_MAX_ATTEMPTS):
        r = await client.post(VERIFY, json={"email": EMAIL, "otp_code": _wrong(code)})
        assert r.status_code == 400

    # حتى الرمز الصحيح لم يعد يعمل
    correct = await client.post(VERIFY, json={"email": EMAIL, "otp_code": code})
    assert correct.status_code == 400
    reset = await client.post(RESET, json={"email": EMAIL, "otp_code": code, "new_password": NEW_PASSWORD})
    assert reset.status_code == 400


async def test_successful_attempts_do_not_count_toward_limit(
    client: AsyncClient, super_admin_user, sent_codes
) -> None:
    code = await _request_code(client, sent_codes)
    for _ in range(settings.PASSWORD_RESET_MAX_ATTEMPTS - 1):
        await client.post(VERIFY, json={"email": EMAIL, "otp_code": _wrong(code)})

    assert (await client.post(VERIFY, json={"email": EMAIL, "otp_code": code})).status_code == 204
    reset = await client.post(RESET, json={"email": EMAIL, "otp_code": code, "new_password": NEW_PASSWORD})
    assert reset.status_code == 204


async def test_expired_code_rejected(client: AsyncClient, super_admin_user, sent_codes) -> None:
    code = await _request_code(client, sent_codes)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(PasswordResetToken).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await db.commit()

    response = await client.post(VERIFY, json={"email": EMAIL, "otp_code": code})
    assert response.status_code == 400


async def test_reset_logs_out_all_sessions(client: AsyncClient, super_admin_user, sent_codes) -> None:
    tokens = []
    for _ in range(2):  # جهازين
        login = await client.post(LOGIN, json={"username": "super_admin_test", "password": "StrongPass1"})
        tokens.append(login.json()["access_token"])
    for t in tokens:
        assert (await client.get("/api/v1/departments", headers={"Authorization": f"Bearer {t}"})).status_code == 200

    code = await _request_code(client, sent_codes)
    reset = await client.post(RESET, json={"email": EMAIL, "otp_code": code, "new_password": NEW_PASSWORD})
    assert reset.status_code == 204

    for t in tokens:
        assert (await client.get("/api/v1/departments", headers={"Authorization": f"Bearer {t}"})).status_code == 401


async def test_locked_account_can_reset_and_unlocks(client: AsyncClient, super_admin_user, sent_codes) -> None:
    for _ in range(settings.MAX_FAILED_LOGIN_ATTEMPTS):
        await client.post(LOGIN, json={"username": "super_admin_test", "password": "WrongPass1"})
    locked = await client.post(LOGIN, json={"username": "super_admin_test", "password": "StrongPass1"})
    assert locked.status_code == 401 and "مقفل" in locked.json()["detail"]

    code = await _request_code(client, sent_codes)
    reset = await client.post(RESET, json={"email": EMAIL, "otp_code": code, "new_password": NEW_PASSWORD})
    assert reset.status_code == 204

    login = await client.post(LOGIN, json={"username": "super_admin_test", "password": NEW_PASSWORD})
    assert login.status_code == 200


async def test_suspended_after_request_cannot_reset(client: AsyncClient, super_admin_user, sent_codes) -> None:
    code = await _request_code(client, sent_codes)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(User).where(User.user_id == super_admin_user.user_id).values(status=UserStatus.suspended)
        )
        await db.commit()

    reset = await client.post(RESET, json={"email": EMAIL, "otp_code": code, "new_password": NEW_PASSWORD})
    assert reset.status_code == 400


async def test_reset_rejects_weak_password_and_bad_code_format(
    client: AsyncClient, super_admin_user, sent_codes
) -> None:
    code = await _request_code(client, sent_codes)
    weak = await client.post(RESET, json={"email": EMAIL, "otp_code": code, "new_password": "weakpass"})
    assert weak.status_code == 422
    bad_format = await client.post(VERIFY, json={"email": EMAIL, "otp_code": "12ab"})
    assert bad_format.status_code == 422

    # الرمز ما زال صالحًا (الطلبات المرفوضة بالـValidation لا تُحتسب محاولات)
    assert (await client.post(VERIFY, json={"email": EMAIL, "otp_code": code})).status_code == 204
