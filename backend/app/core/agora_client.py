"""
الهدف (الرجوع لـAgora — قرار لاما 2026-11-04):
إصدار توكن قصير العمر لغرفة Agora RTC (فيديو/صوت الاجتماع داخل المنصة)،
عبر حزمة agora-token-builder (خوارزمية Agora الرسمية — تُبنى محليًا بدون أي
اتصال شبكة).

المسؤولية:
- is_configured: هل مفاتيح Agora موجودة بالبيئة.
- generate_rtc_token: توكن لقناة (= رقم الاجتماع) وحساب (= user_id بالمنصة).

قرار تصميم — الحساب نصّي (User Account) بدل رقم عشوائي (النسخة القديمة):
- الحساب = user_id بالمنصة، فكل جهاز يعرف "مين هذا الصوت/الفيديو" مباشرة
  من Agora نفسها (remoteUser.uid = user_id) — بدون جدول ربط إضافي. هذا يخدم
  اسم المتحدث، ودمج أصوات الأعضاء بالتسجيل، والقبول/الإحصائيات.
- نفس المستخدم لو دخل من جهازين: Agora تطلّع الجهاز الأقدم (UID_CONFLICT) —
  سلوك مقبول (ما يصير له صوتين بالاجتماع).
- العميل ما يختار الحساب: الباك-إند يبنيه من المستخدم المسجّل دخوله، فلا
  يقدر أحد ينتحل شخص ثاني (التوكن مربوط بالحساب).

ملاحظات أمنية:
- AGORA_APP_CERTIFICATE لا يصل للواجهة أبدًا — العميل يستلم توكن جاهز فقط.
- صلاحية التوكن AGORA_TOKEN_TTL_SECONDS (4 ساعات افتراضيًا) — الواجهة تجدده
  قبل انتهائه (حدث token-privilege-will-expire).
"""

import time

from agora_token_builder import RtcTokenBuilder
from agora_token_builder.RtcTokenBuilder import Role_Publisher

from app.core.config import settings


class AgoraError(Exception):
    """خطأ عام أثناء إصدار توكن Agora."""


class AgoraNotConfiguredError(AgoraError):
    """AGORA_APP_ID أو AGORA_APP_CERTIFICATE غير معبّأين بالبيئة."""


def is_configured() -> bool:
    return bool(settings.AGORA_APP_ID.strip() and settings.AGORA_APP_CERTIFICATE.strip())


def get_app_id() -> str:
    """App ID (عام — يُرسل للواجهة). الأخطاء: AgoraNotConfiguredError."""
    if not is_configured():
        raise AgoraNotConfiguredError("إعدادات Agora غير مكتملة (AGORA_APP_ID / AGORA_APP_CERTIFICATE)")
    return settings.AGORA_APP_ID.strip()


def generate_rtc_token(*, channel_name: str, account: str) -> tuple[str, int]:
    """
    الهدف: توكن RTC بصلاحية Publisher (بث + استقبال) لحساب نصّي في قناة.
    المدخلات: channel_name (رقم الاجتماع)، account (user_id بالمنصة).
    المخرجات: (token, expires_at) — expires_at بصيغة Unix timestamp.
    الأخطاء: AgoraNotConfiguredError.
    """
    app_id = get_app_id()
    expires_at = int(time.time()) + settings.AGORA_TOKEN_TTL_SECONDS
    token = RtcTokenBuilder.buildTokenWithAccount(
        app_id,
        settings.AGORA_APP_CERTIFICATE.strip(),
        channel_name,
        account,
        Role_Publisher,
        expires_at,
    )
    return token, expires_at
