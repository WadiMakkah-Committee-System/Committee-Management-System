"""
الهدف:
إصدار Token قصير العمر (Server-Side) لجلسات Agora RTC (اجتماعات الفيديو
عن بعد — meetings.join)، عبر حزمة agora-token-builder (خوارزمية Agora
الرسمية لبناء Token — HMAC/AES محليًا بدون أي اتصال شبكة فعلي، بخلاف
storage_client.py الذي يتصل فعليًا بـSupabase Storage REST API).

المسؤولية:
- generate_rtc_token: يبني Token صالح لقناة/uid محددين، بصلاحية Publisher
  (بث + استقبال صوت/فيديو) — لا يوجد مفهوم "مشاهد فقط" باجتماعات هذا
  النظام، فكل من يملك meetings.join يستطيع النشر.

ملاحظات أمنية:
- AGORA_APP_CERTIFICATE لا يصل للـFrontend أبدًا (نفس مبدأ
  SUPABASE_SERVICE_ROLE_KEY في storage_client.py) — العميل يستلم Token
  جاهز فقط، وليس المفاتيح نفسها.
- uid يُولّد عشوائيًا بطبقة الخدمة (meeting_service.join_meeting) لكل
  جلسة انضمام، وليس من العميل — يمنع أي محاولة انتحال uid شخص آخر.
- AgoraError تُستخدم كـException عام تلتقطه طبقة API وتحوّله لاستجابة
  HTTP مناسبة (503 لو غير مُهيّأ، نفس نمط StorageNotConfiguredError).
"""

import time

from agora_token_builder import RtcTokenBuilder
from agora_token_builder.RtcTokenBuilder import Role_Publisher

from app.core.config import settings


class AgoraError(Exception):
    """خطأ عام أثناء إصدار Token Agora."""


class AgoraNotConfiguredError(AgoraError):
    """AGORA_APP_ID أو AGORA_APP_CERTIFICATE غير مُعبّأين بالبيئة الحالية."""


def get_app_id() -> str:
    if not settings.AGORA_APP_ID or not settings.AGORA_APP_CERTIFICATE:
        raise AgoraNotConfiguredError(
            "إعدادات Agora غير مكتملة (AGORA_APP_ID / AGORA_APP_CERTIFICATE)"
        )
    return settings.AGORA_APP_ID


def generate_rtc_token(*, channel_name: str, uid: int) -> tuple[str, int]:
    """يبني Token RTC صالح لمدة AGORA_TOKEN_TTL_SECONDS (ثانية) من الآن،
    بصلاحية Publisher. يُعيد (token, expires_at) — expires_at بصيغة Unix
    timestamp (نفس صيغة privilegeExpiredTs التي يطلبها Agora)."""
    app_id = get_app_id()
    expires_at = int(time.time()) + settings.AGORA_TOKEN_TTL_SECONDS
    token = RtcTokenBuilder.buildTokenWithUid(
        app_id,
        settings.AGORA_APP_CERTIFICATE,
        channel_name,
        uid,
        Role_Publisher,
        expires_at,
    )
    return token, expires_at
