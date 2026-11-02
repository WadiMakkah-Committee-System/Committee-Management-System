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
from dataclasses import dataclass
from datetime import datetime

from azure.communication.identity import CommunicationIdentityClient, CommunicationTokenScope

from app.core.config import settings


class AcsError(Exception):
    """فشل إصدار توكن ACS — تُترجَم إلى 502 بطبقة الـAPI."""


class AcsNotConfiguredError(AcsError):
    """ACS_CONNECTION_STRING غير معبّأ — الانضمام المدمج معطّل (503)."""


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
