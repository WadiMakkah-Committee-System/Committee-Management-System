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

# مهلة صريحة إلزامية (2026-09-09 — بلاغ لاما: صفحة بيضاء عالقة بكل
# النظام عند فتح أي شاشة تفاصيل، مش بس المحاضر/الاجتماعات): بدون
# socket_connect_timeout/socket_timeout هنا، عميل redis.asyncio ينتظر
# استجابة Redis بلا أي حد أقصى — لو Redis محليًا توقف أو صار غير قادر
# على الاستجابة (تعطّل الخدمة، توقفت بعد نوم الجهاز، ...)، أي طلب محمي
# (get_current_user يستدعي is_session_valid/touch_session لكل طلب) يعلّق
# للأبد بلا أي خطأ يظهر بالفرونت — وبما إن جلسة قاعدة البيانات
# (get_db) بنفس الطلب فُتحت أصلًا قبل استدعاء Redis، تبقى محجوزة "idle
# in transaction" للأبد معه، فيستنزف pool الاتصالات تدريجيًا مع كل طلب
# عالق جديد (تأكدنا من هذا فعليًا عبر فحص pg_stat_activity مباشرة).
# بالمهلة هنا، انقطاع Redis يفشل بسرعة (خطأ 500 واضح للمستخدمة) بدل ما
# يعلّق الطلب للأبد، وجلسة DB تُغلق تلقائيًا مع الاستثناء (get_db أدناه
# يمسك أي Exception ويعمل rollback قبل إعادة رفعه) — لا مزيد من تسرّب
# اتصالات صامت بسبب Redis تحديدًا.
redis_client = redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=3,
    socket_timeout=3,
)

_SESSION_KEY_PREFIX = "session:"
# فهرس جلسات كل مستخدم (تحديث 2026-10-31 — FR-UM-018: إبطال كل جلسات
# المستخدم بعد استعادة كلمة المرور). Set بـ"user_sessions:{user_id}" يحوي
# session_id لكل جلسة أُنشئت له. قد يبقى فيه معرّفات لجلسات انتهت فعليًا
# (انتهاء الخمول يحذف مفتاح الجلسة فقط) — غير ضار، حذفها لاحقًا no-op.
# صلاحيته = عمر Refresh Token + يوم، ويتجدد مع كل تسجيل دخول جديد: بعد
# انتهاء الـRefresh Token لا يمكن استخدام أي جلسة قديمة أصلًا.
# ملاحظة: الجلسات المُنشأة قبل هذا التحديث غير مفهرسة، فلن تُبطَل بهذه
# الآلية (تنتهي طبيعيًا بالخمول) — حالة انتقالية لمرة واحدة بعد النشر.
_USER_SESSIONS_KEY_PREFIX = "user_sessions:"


def _session_key(session_id: str) -> str:
    return f"{_SESSION_KEY_PREFIX}{session_id}"


def _user_sessions_key(user_id: uuid.UUID | str) -> str:
    return f"{_USER_SESSIONS_KEY_PREFIX}{user_id}"


async def create_session(user_id: uuid.UUID) -> str:
    """
    إنشاء جلسة جديدة في Redis وإرجاع session_id الفريد الخاص بها.
    يسجّلها أيضًا بفهرس جلسات المستخدم (لـinvalidate_all_user_sessions).
    """
    session_id = str(uuid.uuid4())
    index_key = _user_sessions_key(user_id)
    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.set(
            _session_key(session_id),
            str(user_id),
            ex=timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES),
        )
        pipe.sadd(index_key, session_id)
        pipe.expire(index_key, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS + 1))
        await pipe.execute()
    return session_id


async def invalidate_all_user_sessions(user_id: uuid.UUID) -> int:
    """
    الهدف:
    إبطال كل جلسات مستخدم واحد فورًا على كل الأجهزة (بعد استعادة كلمة
    المرور — FR-UM-018، قرار لاما 2026-10-31).

    المدخلات: user_id — معرّف المستخدم.
    المخرجات: int — عدد مفاتيح الجلسات التي كانت موجودة وحُذفت فعليًا.
    التأثيرات الجانبية: يحذف مفاتيح session:* الخاصة به وفهرسه من Redis.
    """
    index_key = _user_sessions_key(user_id)
    session_ids = await redis_client.smembers(index_key)
    deleted = 0
    if session_ids:
        deleted = await redis_client.delete(*(_session_key(sid) for sid in session_ids))
    await redis_client.delete(index_key)
    return int(deleted)


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
