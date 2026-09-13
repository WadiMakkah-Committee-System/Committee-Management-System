"""
الهدف:
نقطة الدخول الرئيسية لتطبيق FastAPI — تجميع الإعدادات، الـ Middleware
(CORS)، ومعالجات الأخطاء العامة، وربط راوترات API.

المسؤولية:
- إنشاء تطبيق FastAPI واحد وتسجيل كل الراوترات عليه.
- تفعيل CORS للسماح للواجهة الأمامية (React) بالاتصال.
- توفير مسار /health بسيط للتحقق من أن الخدمة تعمل (Health Check).
"""

import time as _perf_time
from contextlib import asynccontextmanager

import socketio
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.gzip import GZipMiddleware

from app.api.v1.router import api_router
from app.core import perf_probe
from app.core.config import settings
from app.core.scheduler import start_scheduler
from app.db.session import get_db


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

# CORS: مفتوح بالتطوير، ومقيَّد بالإنتاج لنطاقات settings.CORS_ORIGINS
# (تحديث 2026-09-12 — نشر المنصة على استضافة عامة: كانت القائمة هنا
# فارغة تمامًا بالإنتاج قبل هذا التحديث، أي كل الطلبات كانت تُرفض).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.ENVIRONMENT == "development" else settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# تحديث 2026-09-12: ضغط الاستجابات (gzip) لأي استجابة أكبر من 1KB —
# يقلل حجم البيانات المنقولة عبر الشبكة (خصوصًا قوائم JSON الطويلة)،
# تحسين بسيط وآمن تمامًا، لا يمس أي منطق عمل.
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(api_router)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """فحص بسيط للتأكد من أن الخدمة تعمل — لا يتحقق من الاتصال بقاعدة البيانات."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}


# ============================================================
# تحقيق أداء لاما 2026-09-12 — Middleware + نقطتان مؤقتتان معزولتان
# ============================================================
# الهدف الوحيد: قياس فعلي (لا افتراض) لمكان الـ20-30 ثانية الملحوظة
# بالمتصفح. كل شيء بهذا القسم مؤقت ويُحذف فور تحديد السبب الجذري.


@app.middleware("http")
async def perf_trace_middleware(request: Request, call_next):
    """يلف كل طلب HTTP: يبدأ تتبّع المراحل (perf_probe.start_trace)،
    ويقيس الزمن الكلي من استلام الطلب حتى جهوز الاستجابة (قبل أي
    buffering/تشفير إضافي من Render/الشبكة نفسها — هذا الفرق تحديدًا هو
    ما يحدد هل العائق داخل تطبيقنا أو خارجه بالطبقات الأدنى: proxy/
    keep-alive/cold start). يطبع سطر PERF واحد بـstdout (يظهر بـRender
    Logs مباشرة) + يرجع X-Perf-Trace/X-Perf-Total-Ms كـheaders."""
    perf_probe.start_trace()
    t0 = _perf_time.perf_counter()
    response = await call_next(request)
    total_ms = round((_perf_time.perf_counter() - t0) * 1000, 1)
    trace_str = perf_probe.trace_summary()
    response.headers["X-Perf-Total-Ms"] = str(total_ms)
    if trace_str:
        # إصلاح 2026-09-13 (اكتُشف أثناء تحقيق N+1 الثاني): القص كان على
        # 4000 حرف فقط، بينما print() بالأسفل يسجّل الـtrace كاملًا بدون
        # قص بالـLogs — لطلب فيه ~40 استعلام، الـmarker واستعلامات الإصلاح
        # كانت تقع بعد نقطة القص، فتظهر نتيجة NEW_CODE_CONFIRMED: False
        # خاطئة بفحص لاما رغم أن الكود الصحيح فعليًا كان يشتغل (تأكَّد هذا
        # من Render Logs الخام وقتها). رفع الحد هنا يخلي X-Perf-Trace
        # نفسه مطابقًا لما يُسجَّل بالـLogs لأي تتبّع معقول الحجم.
        response.headers["X-Perf-Trace"] = trace_str[:15000]
    print(
        f"[PERF] {request.method} {request.url.path} total={total_ms}ms | {trace_str}",
        flush=True,
    )
    return response


@app.get("/performance-test", tags=["Perf-Debug"])
async def performance_test() -> dict[str, str]:
    """بدون DB/Redis/Auth إطلاقًا — يعزل HTTP overhead المحض + سلوك
    Render/proxy/cold-start عن أي طبقة أخرى بالتطبيق. إن كان هذا وحده
    بطيئًا، فالسبب خارج منطق تطبيقنا كليًا (شبكة/proxy/worker/cold start)."""
    return {"status": "ok"}


@app.get("/performance-db-test", tags=["Perf-Debug"])
async def performance_db_test(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """بدون Auth/Redis — استعلام SELECT 1 وحيد فقط. يعزل وقت الحصول على
    اتصال قاعدة بيانات + تنفيذ أبسط استعلام ممكن عن أي منطق عمل فعلي."""
    with perf_probe.timed("db_test.select_1"):
        await db.execute(text("SELECT 1"))
    return {"status": "ok"}


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
