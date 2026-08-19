"""
الهدف:
توفير اتصال Redis واحد يُعاد استخدامه لتتبع الجلسات (Sessions) وإبطال
التوكنات (Token Invalidation) عند تسجيل الخروج أو انتهاء مدة الخمول.

المسؤولية:
- إنشاء عميل Redis غير متزامن (async) واحد لكل التطبيق.
- توفير دوال مساعدة لإدارة الجلسات: إنشاء، تجديد النشاط (idle timeout)،
  التحقق من الصلاحية، وإبطال الجلسة (logout).

آلية العمل:
كل جلسة تسجيل دخول ناجحة تُنشئ session_id عشوائي (UUID) يُخزَّن كـ مفتاح
في Redis بصيغة "session:{session_id}" وقيمته user_id، مع Expiry مساوٍ لمدة
الخمول المسموحة (SESSION_IDLE_TIMEOUT_MINUTES). كل طلب محمي (authenticated)
يجدّد هذا الـ Expiry (sliding expiration) — إذا انتهت صلاحية المفتاح تلقائيًا
في Redis، تُعتبر الجلسة منتهية حتى لو كان الـ Access Token نفسه لم تنتهِ
صلاحيته بعد. هذا يحقق "إنهاء الجلسة تلقائيًا بعد فترة خمول" من CLAUDE.md.
"""

import uuid
from datetime import timedelta

import redis.asyncio as redis

from app.core.config import settings

redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

_SESSION_KEY_PREFIX = "session:"


def _session_key(session_id: str) -> str:
    return f"{_SESSION_KEY_PREFIX}{session_id}"


async def create_session(user_id: uuid.UUID) -> str:
    """إنشاء جلسة جديدة في Redis وإرجاع session_id الفريد الخاص بها."""
    session_id = str(uuid.uuid4())
    await redis_client.set(
        _session_key(session_id),
        str(user_id),
        ex=timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES),
    )
    return session_id


async def touch_session(session_id: str) -> bool:
    """
    تجديد مدة صلاحية الجلسة عند كل طلب ناجح (Sliding Expiration).
    ترجع False إذا كانت الجلسة غير موجودة أصلًا (منتهية أو مُبطَلة).
    """
    exists = await redis_client.expire(
        _session_key(session_id),
        timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES),
    )
    return bool(exists)


async def is_session_valid(session_id: str) -> bool:
    """التحقق من أن الجلسة ما زالت موجودة (لم تنتهِ ولم تُبطَل)."""
    return await redis_client.exists(_session_key(session_id)) == 1


async def invalidate_session(session_id: str) -> None:
    """إبطال جلسة فورًا (تسجيل الخروج)."""
    await redis_client.delete(_session_key(session_id))
