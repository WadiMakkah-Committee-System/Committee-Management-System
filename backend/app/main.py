"""
الهدف:
نقطة الدخول الرئيسية لتطبيق FastAPI — تجميع الإعدادات، الـ Middleware
(CORS)، ومعالجات الأخطاء العامة، وربط راوترات API.

المسؤولية:
- إنشاء تطبيق FastAPI واحد وتسجيل كل الراوترات عليه.
- تفعيل CORS للسماح للواجهة الأمامية (React) بالاتصال.
- توفير مسار /health بسيط للتحقق من أن الخدمة تعمل (Health Check).
"""

from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.scheduler import start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # المهمة المجدولة لتذكيرات المهام وتنبيهات التأخر (راجعي app/core/scheduler.py)
    scheduler_task = start_scheduler()
    yield
    scheduler_task.cancel()

from app.core.socketio_server import sio

app = FastAPI(
    title="نظام إدارة اللجان والاجتماعات - API",
    description="Committee & Meeting Management System — Backend API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: يُقيَّد لاحقًا لنطاقات الواجهة الأمامية الفعلية فقط عند النشر
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.ENVIRONMENT == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """فحص بسيط للتأكد من أن الخدمة تعمل — لا يتحقق من الاتصال بقاعدة البيانات."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}


# تحديث 2026-09-10 (قرار لاما — استبدال قناة الاجتماع/المحضر اللحظية
# بـSocket.IO بدل WebSocket الخام): راجعي app/core/socketio_server.py
# لمعالجات الأحداث. جرّبت أولًا app.mount("/socket.io", ...) العادي —
# تبيّن إنه غير موثوق مع Socket.IO تحديدًا (مشكلة معروفة موثّقة بمستودع
# FastAPI نفسه: قص المسار عبر mount يتعارض مع فحص socketio_path الداخلي
# لمكتبة python-socketio، يسبب أخطاء CORS/اتصال غريبة). الطريقة الموثّقة
# رسميًا بديلًا: تغليف تطبيق FastAPI بالكامل داخل socketio.ASGIApp (بدل
# تركيبه تحته) عبر other_asgi_app — والنتيجة socket_app هي الهدف الفعلي
# لتشغيل uvicorn الآن، بدل app مباشرة (راجعي رسالتي لاما — لازم أمر
# التشغيل يتغيّر لـ"uvicorn app.main:socket_app --reload").
socket_app = socketio.ASGIApp(sio, other_asgi_app=app, socketio_path="socket.io")
