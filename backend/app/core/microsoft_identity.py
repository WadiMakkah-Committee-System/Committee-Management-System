"""
الهدف (migration 0042 — قرار لاما 2026-11-02):
التحقق من هوية موظف الشركة بعد تسجيل دخوله بحساب Microsoft 365 من الواجهة —
الباك-إند هو اللي يتحقق من توقيع التوكن بنفسه، ما يثق بالواجهة.

المسؤولية:
- verify_id_token: يتحقق من ID Token صادر من Microsoft Entra (توقيع RS256 بمفاتيح
  Microsoft العامة، المُصدِر = مستأجر الشركة، الجمهور = تطبيقنا، الصلاحية الزمنية)،
  ويرجع الهوية (Object ID + البريد + الاسم).
- is_enabled / company_domains: إعدادات عامة تُرجَع للواجهة.

الاعتماديات:
- python-jose (موجودة أصلًا بالمشروع لتوكنات المنصة) للتحقق من التوقيع.
- httpx لجلب مفاتيح Microsoft العامة (JWKS) — تُخزَّن بالذاكرة 24 ساعة، وتُجلب
  من جديد لو جاء توكن بمفتاح غير معروف (Microsoft تبدّل مفاتيحها دوريًا).
- TEAMS_TENANT_ID وTEAMS_CLIENT_ID (نفس تطبيق Entra المستخدم لـTeams).

ملاحظات أمنية:
- مفاتيح التحقق تُجلب من login.microsoftonline.com الخاص بمستأجر الشركة فقط،
  وأي توكن من مستأجر آخر يُرفض (issuer/tid).
- لا يُخزَّن التوكن نفسه بأي مكان.
"""

import time
from dataclasses import dataclass

import httpx
from jose import JWTError, jwt

from app.core.config import settings

_JWKS_TTL_SECONDS = 24 * 60 * 60
_REQUEST_TIMEOUT_SECONDS = 15.0

# كاش مفاتيح Microsoft العامة: (وقت الجلب، قائمة المفاتيح).
_jwks_cache: tuple[float, list[dict]] | None = None


class MicrosoftIdentityError(Exception):
    """التوكن غير صالح/منتهٍ/من خارج الشركة — رسالة عامة للمستخدم (401)."""


class MicrosoftNotConfiguredError(MicrosoftIdentityError):
    """الدخول بـMicrosoft غير مفعّل بهذه البيئة (TEAMS_TENANT_ID/CLIENT_ID فارغة)."""


@dataclass(frozen=True)
class MicrosoftIdentity:
    """هوية الموظف المستخرجة من توكن موثّق: object_id ثابت لا يتغير، وemail
    (اسم الدخول بالشركة) للبحث عن المستخدم بالمنصة."""

    object_id: str
    tenant_id: str
    email: str
    name: str


def is_enabled() -> bool:
    """هل الدخول بحساب Microsoft مفعّل (تطبيق Entra مُعرَّف بالبيئة)."""
    return bool(settings.TEAMS_TENANT_ID.strip() and settings.TEAMS_CLIENT_ID.strip())


def company_domains() -> list[str]:
    """نطاقات بريد الشركة (أحرف صغيرة) من MICROSOFT_LOGIN_DOMAINS."""
    return [d.strip().lower().lstrip("@") for d in settings.MICROSOFT_LOGIN_DOMAINS.split(",") if d.strip()]


def _tenant() -> str:
    return settings.TEAMS_TENANT_ID.strip()


async def _fetch_jwks() -> list[dict]:
    """يجلب مفاتيح Microsoft العامة لمستأجر الشركة (JWKS)."""
    url = f"https://login.microsoftonline.com/{_tenant()}/discovery/v2.0/keys"
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json().get("keys", [])


async def _signing_key(kid: str) -> dict:
    """
    يرجع مفتاح التوقيع المطابق لـkid من الكاش، ويجلب المفاتيح من جديد لو
    الكاش قديم أو المفتاح غير موجود فيه (تدوير مفاتيح Microsoft).
    الأخطاء: MicrosoftIdentityError لو المفتاح غير موجود حتى بعد الجلب.
    """
    global _jwks_cache
    now = time.monotonic()
    for attempt in range(2):
        if _jwks_cache is None or attempt == 1 or now - _jwks_cache[0] > _JWKS_TTL_SECONDS:
            try:
                _jwks_cache = (now, await _fetch_jwks())
            except httpx.HTTPError as exc:
                raise MicrosoftIdentityError("تعذّر التحقق من حساب Microsoft حاليًا، حاول بعد قليل") from exc
        key = next((k for k in _jwks_cache[1] if k.get("kid") == kid), None)
        if key is not None:
            return key
    raise MicrosoftIdentityError("توكن Microsoft غير صالح")


async def verify_id_token(id_token: str) -> MicrosoftIdentity:
    """
    الهدف: التحقق الكامل من ID Token صادر من Microsoft لموظف الشركة.
    المدخلات: id_token (من MSAL بالواجهة بعد تسجيل الدخول).
    الفحوص: التوقيع (RS256 بمفتاح Microsoft)، aud = TEAMS_CLIENT_ID،
    iss = مستأجر الشركة (v2.0)، exp/nbf، ووجود oid.
    المخرجات: MicrosoftIdentity.
    الأخطاء: MicrosoftNotConfiguredError، MicrosoftIdentityError.
    """
    if not is_enabled():
        raise MicrosoftNotConfiguredError("الدخول بحساب Microsoft غير مفعّل")
    invalid = MicrosoftIdentityError("توكن Microsoft غير صالح أو منتهي الصلاحية")
    try:
        header = jwt.get_unverified_header(id_token)
    except JWTError as exc:
        raise invalid from exc
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise invalid
    key = await _signing_key(header["kid"])
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=settings.TEAMS_CLIENT_ID.strip(),
            issuer=f"https://login.microsoftonline.com/{_tenant()}/v2.0",
            # at_hash يخص access token مرافق — ما نستلمه هنا.
            options={"verify_at_hash": False},
        )
    except JWTError as exc:
        raise invalid from exc

    object_id = str(claims.get("oid") or "")
    tenant_id = str(claims.get("tid") or "")
    email = str(claims.get("preferred_username") or claims.get("email") or "").strip()
    if not object_id or tenant_id.lower() != _tenant().lower() or not email:
        raise invalid
    return MicrosoftIdentity(
        object_id=object_id, tenant_id=tenant_id, email=email, name=str(claims.get("name") or "")
    )
