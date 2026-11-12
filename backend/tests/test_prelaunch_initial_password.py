"""
الهدف:
اختبارات كلمة المرور الأولية قبل التدشين (طلب الإدارة 2026-11-12) —
متغير البيئة PRELAUNCH_INITIAL_PASSWORD:

- مفعّل (مثل 123456): نموذج إضافة مستخدم يقبل هذه الكلمة بالضبط (ويبقى يقبل
  الكلمات القوية)، ورفع ملف Excel يعطيها لكل المستوردين، والحساب يُجبَر على
  تغييرها عند أول دخول.
- تغيير كلمة المرور عند أول دخول ونسيت كلمة المرور: السياسة الكاملة دائمًا،
  حتى والوضع مفعّل.
- فارغ (الافتراضي): لا تغيير إطلاقًا عن السلوك السابق.
- GET /users/initial-password-policy: يتطلب users.create، ولا يكشف القيمة.

البريد لا يُرسل فعليًا — notify_imported_users_credentials مُستبدَلة.
"""

import asyncio
import io
import uuid

import pytest
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import select

from app.core import background
from app.core.config import settings
from app.core.security import hash_password, is_prelaunch_initial_password
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.models.user_role import UserRole
from app.services import notification_service
from app.services.user_import_service import TEMPLATE_HEADERS

USERS = "/api/v1/users"
POLICY = "/api/v1/users/initial-password-policy"
IMPORT = "/api/v1/users/import"
LOGIN = "/api/v1/auth/login"
CHANGE = "/api/v1/auth/change-password"
RESET = "/api/v1/auth/reset-password"
PRELAUNCH = "123456"


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """يلتقط (البريد، الاسم، اسم المستخدم، كلمة المرور) بدل إرسال البريد فعليًا."""
    captured: list[tuple] = []

    async def fake_notify(accounts, *, login_url):
        captured.extend(accounts)

    monkeypatch.setattr(notification_service, "notify_imported_users_credentials", fake_notify)
    return captured


@pytest.fixture
def prelaunch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """يفعّل وضع ما قبل التدشين لهذا الاختبار فقط (كأنه مضبوط على Render)."""
    monkeypatch.setattr(settings, "PRELAUNCH_INITIAL_PASSWORD", PRELAUNCH)


async def _flush_background() -> None:
    pending = list(background._pending_tasks)
    if pending:
        await asyncio.wait(pending, timeout=10)


def _user_payload(username: str, password: str) -> dict:
    return {
        "first_name": "سارة",
        "middle_name": "محمد",
        "last_name": "العتيبي",
        "username": username,
        "email": f"{username}@example.com",
        "password": password,
        "dep_id": None,
    }


async def _login(client: AsyncClient, username: str, password: str):
    return await client.post(LOGIN, json={"username": username, "password": password})


async def _login_with_role(client: AsyncClient, auth_headers, *, codes: list[str], scopes: dict[str, str]) -> dict:
    role = await client.post(
        "/api/v1/roles",
        json={"name": f"دور {uuid.uuid4().hex[:6]}", "permission_codes": codes, "permission_scopes": scopes},
        headers=auth_headers,
    )
    assert role.status_code == 201, role.text
    username = f"tester_{uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        user = User(
            first_name="م", middle_name="س", last_name="ت", username=username, email=f"{username}@example.com",
            password_hash=hash_password("StrongPass1"), role_id=role.json()["role_id"],
        )
        db.add(user)
        await db.flush()
        db.add(UserRole(user_id=user.user_id, role_id=user.role_id))
        await db.commit()
    login = await _login(client, username, "StrongPass1")
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _xlsx(rows: list[list[str | None]]) -> bytes:
    workbook = Workbook()
    ws = workbook.active
    ws.title = "المستخدمين"
    ws.append(TEMPLATE_HEADERS)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def _upload(client: AsyncClient, headers: dict, content: bytes):
    return await client.post(
        IMPORT,
        files={"file": ("users.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )


# ---------------------------------------------------------------- الدالة المساعدة


def test_helper_off_by_default() -> None:
    assert settings.PRELAUNCH_INITIAL_PASSWORD == ""
    assert is_prelaunch_initial_password("") is False
    assert is_prelaunch_initial_password(PRELAUNCH) is False


def test_helper_exact_match_and_trims_configured_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PRELAUNCH_INITIAL_PASSWORD", " 123456 ")  # مسافة بالخطأ بـRender
    assert is_prelaunch_initial_password("123456") is True
    assert is_prelaunch_initial_password("12345") is False
    assert is_prelaunch_initial_password("1234567") is False
    assert is_prelaunch_initial_password(" 123456") is False


# ---------------------------------------------------------------- نقطة حالة الوضع


async def test_policy_endpoint_enforced_by_default(client: AsyncClient, auth_headers) -> None:
    response = await client.get(POLICY, headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"rules_enforced": True}


async def test_policy_endpoint_relaxed_when_on_without_leaking_value(
    client: AsyncClient, auth_headers, prelaunch_on
) -> None:
    response = await client.get(POLICY, headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"rules_enforced": False}
    assert PRELAUNCH not in response.text


async def test_policy_endpoint_requires_users_create(client: AsyncClient, auth_headers, prelaunch_on) -> None:
    viewer = await _login_with_role(client, auth_headers, codes=["users.view"], scopes={"users.view": "all"})
    assert (await client.get(POLICY, headers=viewer)).status_code == 403
    assert (await client.get(POLICY)).status_code == 401

    creator = await _login_with_role(client, auth_headers, codes=["users.create"], scopes={"users.create": "all"})
    assert (await client.get(POLICY, headers=creator)).json() == {"rules_enforced": False}


# ---------------------------------------------------------------- إضافة مستخدم يدويًا


async def test_create_rejects_prelaunch_password_when_off(client: AsyncClient, auth_headers, sent) -> None:
    response = await client.post(USERS, json=_user_payload("off_user", PRELAUNCH), headers=auth_headers)
    assert response.status_code == 422


async def test_create_accepts_prelaunch_password_and_forces_change(
    client: AsyncClient, auth_headers, sent, prelaunch_on
) -> None:
    response = await client.post(USERS, json=_user_payload("on_user", PRELAUNCH), headers=auth_headers)
    assert response.status_code == 201, response.text
    assert response.json()["must_change_password"] is True
    assert PRELAUNCH not in response.text

    login = await _login(client, "on_user", PRELAUNCH)
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True


async def test_create_when_on_accepts_only_exact_value_or_strong_password(
    client: AsyncClient, auth_headers, sent, prelaunch_on
) -> None:
    for i, weak in enumerate(["12345", "1234567", "abcdef", " 123456"]):
        response = await client.post(USERS, json=_user_payload(f"weak_{i}", weak), headers=auth_headers)
        assert response.status_code == 422, weak
        # نفس رسالة السياسة المعتادة — لا تلمّح لكلمة ما قبل التدشين
        # (نفحص msg فقط: FastAPI يعيد ما كتبه المستخدم نفسه بحقل input).
        messages = " ".join(d["msg"] for d in response.json()["detail"])
        assert "8 أحرف على الأقل" in messages and PRELAUNCH not in messages

    strong = await client.post(USERS, json=_user_payload("strong_user", "StrongPass1"), headers=auth_headers)
    assert strong.status_code == 201, strong.text


# ---------------------------------------------------------------- رفع ملف Excel


async def test_import_gives_everyone_prelaunch_password(client: AsyncClient, auth_headers, sent, prelaunch_on) -> None:
    content = _xlsx(
        [
            ["خالد", "علي", "الحربي", "khalid@example.com", None, None, None],
            ["نورة", "سعد", "القحطاني", "noura@example.com", None, None, None],
        ]
    )
    response = await _upload(client, auth_headers, content)
    assert response.status_code == 201, response.text
    assert PRELAUNCH not in response.text  # لا كلمات مرور بالاستجابة

    await _flush_background()
    assert sorted(password for *_, password in sent) == [PRELAUNCH, PRELAUNCH]

    async with AsyncSessionLocal() as db:
        users = (
            await db.execute(select(User).where(User.email.in_(["khalid@example.com", "noura@example.com"])))
        ).scalars().all()
    assert len(users) == 2 and all(u.must_change_password for u in users)

    username = next(u for e, _, u, _ in sent if e == "khalid@example.com")
    login = await _login(client, username, PRELAUNCH)
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True


async def test_import_uses_random_password_when_off(client: AsyncClient, auth_headers, sent) -> None:
    response = await _upload(client, auth_headers, _xlsx([["خالد", "علي", "الحربي", "k2@example.com", None, None, None]]))
    assert response.status_code == 201, response.text
    await _flush_background()
    [(_, _, _, password)] = sent
    assert password != PRELAUNCH and len(password) == 12


# ---------------------------------------------------------------- تبقى السياسة كاملة


async def test_first_login_change_still_requires_full_rules(
    client: AsyncClient, auth_headers, sent, prelaunch_on
) -> None:
    created = await client.post(USERS, json=_user_payload("first_login", PRELAUNCH), headers=auth_headers)
    assert created.status_code == 201, created.text
    token = (await _login(client, "first_login", PRELAUNCH)).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    for weak in [PRELAUNCH, "abcdefgh", "Abcdefgh", "abcdefg1"]:
        response = await client.post(
            CHANGE, json={"current_password": PRELAUNCH, "new_password": weak}, headers=headers
        )
        assert response.status_code == 422, weak

    ok = await client.post(CHANGE, json={"current_password": PRELAUNCH, "new_password": "NewStrong1"}, headers=headers)
    assert ok.status_code == 204, ok.text
    assert (await _login(client, "first_login", PRELAUNCH)).status_code == 401
    after = await _login(client, "first_login", "NewStrong1")
    assert after.status_code == 200 and after.json()["must_change_password"] is False


async def test_forgot_password_reset_still_requires_full_rules(client: AsyncClient, prelaunch_on) -> None:
    response = await client.post(
        RESET, json={"email": "anyone@example.com", "otp_code": "123456", "new_password": PRELAUNCH}
    )
    assert response.status_code == 422
