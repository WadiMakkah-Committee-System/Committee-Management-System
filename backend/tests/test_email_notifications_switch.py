"""
اختبارات مفتاح إيقاف بريد الإشعارات (طلب لاما 2026-11-12):
EMAIL_NOTIFICATIONS_ENABLED=false يوقف كل البريد ما عدا رمز "نسيت كلمة المرور".
"""

from unittest.mock import AsyncMock

import pytest

from app.core import email_client
from app.core.config import settings
from app.services import notification_service


@pytest.fixture
def smtp_spy(monkeypatch):
    spy = AsyncMock()
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(email_client, "_send_via_smtp", spy)
    return spy


async def test_disabled_blocks_regular_email(monkeypatch, smtp_spy) -> None:
    monkeypatch.setattr(settings, "EMAIL_NOTIFICATIONS_ENABLED", False)
    await email_client.send_email(to=["a@example.com"], subject="s", html_body="<p>x</p>")
    smtp_spy.assert_not_awaited()


async def test_disabled_still_sends_password_reset(monkeypatch, smtp_spy) -> None:
    monkeypatch.setattr(settings, "EMAIL_NOTIFICATIONS_ENABLED", False)
    await notification_service.notify_password_reset_code(
        email="a@example.com", first_name="لمى", otp_code="123456", expires_minutes=10
    )
    smtp_spy.assert_awaited_once()


async def test_disabled_blocks_imported_credentials(monkeypatch, smtp_spy) -> None:
    monkeypatch.setattr(settings, "EMAIL_NOTIFICATIONS_ENABLED", False)
    await notification_service.notify_imported_users_credentials(
        [("a@example.com", "لمى", "lama", "Pass12345!")], login_url=None
    )
    smtp_spy.assert_not_awaited()


async def test_enabled_by_default_sends(monkeypatch, smtp_spy) -> None:
    monkeypatch.setattr(settings, "EMAIL_NOTIFICATIONS_ENABLED", True)
    await email_client.send_email(to=["a@example.com"], subject="s", html_body="<p>x</p>")
    smtp_spy.assert_awaited_once()
