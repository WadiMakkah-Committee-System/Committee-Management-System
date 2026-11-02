"""
الهدف:
قناة الاجتماع/المحضر اللحظية — Socket.IO بدل WebSocket الخام (app/core/
meeting_realtime.py سابقًا). قرار لاما 2026-09-10: تبديل طبقة النقل
لواحدة أنضج (إعادة اتصال تلقائية + Rooms جاهزة بدل connection_manager
اليدوي) — نفس بالضبط المنطق/الأحداث القديمة (رفع يد + بند أجندة قيد
المناقشة + تعاون تحرير المحضر)، فقط بآلية نقل مختلفة. (المحادثة النصية
أُزيلت 2026-11-02 — الأعضاء يستخدمون شات Microsoft Teams.)

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

import logging
import uuid
from typing import Any

import socketio

from app.core.config import settings
from app.core.redis_client import is_session_valid, touch_session
from app.core.security import InvalidTokenError, decode_token
from app.db.session import AsyncSessionLocal
from app.models.user import User, UserStatus
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
    # hand.raised/agenda.discussing/minutes.updated —
    # كل بث لاحق عبر room=room (وكلها تمر بنفس هذا المسار) كان لا يصل أبدًا
    # لهذا الاتصال تحديدًا (بينما الرسائل المباشرة to=sid، مثل presence.roster
    # أعلاه، كانت تصل بشكل طبيعي لأنها لا تعتمد على عضوية الغرفة). الإصلاح:
    # إضافة await فقط — لا تغيير بالمنطق.
    await sio.enter_room(sid, room)

    if existing_user_ids:
        await sio.emit("presence.roster", {"user_ids": list(existing_user_ids)}, to=sid)

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


@sio.on("hand.raise")
async def hand_raise(sid: str, _data: dict[str, Any] | None = None) -> None:
    resolved = await _session_user_and_room(sid)
    if resolved is None:
        return
    user, meeting_id = resolved
    await sio.emit(
        "hand.raised",
        {"user_id": str(user.user_id), "full_name": user.full_name},
        room=_room(meeting_id),
    )


@sio.on("hand.lower")
async def hand_lower(sid: str, _data: dict[str, Any] | None = None) -> None:
    resolved = await _session_user_and_room(sid)
    if resolved is None:
        return
    user, meeting_id = resolved
    await sio.emit("hand.lowered", {"user_id": str(user.user_id)}, room=_room(meeting_id))


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
    await sio.emit(
        "agenda.discussing",
        {"agenda_item_id": agenda_item_id, "title": title},
        room=_room(meeting_id),
    )
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
