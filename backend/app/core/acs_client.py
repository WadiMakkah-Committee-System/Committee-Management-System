"""
الهدف (تجربة — فرع poc/acs-teams-embed، 2026-11-02):
إصدار توكن قصير العمر من Azure Communication Services (ACS) يسمح للمتصفح
بالانضمام لاجتماع Microsoft Teams **من داخل واجهة المنصة نفسها** (بدل فتح
تطبيق Teams) — نفس فكرة توكن Agora السابق بالضبط، لكن الاتصال يمر عبر Teams
Meeting Interoperability (يبقى التسجيل والتفريغ الرسمي داخل Teams).

المسؤولية:
- issue_meeting_token: ينشئ هوية ACS جديدة لكل جلسة انضمام ويصدر لها توكن
  بنطاق VOIP فقط (صوت/فيديو) — لا يمنح أي صلاحية أخرى.

الاعتماديات:
- حزمة azure-communication-identity (الرسمية من مايكروسوفت) — إصدار التوكن
  يتطلب توقيعًا بمفتاح المورد، ولا بديل موثوق بـhttpx وحده.
- ACS_CONNECTION_STRING بالبيئة (سر — لا يصل للواجهة أبدًا).

ملاحظات:
- المستخدم ينضم كـ"ضيف" (external) لاجتماع Teams — يدخل بعد وجود مستخدم
  Teams واحد على الأقل بالاجتماع، ويمر بالـLobby حسب إعداد الاجتماع.
- التكلفة: 0.004 دولار لكل مشارك بالدقيقة على مورد ACS.
"""

import asyncio
import base64
import json
from dataclasses import dataclass
from datetime import datetime

from azure.communication.identity import CommunicationIdentityClient, CommunicationTokenScope

from app.core.config import settings


class AcsError(Exception):
    """فشل إصدار توكن ACS — تُترجَم إلى 502 بطبقة الـAPI."""


class AcsNotConfiguredError(AcsError):
    """ACS_CONNECTION_STRING غير معبّأ — الانضمام المدمج معطّل (503)."""


class AcsTeamsIdentityError(AcsError):
    """توكن Microsoft المرسَل غير صالح، أو من خارج مستأجر الشركة، أو رفضه ACS (403)."""


@dataclass(frozen=True)
class AcsToken:
    """توكن الانضمام: token يمرَّر لـ@azure/communication-calling بالواجهة،
    user_id معرّف هوية ACS (للتشخيص فقط)، expires_on وقت انتهاء الصلاحية."""

    token: str
    user_id: str
    expires_on: datetime


def is_configured() -> bool:
    """هل الانضمام المدمج مفعّل بهذه البيئة (ACS_CONNECTION_STRING معبّأ)."""
    return bool(settings.ACS_CONNECTION_STRING.strip())


def _issue_sync() -> AcsToken:
    client = CommunicationIdentityClient.from_connection_string(settings.ACS_CONNECTION_STRING.strip())
    user, access = client.create_user_and_token(scopes=[CommunicationTokenScope.VOIP])
    return AcsToken(token=access.token, user_id=user.properties["id"], expires_on=access.expires_on)


async def issue_meeting_token() -> AcsToken:
    """
    الهدف: توكن ACS جديد لجلسة انضمام واحدة.
    المخرجات: AcsToken (صالح 24 ساعة افتراضيًا).
    التأثيرات الجانبية: استدعاء خارجي لـACS (ينشئ هوية جديدة) — يُشغَّل بخيط
    منفصل لأن الحزمة الرسمية متزامنة، حتى لا يحجب حلقة الأحداث.
    الأخطاء: AcsNotConfiguredError، AcsError (مفتاح خاطئ/شبكة).
    """
    if not is_configured():
        raise AcsNotConfiguredError("الانضمام المدمج غير مُهيّأ (ACS_CONNECTION_STRING)")
    try:
        return await asyncio.to_thread(_issue_sync)
    except Exception as exc:  # الحزمة ترمي أنواعًا متعددة (HttpResponseError, ValueError...)
        raise AcsError(f"تعذّر إصدار توكن Azure Communication Services: {type(exc).__name__}") from exc


# ============================== الدخول بحساب Microsoft (هوية Teams) ==============================


def _unverified_claims(aad_token: str) -> dict:
    """
    الهدف: قراءة حقول توكن Microsoft Entra (tid/oid/اسم المستخدم) **بدون**
    التحقق من التوقيع.
    لماذا بدون تحقق هنا: التحقق الفعلي من التوقيع وصلاحية التوكن يجريه ACS
    نفسه عند التبادل (get_token_for_teams_user) — هو الذي يرفض أي توكن مزوّر
    أو منتهٍ أو لا يطابق oid/client_id. نستخدم القراءة هنا فقط لاستخراج oid
    (مطلوب للتبادل) ولرفض مبكر لحسابات من خارج مستأجر الشركة.
    الأخطاء: AcsTeamsIdentityError لو التوكن ليس JWT مقروءًا.
    """
    try:
        payload = aad_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as exc:
        raise AcsTeamsIdentityError("توكن Microsoft غير صالح") from exc
    if not isinstance(claims, dict):
        raise AcsTeamsIdentityError("توكن Microsoft غير صالح")
    return claims


@dataclass(frozen=True)
class TeamsUserIdentity:
    """هوية مستخدم Microsoft 365 المستخرجة من توكنه (للتدقيق والعرض)."""

    object_id: str
    username: str


def _exchange_sync(aad_token: str, object_id: str) -> AcsToken:
    client = CommunicationIdentityClient.from_connection_string(settings.ACS_CONNECTION_STRING.strip())
    access = client.get_token_for_teams_user(aad_token, settings.TEAMS_CLIENT_ID.strip(), object_id)
    return AcsToken(token=access.token, user_id=object_id, expires_on=access.expires_on)


async def issue_teams_user_token(aad_token: str) -> tuple[AcsToken, TeamsUserIdentity]:
    """
    الهدف: تحويل توكن Microsoft Entra لموظف الشركة (سجّل دخوله بالواجهة عبر
    MSAL) إلى توكن ACS بهويته الحقيقية في Teams — فيدخل الاجتماع باسمه،
    بدون Lobby، والمنظّم يدخل كمنظّم ويقدر يقبل الضيوف من داخل المنصة.

    المدخلات: aad_token بنطاقَي Teams.ManageCalls وTeams.ManageChats
    (https://auth.msft.communication.azure.com/...).
    المخرجات: (AcsToken، TeamsUserIdentity).
    قواعد: يُرفض أي توكن من مستأجر غير TEAMS_TENANT_ID قبل الاتصال بـACS.
    الأخطاء: AcsNotConfiguredError، AcsTeamsIdentityError (توكن مرفوض/خارجي)،
    AcsError (شبكة/خطأ آخر من ACS).
    """
    if not is_configured() or not settings.TEAMS_CLIENT_ID.strip():
        raise AcsNotConfiguredError("الانضمام بحساب Microsoft غير مُهيّأ")
    claims = _unverified_claims(aad_token)
    object_id = str(claims.get("oid") or "")
    tenant_id = str(claims.get("tid") or "")
    if not object_id or tenant_id.lower() != settings.TEAMS_TENANT_ID.strip().lower():
        raise AcsTeamsIdentityError("حساب Microsoft ليس من حسابات الشركة")
    username = str(claims.get("preferred_username") or claims.get("upn") or claims.get("name") or "")
    try:
        token = await asyncio.to_thread(_exchange_sync, aad_token, object_id)
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        # تفاصيل رد ACS (رمز الخطأ ورسالته — بدون التوكن) تُكتب بسجل الخادم فقط
        # لتشخيص سبب الرفض (رخصة/مستأجر/صلاحية)، ولا تصل للمستخدم.
        detail = str(getattr(exc, "message", "") or exc).replace(aad_token, "<token>")[:500]
        if status_code in (400, 401, 403):
            raise AcsTeamsIdentityError(f"رفض ACS توكن Microsoft ({status_code}): {detail}") from exc
        raise AcsError(f"تعذّر تبادل توكن Microsoft مع ACS: {type(exc).__name__}: {detail}") from exc
    return token, TeamsUserIdentity(object_id=object_id, username=username)
