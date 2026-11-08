"""
الهدف:
سياق الطلب الحالي (Request Context) — "من" ينفّذ الطلب و"بأي صفة" (دوره
الحالي)، متاح لأي طبقة بدون تمريره يدويًا عبر كل استدعاء.

المسؤولية:
- current_actor: (user_id, active_role_id) للمستخدم المصادَق عليه بالطلب
  الحالي. تُضبط بـcore.dependencies.get_current_user فقط.
- RequestContextMiddleware: يصفّر السياق في بداية كل طلب HTTP ويعيده بعده،
  فلا يتسرّب فاعل طلب سابق لطلب لاحق (مهم خصوصًا مع httpx.ASGITransport
  بالاختبارات، اللي يشغّل كل الطلبات بنفس المهمة).

المستهلك الحالي الوحيد: audit_service.log_action — يسجّل الصفة اللي نُفّذت
بها العملية (audit_logs.actor_role_id، migration 0046 — تعدد الأدوار) بدون
تعديل عشرات الاستدعاءات القائمة لـlog_action.

ملاحظات:
- ContextVar آمن مع async: كل طلب يشتغل بنسخة سياق مستقلة.
- لا يُستخدم هذا السياق لأي قرار صلاحيات — الصلاحيات تبقى من current_user
  المحمَّل من قاعدة البيانات (core.dependencies). هذا للتسجيل فقط.
"""

import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Receive, Scope, Send

current_actor: ContextVar[tuple[uuid.UUID, uuid.UUID | None] | None] = ContextVar(
    "current_actor", default=None
)


class RequestContextMiddleware:
    """
    Middleware ASGI خام (بدون BaseHTTPMiddleware — أخف ولا يغلّف الاستجابة)
    يبدأ كل طلب بسياق فاعل فارغ ويعيده لحالته السابقة بعد انتهاء الطلب.
    التكلفة: ضبط/إعادة ContextVar واحد لكل طلب — بلا أي I/O.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        token = current_actor.set(None)
        try:
            await self.app(scope, receive, send)
        finally:
            current_actor.reset(token)
