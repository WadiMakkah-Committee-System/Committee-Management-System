"""
اختبارات الدخول بحساب Microsoft 365 (migration 0042 — قرار لاما 2026-11-02).

التوكنات هنا موقّعة بمفتاح RSA مولَّد بالاختبار، ومفاتيح Microsoft العامة
(JWKS) مستبدلة بمفتاحه العام — فنختبر التحقق الحقيقي من التوقيع/المُصدِر/
الجمهور/الصلاحية بدون اتصال شبكة.
"""

import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from jose import jwk, jwt
from sqlalchemy import select

from app.core import microsoft_identity
from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.session import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.user import User, UserStatus

TENANT = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
KID = "test-key-1"

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _private_key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
_PUBLIC_JWK = {
    **jwk.construct(
        _private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode(),
        "RS256",
    ).to_dict(),
    "kid": KID,
    "use": "sig",
}


def _id_token(
    *, oid: str, email: str, tid: str = TENANT, aud: str = CLIENT, exp_in: int = 600, kid: str = KID
) -> str:
    """ID Token بنفس شكل Microsoft v2.0 موقّع بمفتاح الاختبار."""
    now = int(time.time())
    claims = {
        "aud": aud,
        "iss": f"https://login.microsoftonline.com/{tid}/v2.0",
        "iat": now,
        "nbf": now,
        "exp": now + exp_in,
        "oid": oid,
        "tid": tid,
        "preferred_username": email,
        "name": "موظف تجريبي",
    }
    return jwt.encode(claims, _PRIVATE_PEM, algorithm="RS256", headers={"kid": kid})


@pytest.fixture(autouse=True)
def _microsoft_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TEAMS_TENANT_ID", TENANT)
    monkeypatch.setattr(settings, "TEAMS_CLIENT_ID", CLIENT)
    monkeypatch.setattr(settings, "MICROSOFT_LOGIN_DOMAINS", "wadimakkah.sa, @Tilal.sa")
    monkeypatch.setattr(settings, "MICROSOFT_LOGIN_ENABLED", True)

    async def fake_jwks() -> list[dict]:
        return [_PUBLIC_JWK]

    monkeypatch.setattr(microsoft_identity, "_fetch_jwks", fake_jwks)
    monkeypatch.setattr(microsoft_identity, "_jwks_cache", None)


async def _make_user(
    *,
    email: str,
    username: str,
    must_change_password: bool = True,
    status: UserStatus = UserStatus.active,
    microsoft_object_id: uuid.UUID | None = None,
) -> User:
    async with AsyncSessionLocal() as db:
        user = User(
            first_name="موظف",
            middle_name="تجريبي",
            last_name="الشركة",
            username=username,
            email=email,
            password_hash=hash_password("TempPass1"),
            must_change_password=must_change_password,
            status=status,
            microsoft_object_id=microsoft_object_id,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _reload(user_id: uuid.UUID) -> User:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User).where(User.user_id == user_id))).scalar_one()


async def test_login_options_exposes_public_config_only(client: AsyncClient, monkeypatch) -> None:
    body = (await client.get("/api/v1/auth/login-options")).json()
    assert body == {
        "microsoft_enabled": True,
        "microsoft_client_id": CLIENT,
        "microsoft_tenant_id": TENANT,
        "microsoft_domains": ["wadimakkah.sa", "tilal.sa"],
    }
    monkeypatch.setattr(settings, "TEAMS_CLIENT_ID", "")
    assert (await client.get("/api/v1/auth/login-options")).json()["microsoft_enabled"] is False


async def test_microsoft_login_hidden_and_rejected_when_switched_off(client: AsyncClient, monkeypatch) -> None:
    """قرار لاما 2026-11-04: MICROSOFT_LOGIN_ENABLED=false ⇒ مخفي بصفحة الدخول ومرفوض بالباك-إند
    حتى لو مفاتيح Entra موجودة (الكود محفوظ للرجوع)."""
    monkeypatch.setattr(settings, "MICROSOFT_LOGIN_ENABLED", False)
    assert (await client.get("/api/v1/auth/login-options")).json()["microsoft_enabled"] is False
    await _make_user(email="off@wadimakkah.sa", username="off_user")
    response = await client.post(
        "/api/v1/auth/microsoft", json={"id_token": _id_token(oid=str(uuid.uuid4()), email="off@wadimakkah.sa")}
    )
    assert response.status_code == 503


async def test_first_microsoft_login_links_account_and_revokes_temp_password(client: AsyncClient) -> None:
    user = await _make_user(email="L.Alzhrani@wadimakkah.sa", username="lalzhrani")
    oid = str(uuid.uuid4())

    # البريد بحالة أحرف مختلفة عن المسجّل بالمنصة — لازم يطابق.
    response = await client.post(
        "/api/v1/auth/microsoft", json={"id_token": _id_token(oid=oid, email="l.alzhrani@wadimakkah.sa")}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["must_change_password"] is False
    assert body["user"]["username"] == "lalzhrani"

    stored = await _reload(user.user_id)
    assert str(stored.microsoft_object_id) == oid
    assert stored.must_change_password is False
    assert stored.last_login_at is not None
    # كلمة المرور المؤقتة (المرسلة بالإيميل) ما عادت تشتغل.
    assert not verify_password("TempPass1", stored.password_hash)

    async with AsyncSessionLocal() as db:
        logs = (await db.execute(select(AuditLog).where(AuditLog.target_id == user.user_id))).scalars().all()
    meta = [log.metadata_ for log in logs if (log.metadata_ or {}).get("method") == "microsoft"]
    assert meta and meta[0]["first_link"] is True and meta[0]["temp_password_revoked"] is True

    # التوكن يشتغل على باقي المنصة.
    me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200, me.text
    assert me.json()["must_change_password"] is False


async def test_own_password_is_kept_when_already_changed(client: AsyncClient) -> None:
    user = await _make_user(email="a@wadimakkah.sa", username="a_user", must_change_password=False)
    response = await client.post(
        "/api/v1/auth/microsoft", json={"id_token": _id_token(oid=str(uuid.uuid4()), email="a@wadimakkah.sa")}
    )
    assert response.status_code == 200, response.text
    assert verify_password("TempPass1", (await _reload(user.user_id)).password_hash)


async def test_unregistered_microsoft_account_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/microsoft",
        json={"id_token": _id_token(oid=str(uuid.uuid4()), email="new.hire@wadimakkah.sa")},
    )
    assert response.status_code == 401
    assert "غير مسجل" in response.json()["detail"]


async def test_suspended_user_cannot_sign_in(client: AsyncClient) -> None:
    await _make_user(email="s@wadimakkah.sa", username="s_user", status=UserStatus.suspended)
    response = await client.post(
        "/api/v1/auth/microsoft", json={"id_token": _id_token(oid=str(uuid.uuid4()), email="s@wadimakkah.sa")}
    )
    assert response.status_code == 401
    assert "موقوف" in response.json()["detail"]


async def test_linked_object_id_must_match(client: AsyncClient) -> None:
    """مستخدم مربوط بحساب Microsoft، وجاء حساب Microsoft آخر بنفس البريد ⇒ رفض."""
    await _make_user(email="k@wadimakkah.sa", username="k_user", microsoft_object_id=uuid.uuid4())
    response = await client.post(
        "/api/v1/auth/microsoft", json={"id_token": _id_token(oid=str(uuid.uuid4()), email="k@wadimakkah.sa")}
    )
    assert response.status_code == 401
    assert "مربوط بحساب Microsoft آخر" in response.json()["detail"]


async def test_linked_user_found_by_object_id_even_after_email_change(client: AsyncClient) -> None:
    """الربط بالمعرّف الثابت يغلب البريد: لو تغيّر بريد المستخدم بالمنصة يبقى يدخل بحسابه."""
    oid = uuid.uuid4()
    user = await _make_user(email="old@wadimakkah.sa", username="mover", microsoft_object_id=oid, must_change_password=False)
    response = await client.post(
        "/api/v1/auth/microsoft", json={"id_token": _id_token(oid=str(oid), email="renamed@wadimakkah.sa")}
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["user_id"] == str(user.user_id)


@pytest.mark.parametrize(
    "token_kwargs",
    [
        {"tid": "33333333-3333-3333-3333-333333333333"},  # مستأجر آخر (شركة ثانية)
        {"aud": "another-app"},  # توكن لتطبيق آخر
        {"exp_in": -120},  # منتهي
        {"kid": "unknown-key"},  # مفتاح غير معروف لـMicrosoft
    ],
)
async def test_invalid_tokens_are_rejected(client: AsyncClient, token_kwargs: dict) -> None:
    await _make_user(email="v@wadimakkah.sa", username="v_user")
    token = _id_token(oid=str(uuid.uuid4()), email="v@wadimakkah.sa", **token_kwargs)
    response = await client.post("/api/v1/auth/microsoft", json={"id_token": token})
    assert response.status_code == 401, response.text


async def test_forged_signature_is_rejected(client: AsyncClient) -> None:
    await _make_user(email="f@wadimakkah.sa", username="f_user")
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = other_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    now = int(time.time())
    forged = jwt.encode(
        {
            "aud": CLIENT,
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "iat": now,
            "nbf": now,
            "exp": now + 600,
            "oid": str(uuid.uuid4()),
            "tid": TENANT,
            "preferred_username": "f@wadimakkah.sa",
        },
        pem,
        algorithm="RS256",
        headers={"kid": KID},
    )
    response = await client.post("/api/v1/auth/microsoft", json={"id_token": forged})
    assert response.status_code == 401


async def test_not_configured_returns_503(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "TEAMS_TENANT_ID", "")
    response = await client.post(
        "/api/v1/auth/microsoft", json={"id_token": _id_token(oid=str(uuid.uuid4()), email="x@wadimakkah.sa")}
    )
    assert response.status_code == 503
