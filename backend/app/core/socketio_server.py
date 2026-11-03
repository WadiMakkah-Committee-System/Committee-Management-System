"""
الهدف:
قناة الاجتماع/المحضر اللحظية — Socket.IO بدل WebSocket الخام (app/core/
meeting_realtime.py سابقًا). قرار لاما 2026-09-10: تبديل طبقة النقل
لواحدة أنضج (إعادة اتصال تلقائية + Rooms جاهزة بدل connection_manager
اليدوي) — نفس بالضبط المنطق/الأحداث القديمة (محادثة + رفع يد + بند
أجندة قيد المناقشة + تعاون تحرير المحضر)، فقط بآلية نقل مختلفة.

تنويه صريح موثّق مع لاما: هذا التحويل *لا* يحل مشكلة تعليق جلسات DB
بطلبات REST العادية (GET/PATCH على /meetings، /committees، ...) —
السبب الموثّق (فحص pg_stat_activity حيًا) هو جلسة get_db تفضل مفتوحة
داخل طلب REST نفسه (على الأغلب BackgroundTask بريد SMTP بلا timeout —
راجعي app/core/email_client.py)، لا علاقة له بقناة الاجتماع اللحظية.
هذا تحسين منفصل لطبقة النقل فقط، بناءً على طلب صريح.

المصادقة: التوكن يصل عبر Socket.IO "auth" (لا Query String كالسابق —
أنظف ولا يظهر بسجلات الشبكة/الخادم) — راجعي معالج connect أدناه، ونفس
منطق get_current_user_ws بالضبط (app/core/dependencies.py) لكن مباشرة
هنا بدل Dependency (Socket.IO ما يستخدم نظام Depends الخاص بـFastAPI).

الغرفة (room) = meeting:{meeting_id} — كل من قناة غرفة الاجتماع
(useMeetingRealtime) وقناة المحضر (useMinutesRealtime) يفتحان اتصالين
منفصلين (namespace الافتراضي، sid مختلف) وينضمان لنفس الغرفة، بالضبط
كسلوك connection_manager القديم (كلاهما يبث/يستقبل بنفس القناة، والفرونت
يتجاهل الأحداث اللي ما يهتم فيها).

جلسة DB: قصيرة العمر دائمًا (async with AsyncSessionLocal() لكل حدث
يحتاج قاعدة بيانات فعليًا) — لا جلسة مفتوحة طوال عمر الاتصال، بنفس روح
إصلاح 2026-09-09/2026-09-10 بـdependencies.py. المستخدم (User) نفسه
يُحمَّل مرة واحدة فقط عند connect (query واحدة، eager-loaded عبر
user_service.get_user) ويُخزَّن بجلسة Socket.IO (sio.save_session) —
آمن القراءة بعد إغلاق الجلسة لأن AsyncSessionLocal مضبوطة
expire_on_commit=False (راجعي db/session.py)، بالضبط نفس افتراض الكود
القديم (current_user كان يُمرَّر لكل الحلقة من نفس التحميل الأول).
"""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import socketio

from app.core.config import settings
from app.core.redis_client import is_session_valid, redis_client, touch_session
from app.core.security import InvalidTokenError, decode_token
from app.db.session import AsyncSessionLocal
from app.models.user import User, UserStatus
from app.schemas.meeting_chat import MeetingChatMessageOut
from app.services import meeting_chat_service, user_service
from app.services.meeting_chat_service import MeetingChatForbiddenError, MeetingChatNotFoundError

# تحديث 2026-09-12 (نشر المنصة): نفس تقييد main.py CORSMiddleware —
# مفتوح بالتطوير فقط، ومقيَّد بالإنتاج لنطاقات settings.CORS_ORIGINS.
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*" if settings.ENVIRONMENT == "development" else settings.cors_origins_list,
)

logger = logging.getLogger(__name__)


def _room(meeting_id: str) -> str:
    return f"meeting:{meeting_id}"


# ============================== حالة الغرفة (Redis) ==============================
# تحديث لاما 2026-11-03 (دفعة تحسينات الاجتماع): طابور رفع اليد وبند المناقشة
# الحالي (مع مؤقته) صاروا يُحفظون بـRedis — فاللي يدخل متأخر يستلم الصورة
# الحالية (room.state) بدل ما يشوف الغرفة "فاضية" لين يصير حدث جديد.
# مؤقتة بطبيعتها (12 ساعة) — ما تُخزَّن بقاعدة البيانات.
_ROOM_STATE_TTL = timedelta(hours=12)
# حدود مؤقت البند: من دقيقة إلى 4 ساعات (بالثواني).
_TIMER_MIN_SECONDS = 60
_TIMER_MAX_SECONDS = 4 * 60 * 60


def _hands_key(meeting_id: str) -> str:
    return f"meeting:{meeting_id}:hands"


def _discussing_key(meeting_id: str) -> str:
    return f"meeting:{meeting_id}:discussing"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _room_state(meeting_id: str) -> dict[str, Any]:
    """الصورة الحالية للغرفة: طابور الأيدي المرفوعة (بالترتيب) + بند المناقشة الحالي."""
    hands: list[dict[str, Any]] = []
    discussing: dict[str, Any] | None = None
    try:
        raw_hands = await redis_client.hgetall(_hands_key(meeting_id))
        for user_id, value in raw_hands.items():
            data = json.loads(value)
            hands.append({"user_id": user_id, "full_name": data.get("full_name", ""), "raised_at": data.get("raised_at")})
        hands.sort(key=lambda h: h.get("raised_at") or "")
        raw_discussing = await redis_client.get(_discussing_key(meeting_id))
        if raw_discussing:
            discussing = json.loads(raw_discussing)
    except Exception:  # noqa: BLE001 — حالة مساعدة فقط، ما توقف الاتصال
        logger.warning("room.state: تعذّر قراءة حالة الغرفة من Redis (meeting=%s)", meeting_id, exc_info=True)
    return {"hands": hands, "discussing": discussing}


async def _user_has_other_connection(meeting_id: str, user_id: str, exclude_sid: str) -> bool:
    """هل للمستخدم اتصال آخر بنفس الغرفة (غرفة الاجتماع + المحضر يفتحان اتصالين)."""
    for other_sid, _eio in sio.manager.get_participants("/", _room(meeting_id)):
        if other_sid == exclude_sid:
            continue
        try:
            other = await sio.get_session(other_sid)
        except KeyError:
            continue
        other_user: User | None = other.get("user")
        if other_user is not None and str(other_user.user_id) == user_id:
            return True
    return False


async def _resolve_user_from_token(token: str) -> User | None:
    """مكافئ app.core.dependencies._resolve_user_from_token — مكرَّر هنا
    عمدًا (بدل استيراده) لأنه يفتح جلسة DB خاصة به بنمط مختلف قليلًا
    (Socket.IO ما يدعم رفع HTTPException)، ولتفادي أي استيراد دائري بين
    core.dependencies وcore.socketio_server مستقبلًا."""
    try:
        payload = decode_token(token, expected_type="access")
    except InvalidTokenError:
        return None

    session_id = payload.get("sid")
    if session_id is None or not await is_session_valid(session_id):
        return None

    user_id = payload.get("sub")
    if user_id is None:
        return None

    async with AsyncSessionLocal() as db:
        user = await user_service.get_user(db, user_id)
        if user is None or user.status == UserStatus.suspended:
            return None
        await touch_session(session_id)
        return user


@sio.event
async def connect(sid: str, environ: dict, auth: dict | None) -> bool:
    auth = auth or {}
    token = auth.get("token")
    meeting_id_raw = auth.get("meeting_id")
    if not token or not meeting_id_raw:
        return False

    try:
        meeting_id = uuid.UUID(str(meeting_id_raw))
    except ValueError:
        return False

    user = await _resolve_user_from_token(token)
    if user is None:
        return False

    try:
        async with AsyncSessionLocal() as db:
            await meeting_chat_service.require_realtime_access(db, actor=user, meeting_id=meeting_id)
    except (MeetingChatNotFoundError, MeetingChatForbiddenError):
        return False

    await sio.save_session(sid, {"user": user, "meeting_id": str(meeting_id)})
    room = _room(str(meeting_id))

    # إصلاح 2026-09-13 (بلاغ لاما — عضو يفتح الاجتماع بعد غيره يرى البقية
    # "غير متصلين" رغم اتصالهم الفعلي): onlineUserIds بالفرونت كان يُبنى
    # فقط من أحداث presence.joined/presence.left المستقبلية — بلا أي
    # صورة (snapshot) لحالة الغرفة الحالية عند الاتصال. أي مستخدم متصل
    # *قبل* هذا الانضمام يبقى غير معروف للقادم الجديد للأبد (حدث انضمامه
    # بُثّ قبل وجود مستمع له أصلًا). الحل: قبل ضم sid الجديد لنفسه، نجمع
    # كل من هو متصل فعليًا بالغرفة الآن (بيانات جلسة كل sid آخر، بلا أي
    # استعلام DB إضافي) ونرسلها لهذا الاتصال فقط (to=sid، لا بث للغرفة)
    # كصورة أولية — presence.joined يبقى كما هو لبث الانضمامات اللاحقة.
    existing_user_ids: set[str] = set()
    for other_sid, _eio_sid in sio.manager.get_participants("/", room):
        try:
            other_session = await sio.get_session(other_sid)
        except KeyError:
            continue
        other_user: User | None = other_session.get("user")
        if other_user is not None:
            existing_user_ids.add(str(other_user.user_id))

    # إصلاح 2026-09-15 (تحقيق أداء لاما — تحليل.pdf، البند رقم 8): sio.enter_room
    # بـAsyncServer هو coroutine فعليًا (موثّق صراحة بمصدر python-socketio:
    # "Note: this method is a coroutine") — استدعاؤه بدون await كان يُنشئ
    # كائن coroutine ولا يُنفَّذه إطلاقًا، أي هذا الـsid لم يكن ينضم لغرفة
    # الاجتماع فعليًا رغم نجاح connect() ورجوع True. الأثر: presence.joined/
    # chat.message/hand.raised/agenda.discussing/minutes.updated —
    # كل بث لاحق عبر room=room (وكلها تمر بنفس هذا المسار) كان لا يصل أبدًا
    # لهذا الاتصال تحديدًا (بينما الرسائل المباشرة to=sid، مثل presence.roster
    # أعلاه، كانت تصل بشكل طبيعي لأنها لا تعتمد على عضوية الغرفة). الإصلاح:
    # إضافة await فقط — لا تغيير بالمنطق.
    await sio.enter_room(sid, room)

    if existing_user_ids:
        await sio.emit("presence.roster", {"user_ids": list(existing_user_ids)}, to=sid)

    # الصورة الحالية للطابور وبند المناقشة (مع مؤقته) — للقادم الجديد فقط.
    await sio.emit("room.state", await _room_state(str(meeting_id)), to=sid)

    await sio.emit(
        "presence.joined",
        {"user_id": str(user.user_id), "full_name": user.full_name},
        room=room,
    )
    return True


@sio.event
async def disconnect(sid: str) -> None:
    try:
        session = await sio.get_session(sid)
    except KeyError:
        return
    user: User | None = session.get("user")
    meeting_id: str | None = session.get("meeting_id")
    if not user or not meeting_id:
        return
    # خرج فعليًا (ما عنده اتصال ثاني بالغرفة) ⇒ تنزل يده من الطابور.
    if not await _user_has_other_connection(meeting_id, str(user.user_id), sid):
        try:
            await redis_client.hdel(_hands_key(meeting_id), str(user.user_id))
        except Exception:  # noqa: BLE001
            logger.warning("disconnect: تعذّر إنزال اليد من Redis", exc_info=True)
    await sio.emit(
        "presence.left",
        {"user_id": str(user.user_id), "full_name": user.full_name},
        room=_room(meeting_id),
    )


async def _session_user_and_room(sid: str) -> tuple[User, str] | None:
    try:
        session = await sio.get_session(sid)
    except KeyError:
        return None
    user: User | None = session.get("user")
    meeting_id: str | None = session.get("meeting_id")
    if not user or not meeting_id:
        return None
    return user, meeting_id


# إصلاح 2026-09-14 (بلاغ لاما — "أرسل رسالة، تختفي من الحقل، ما تظهر
# بالدردشة، ما أدري وصلت ولا لا"): المعالج القديم كان بلا Acknowledgment
# إطلاقًا (Socket.IO يدعم إرجاع قيمة من المعالج تصل تلقائيًا كـ callback
# بجهة العميل — socket.emit(event, payload, callback) بدل emit عادي بلا
# رد) — فالفرونت (useMeetingRealtime.ts::send) كان ينادي socket.emit
# بلا أي callback إطلاقًا، أي حتى لو أُرجعت قيمة هنا، ما أحد يستقبلها.
# الأخطر: كان يُمسك ValueError فقط ثم return صامتة — أي استثناء آخر
# (MeetingChatForbiddenError/MeetingChatNotFoundError من
# require_realtime_access داخل send_message، أو أي خطأ DB/تسلسل غير
# متوقع) يخرج من المعالج بلا معالجة؛ python-socketio يبتلعه داخليًا
# (يسجّله بـstderr فقط) بلا أي إشعار للعميل — فتبدو الرسالة "اختفت
# بصمت" رغم عدم حفظها إطلاقًا. الحل: (1) إرجاع dict ack من كل مسار
# (نجاح/فشل) ليصل كـcallback حقيقي للمرسل تحديدًا (لا بث)، (2) الإمساك
# بكل فئات الفشل المعروفة صراحة (تحقق/صلاحية/عدم-وجود) مع رسالة عربية
# واضحة لكل حالة، (3) لوغ فعلي (logger.exception) لأي خطأ غير متوقع بدل
# ابتلاعه، بدل try/except عام صامت. البث لبقية أعضاء الغرفة (بما فيها
# المرسل نفسه، لأنه منضم لنفس الغرفة) يبقى كما هو تمامًا عند النجاح
# فقط — هذا الجزء لم يتغير، كان يعمل صحيحًا أصلًا.
@sio.on("chat.send")
async def chat_send(sid: str, data: dict[str, Any] | None) -> dict[str, Any]:
    resolved = await _session_user_and_room(sid)
    if resolved is None:
        return {"ok": False, "error": "انتهت صلاحية جلسة الاتصال — أعيدي تحميل الصفحة."}
    user, meeting_id = resolved
    body = str((data or {}).get("body", "")).strip()
    if not body:
        return {"ok": False, "error": "نص الرسالة لا يمكن أن يكون فارغًا."}
    try:
        async with AsyncSessionLocal() as db:
            message = await meeting_chat_service.send_message(
                db, actor=user, meeting_id=uuid.UUID(meeting_id), body=body
            )
    except ValueError as exc:
        return {"ok": False, "error": str(exc) or "نص الرسالة غير صالح."}
    except (MeetingChatForbiddenError, MeetingChatNotFoundError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:
        logger.exception(
            "chat.send: فشل غير متوقع بحفظ رسالة الدردشة — meeting_id=%s user_id=%s",
            meeting_id,
            user.user_id,
        )
        return {"ok": False, "error": "تعذر إرسال الرسالة بسبب خطأ بالخادم — حاولي مجددًا."}

    payload = {"message": MeetingChatMessageOut.model_validate(message).model_dump(mode="json")}
    await sio.emit("chat.message", payload, room=_room(meeting_id))
    return {"ok": True, "message": payload["message"]}


@sio.on("hand.raise")
async def hand_raise(sid: str, _data: dict[str, Any] | None = None) -> None:
    """رفع اليد — يدخل طابور المتحدثين بوقت الرفع (أول من رفع أول من يتكلم)."""
    resolved = await _session_user_and_room(sid)
    if resolved is None:
        return
    user, meeting_id = resolved
    key = _hands_key(meeting_id)
    raised_at = _now_iso()
    try:
        # hsetnx: لو رافع يده أصلًا يبقى بمكانه بالطابور (ما يرجع لآخره).
        existing = await redis_client.hget(key, str(user.user_id))
        if existing:
            raised_at = json.loads(existing).get("raised_at") or raised_at
        else:
            await redis_client.hset(
                key, str(user.user_id), json.dumps({"full_name": user.full_name, "raised_at": raised_at}, ensure_ascii=False)
            )
        await redis_client.expire(key, _ROOM_STATE_TTL)
    except Exception:  # noqa: BLE001 — البث يكمل حتى لو Redis تعطل
        logger.warning("hand.raise: تعذّر حفظ الطابور بـRedis", exc_info=True)
    await sio.emit(
        "hand.raised",
        {"user_id": str(user.user_id), "full_name": user.full_name, "raised_at": raised_at},
        room=_room(meeting_id),
    )


@sio.on("hand.lower")
async def hand_lower(sid: str, _data: dict[str, Any] | None = None) -> None:
    resolved = await _session_user_and_room(sid)
    if resolved is None:
        return
    user, meeting_id = resolved
    try:
        await redis_client.hdel(_hands_key(meeting_id), str(user.user_id))
    except Exception:  # noqa: BLE001
        logger.warning("hand.lower: تعذّر تحديث الطابور بـRedis", exc_info=True)
    await sio.emit("hand.lowered", {"user_id": str(user.user_id)}, room=_room(meeting_id))


@sio.on("floor.give")
async def floor_give(sid: str, data: dict[str, Any] | None) -> dict[str, Any]:
    """
    الهدف (طابور المتحدثين — قرار لاما 2026-11-03): رئيس اللجنة يعطي الكلمة
    لصاحب يد مرفوعة ⇒ تنزل يده من الطابور ويُبث "floor.given" للكل.
    الصلاحية: نفس إدارة الأجندة (رئيس اللجنة أو meetings.agenda.item.update عامة).
    """
    resolved = await _session_user_and_room(sid)
    if resolved is None:
        return {"ok": False, "error": "انتهت صلاحية جلسة الاتصال — أعيدي تحميل الصفحة."}
    user, meeting_id = resolved
    target_user_id = str((data or {}).get("user_id") or "")
    if not target_user_id:
        return {"ok": False, "error": "حددي العضو."}
    try:
        async with AsyncSessionLocal() as db:
            await meeting_chat_service.require_agenda_manage_access(db, actor=user, meeting_id=uuid.UUID(meeting_id))
    except (MeetingChatForbiddenError, MeetingChatNotFoundError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:
        logger.exception("floor.give: فشل غير متوقع — meeting_id=%s", meeting_id)
        return {"ok": False, "error": "تعذر إعطاء الكلمة بسبب خطأ بالخادم — حاولي مجددًا."}
    full_name = ""
    try:
        raw = await redis_client.hget(_hands_key(meeting_id), target_user_id)
        if raw:
            full_name = json.loads(raw).get("full_name", "")
        await redis_client.hdel(_hands_key(meeting_id), target_user_id)
    except Exception:  # noqa: BLE001
        logger.warning("floor.give: تعذّر تحديث الطابور بـRedis", exc_info=True)
    await sio.emit("hand.lowered", {"user_id": target_user_id}, room=_room(meeting_id))
    await sio.emit("floor.given", {"user_id": target_user_id, "full_name": full_name}, room=_room(meeting_id))
    return {"ok": True}


@sio.on("agenda.discussing")
async def agenda_discussing(sid: str, data: dict[str, Any] | None) -> dict[str, Any]:
    resolved = await _session_user_and_room(sid)
    if resolved is None:
        return {"ok": False, "error": "انتهت صلاحية جلسة الاتصال — أعيدي تحميل الصفحة."}
    user, meeting_id = resolved
    agenda_item_id = (data or {}).get("agenda_item_id")
    title = (data or {}).get("title")
    if not agenda_item_id or not title:
        return {"ok": False, "error": "بيانات بند الأجندة ناقصة."}
    # مؤقت البند اختياري (قرار لاما 2026-11-03): None = بدون مؤقت.
    duration_raw = (data or {}).get("duration_seconds")
    duration_seconds: int | None = None
    if duration_raw is not None:
        try:
            duration_seconds = int(duration_raw)
        except (TypeError, ValueError):
            return {"ok": False, "error": "مدة المؤقت غير صالحة."}
        if not _TIMER_MIN_SECONDS <= duration_seconds <= _TIMER_MAX_SECONDS:
            return {"ok": False, "error": "مدة المؤقت لازم تكون بين دقيقة و4 ساعات."}
    # إصلاح 2026-09-14 (بلاغ لاما): كان أي مشارك بالغرفة يقدر يبث هذا
    # الحدث، لا رئيس اللجنة فقط — راجعي require_agenda_manage_access
    # بـmeeting_chat_service.py للتفصيل الكامل. فشل الصلاحية هنا = خطأ
    # صريح تُعرَض للضاغط (الواجهة أصلًا تحجب الزر عن غير رئيس اللجنة،
    # فهذا خط دفاع ثانٍ لو استُدعي الحدث مباشرة — لكن لا يعود بعدها صمتًا).
    # إصلاح 2026-09-14 (بلاغ لاما الثاني — الزر لا يعطي رئيس اللجنة أي
    # مؤشر عند الضغط، كأنه لا يفعل شيئًا): هذا المعالج لم يكن يُرجع أي رد
    # إطلاقًا (نفس عِلّة chat_send قبل إصلاحها) — الواجهة تعتمد فقط على
    # استقبال بثّ "agenda.discussing" رجوعًا لتحديث حالتها، فأي فشل صامت
    # هنا (صلاحية، بند غير موجود، خطأ خادم غير متوقع) يعني عدم ظهور أي
    # شيء إطلاقًا لرئيس اللجنة. الآن يُرجع {ok, error?} دائمًا — راجعي
    # useMeetingRealtime.ts::announceDiscussing وMeetingRoom.tsx::
    # handleStartDiscussing لكيفية استخدام هذا الرد بالواجهة.
    try:
        async with AsyncSessionLocal() as db:
            await meeting_chat_service.require_agenda_manage_access(
                db, actor=user, meeting_id=uuid.UUID(meeting_id)
            )
    except (MeetingChatForbiddenError, MeetingChatNotFoundError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:
        logger.exception(
            "agenda.discussing: فشل غير متوقع أثناء التحقق من صلاحية إدارة الأجندة — "
            "meeting_id=%s user_id=%s",
            meeting_id,
            user.user_id,
        )
        return {"ok": False, "error": "تعذر بدء المناقشة بسبب خطأ بالخادم — حاولي مجددًا."}
    payload = {
        "agenda_item_id": agenda_item_id,
        "title": title,
        "started_at": _now_iso(),
        "duration_seconds": duration_seconds,
    }
    try:
        await redis_client.set(_discussing_key(meeting_id), json.dumps(payload, ensure_ascii=False), ex=_ROOM_STATE_TTL)
    except Exception:  # noqa: BLE001
        logger.warning("agenda.discussing: تعذّر حفظ البند الحالي بـRedis", exc_info=True)
    await sio.emit("agenda.discussing", payload, room=_room(meeting_id))
    return {"ok": True}


@sio.on("minutes.editing")
async def minutes_editing(sid: str, data: dict[str, Any] | None) -> None:
    """حدث عابر بحت (لا يُحفَظ) — راجعي تعليق meeting_live_socket القديم."""
    resolved = await _session_user_and_room(sid)
    if resolved is None:
        return
    user, meeting_id = resolved
    section_id = (data or {}).get("section_id")
    if not section_id:
        return
    await sio.emit(
        "minutes.editing",
        {"user_id": str(user.user_id), "full_name": user.full_name, "section_id": section_id},
        room=_room(meeting_id),
    )


@sio.on("minutes.updated")
async def minutes_updated(sid: str, data: dict[str, Any] | None) -> None:
    """يبثّ نسخة المحضر المحفوظة فعليًا (بعد نجاح PUT /minutes/sections
    عبر REST) لبقية الحاضرين — لا يكتب شيئًا هنا، بث فقط."""
    resolved = await _session_user_and_room(sid)
    if resolved is None:
        return
    user, meeting_id = resolved
    sections = (data or {}).get("sections")
    if not isinstance(sections, list):
        return
    await sio.emit(
        "minutes.updated",
        {"user_id": str(user.user_id), "full_name": user.full_name, "sections": sections},
        room=_room(meeting_id),
    )
