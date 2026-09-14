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

import logging
import uuid
from typing import Any

import socketio

from app.core.config import settings
from app.core.redis_client import is_session_valid, touch_session
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
    # إصلاح 2026-09-14 (بلاغ لاما — Bug 2: اسم المشارك بمربّع الفيديو يظهر
    # كرقم/معرّف غريب بدل اسمها الحقيقي، مثال ليليان): نفس منطق
    # presence.roster أدناه بالضبط، لكن لـ"من هو صاحب أي agora_uid" —
    # راجعي تعليق video_uid تحت لتفصيل الجذر الحقيقي للمشكلة.
    existing_video_uids: list[dict[str, Any]] = []
    for other_sid, _eio_sid in sio.manager.get_participants("/", room):
        try:
            other_session = await sio.get_session(other_sid)
        except KeyError:
            continue
        other_user: User | None = other_session.get("user")
        if other_user is not None:
            existing_user_ids.add(str(other_user.user_id))
            other_agora_uid = other_session.get("agora_uid")
            if other_agora_uid is not None:
                existing_video_uids.append(
                    {
                        "user_id": str(other_user.user_id),
                        "full_name": other_user.full_name,
                        "agora_uid": other_agora_uid,
                    }
                )

    sio.enter_room(sid, room)

    if existing_user_ids:
        await sio.emit("presence.roster", {"user_ids": list(existing_user_ids)}, to=sid)
    if existing_video_uids:
        await sio.emit("video.roster", {"entries": existing_video_uids}, to=sid)

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


# إصلاح 2026-09-14 (بلاغ لاما — Bug 2: اسم المشارك بمربّع الفيديو يظهر
# كرقم غريب بدل اسمها الحقيقي): الجذر الحقيقي ليس بربط بيانات المستخدم
# (participants يرجع أصلًا first_name/last_name كاملة — راجعي
# schemas/meeting.py::MeetingOut.participants) بل بمكوّن الفيديو نفسه —
# MeetingStage.tsx::nameFor يبحث بخريطة participantNames المبنية بمفتاح
# user_id (UUID من قاعدة البيانات)، بينما المفتاح الفعلي لكل مربّع فيديو
# بمكتبة Agora هو agora_uid (رقم عشوائي 6 خانات مُولَّد لكل جلسة انضمام —
# راجعي meeting_service.join_meeting) — لا علاقة له بـuser_id إطلاقًا،
# فالبحث يفشل دائمًا لأي مشارك (لا لليليان فقط)، ويظهر بدلًا منه نص
# احتياطي "مشارك #<agora_uid>". الحل: بث ربط user_id↔agora_uid لحظيًا عبر
# نفس قناة Socket.IO الموجودة أصلًا (بنفس نمط presence.roster/joined
# تمامًا، بلا أي بنية جديدة) فور انضمام العميل فعليًا لقناة Agora —
# راجعي useAgoraConnection.ts وuseMeetingRealtime.ts بالفرونت للطرف الآخر.
@sio.on("video.uid")
async def video_uid(sid: str, data: dict[str, Any] | None) -> None:
    resolved = await _session_user_and_room(sid)
    if resolved is None:
        return
    user, meeting_id = resolved
    agora_uid = (data or {}).get("agora_uid")
    if agora_uid is None:
        return
    try:
        session = await sio.get_session(sid)
    except KeyError:
        return
    session["agora_uid"] = agora_uid
    await sio.save_session(sid, session)
    await sio.emit(
        "video.uid",
        {"user_id": str(user.user_id), "full_name": user.full_name, "agora_uid": agora_uid},
        room=_room(meeting_id),
    )


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
async def agenda_discussing(sid: str, data: dict[str, Any] | None) -> None:
    resolved = await _session_user_and_room(sid)
    if resolved is None:
        return
    user, meeting_id = resolved
    agenda_item_id = (data or {}).get("agenda_item_id")
    title = (data or {}).get("title")
    if not agenda_item_id or not title:
        return
    # إصلاح 2026-09-14 (بلاغ لاما): كان أي مشارك بالغرفة يقدر يبث هذا
    # الحدث، لا رئيس اللجنة فقط — راجعي require_agenda_manage_access
    # بـmeeting_chat_service.py للتفصيل الكامل. فشل الصلاحية هنا = تجاهل
    # صامت (نفس نمط chat_send أعلاه) — الواجهة أصلًا لا تعرض زر الضغط
    # إلا لرئيس اللجنة، فهذا فقط خط دفاع ثانٍ ضد استدعاء الحدث مباشرة.
    try:
        async with AsyncSessionLocal() as db:
            await meeting_chat_service.require_agenda_manage_access(
                db, actor=user, meeting_id=uuid.UUID(meeting_id)
            )
    except (MeetingChatForbiddenError, MeetingChatNotFoundError):
        return
    await sio.emit(
        "agenda.discussing",
        {"agenda_item_id": agenda_item_id, "title": title},
        room=_room(meeting_id),
    )


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
