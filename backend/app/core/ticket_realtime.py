"""
الهدف:
التحديث اللحظي لمحادثة التذاكر (TKT-FR-024) على نفس خادم Socket.IO الحالي
(app/core/socketio_server.py) — namespace مستقل "/tickets"، فما يتأثر
اتصال الاجتماعات (namespace "/" اللي يشترط meeting_id).

المسؤولية:
- connect: التحقق من التوكن (نفس منطق قناة الاجتماع) ورفض حسابات الضيوف.
- ticket.subscribe / ticket.unsubscribe: الاشتراك بتذكرة بعد فحص الصلاحية
  (نفس resolve_viewer بالـREST). عضو الدعم ينضم أيضًا لقناة الدعم الخاصة
  بالتذكرة (للملاحظات الداخلية).
- emit_ticket_*: بث تنبيه خفيف بعد نجاح العملية بالـREST.

قرار التصميم (القسم 7 بالمواصفات — "socket.io للاستقبال فقط"):
البث يحمل المعرّفات فقط (ticket_id/message_id)، والواجهة تجلب البيانات من
الـREST اللي يطبّق الصلاحيات. فما فيه أي بيانات تتسرّب عبر القناة اللحظية،
والإرسال نفسه REST فلو انقطع الاتصال اللحظي ما يتأثر.

الغرف:
- ticket:{id}          — كل المشتركين (مقدّم الطلب والدعم): رسائل عامة وتغييرات الحالة.
- ticket:{id}:support  — الدعم فقط: الملاحظات الداخلية وتغييرات الأولوية/الإسناد.

جلسة DB قصيرة العمر لكل فحص (نفس قاعدة socketio_server).
"""

import logging
import uuid
from typing import Any

from app.core.socketio_server import _resolve_user_from_token, sio
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

NAMESPACE = "/tickets"


def _room(ticket_id: uuid.UUID | str) -> str:
    """غرفة كل المشتركين بالتذكرة."""
    return f"ticket:{ticket_id}"


def _support_room(ticket_id: uuid.UUID | str) -> str:
    """غرفة الدعم فقط بالتذكرة (الملاحظات الداخلية)."""
    return f"ticket:{ticket_id}:support"


@sio.on("connect", namespace=NAMESPACE)
async def tickets_connect(sid: str, environ: dict, auth: dict | None) -> bool:
    """
    الهدف: قبول اتصال قناة التذاكر بعد التحقق من التوكن.
    المدخلات: auth = {"token": "..."} من socket.io-client.
    المخرجات: True للقبول، False للرفض (توكن غير صالح، حساب موقوف، أو ضيف).
    التأثيرات الجانبية: حفظ المستخدم بجلسة Socket.IO (تحميل واحد عند الاتصال).
    """
    token = (auth or {}).get("token")
    if not token:
        return False
    user = await _resolve_user_from_token(token)
    if user is None or user.is_guest:
        return False
    await sio.save_session(sid, {"user": user}, namespace=NAMESPACE)
    return True


@sio.on("ticket.subscribe", namespace=NAMESPACE)
async def tickets_subscribe(sid: str, data: dict[str, Any] | None) -> dict[str, Any]:
    """
    الهدف: الاشتراك بتحديثات تذكرة واحدة.

    المدخلات: {"ticket_id": "..."}.
    المخرجات (ack): {"ok": true, "viewer": "requester"|"support"} أو {"ok": false}.

    قواعد العمل: نفس فحص الـREST (resolve_viewer) — صاحب التذكرة أو الدعم.
    أي رفض يرجع ok=false بدون تفاصيل (ما ينكشف وجود التذكرة).
    """
    from app.services import ticket_service

    try:
        session = await sio.get_session(sid, namespace=NAMESPACE)
        user = session["user"]
        ticket_id = uuid.UUID(str((data or {}).get("ticket_id")))
    except (KeyError, ValueError, TypeError):
        return {"ok": False}
    try:
        async with AsyncSessionLocal() as db:
            _, viewer = await ticket_service.get_ticket(db, actor=user, ticket_id=ticket_id)
    except (ticket_service.TicketNotFoundError, ticket_service.TicketForbiddenError):
        return {"ok": False}
    await sio.enter_room(sid, _room(ticket_id), namespace=NAMESPACE)
    if viewer == "support":
        await sio.enter_room(sid, _support_room(ticket_id), namespace=NAMESPACE)
    return {"ok": True, "viewer": viewer}


@sio.on("ticket.unsubscribe", namespace=NAMESPACE)
async def tickets_unsubscribe(sid: str, data: dict[str, Any] | None) -> dict[str, Any]:
    """الهدف: إلغاء الاشتراك بتذكرة (عند مغادرة صفحتها). المخرجات: {"ok": true}."""
    try:
        ticket_id = uuid.UUID(str((data or {}).get("ticket_id")))
    except (ValueError, TypeError):
        return {"ok": False}
    await sio.leave_room(sid, _room(ticket_id), namespace=NAMESPACE)
    await sio.leave_room(sid, _support_room(ticket_id), namespace=NAMESPACE)
    return {"ok": True}


async def emit_ticket_message(ticket_id: uuid.UUID, message_id: uuid.UUID, *, is_internal: bool) -> None:
    """
    الهدف: تنبيه "وصلت رسالة" بعد حفظها.
    قاعدة العمل: الملاحظة الداخلية تُبث لغرفة الدعم فقط، فمقدّم الطلب ما
    يعرف حتى إن فيه ملاحظة انكتبت.
    لا يرفع استثناء (البث إضافة — العملية نفسها نجحت).
    """
    room = _support_room(ticket_id) if is_internal else _room(ticket_id)
    try:
        await sio.emit(
            "ticket.message",
            {"ticket_id": str(ticket_id), "message_id": str(message_id)},
            room=room,
            namespace=NAMESPACE,
        )
    except Exception:  # noqa: BLE001
        logger.warning("تعذّر بث رسالة تذكرة لحظيًا", exc_info=True)


async def emit_ticket_updated(ticket_id: uuid.UUID, *, support_only: bool) -> None:
    """
    الهدف: تنبيه "تغيّرت التذكرة" (حالة، إسناد، أولوية...) لتحديث العرض.
    قاعدة العمل: تغيير الحالة للكل؛ الإسناد والأولوية والنوع والوحدة للدعم فقط.
    لا يرفع استثناء.
    """
    room = _support_room(ticket_id) if support_only else _room(ticket_id)
    try:
        await sio.emit("ticket.updated", {"ticket_id": str(ticket_id)}, room=room, namespace=NAMESPACE)
    except Exception:  # noqa: BLE001
        logger.warning("تعذّر بث تحديث تذكرة لحظيًا", exc_info=True)
