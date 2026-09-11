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
