"""
الهدف:
إعداد بيئة الاختبار المشتركة (Fixtures) — تشغيل التطبيق مقابل قاعدة
بيانات PostgreSQL محلية حقيقية (وليس SQLite)، لأن الـ schema يعتمد على
ميزات خاصة بـ Postgres (UUID, ENUM, JSONB, Partial Unique Index).

المسؤولية:
- تنظيف الجداول قبل كل اختبار (بدل إعادة إنشاء الـ schema كل مرة، توفيرًا
  للوقت — الـ schema نفسه ثابت وتم تطبيقه يدويًا عبر db/migrations).
- توفير httpx.AsyncClient متصل بتطبيق FastAPI مباشرة (ASGITransport) بدون
  الحاجة لتشغيل خادم HTTP فعلي.
- توفير مستخدم super_admin جاهز لاختبارات تتطلب صلاحيات.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from sqlalchemy import select

from app.core.redis_client import redis_client
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, engine
from app.main import app
from app.models.role import Role
from app.models.user import User


@pytest_asyncio.fixture(autouse=True)
async def _fresh_async_resources() -> AsyncGenerator[None, None]:
    """
    محرك SQLAlchemy async وعميل Redis كائنان مشتركان (singleton) يُنشآن
    عند تحميل الوحدة (module import)، ويربطان اتصالاتهما بحلقة الحدث
    (event loop) التي استخدمتهما أول مرة. بما أن pytest-asyncio يفتح حلقة
    حدث جديدة لكل اختبار (function-scoped)، يجب التخلص من أي اتصالات
    متبقية من حلقة سابقة (مغلقة الآن) قبل بداية كل اختبار، وإلا فشلت
    الاختبارات التالية للأول بخطأ "Event loop is closed" أو
    "attached to a different loop".

    التخلص (dispose) يجب أن يحدث في نهاية الاختبار الحالي (قبل إغلاق حلقة
    الحدث الخاصة به)، وليس في بداية الاختبار التالي — وإلا ستحاول عملية
    الإغلاق نفسها استخدام حلقة حدث أُغلقت مسبقًا.
    """
    yield
    await engine.dispose()
    await redis_client.aclose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(_fresh_async_resources: None) -> AsyncGenerator[None, None]:
    """
    تفريغ كل الجداول قبل كل اختبار لضمان عزل تام بين الاختبارات.

    roles/permissions/role_permissions مستثناة من TRUNCATE عمدًا — هذه
    بيانات كتالوج/بذر (seed) تُطبَّق مرة واحدة عبر db/migrations وتُستخدم
    من كل الاختبارات (خصوصًا الأدوار النظامية الخمسة)؛ حذفها بالكامل يكسر
    كل اختبار يعتمد على وجودها. الأدوار المخصَّصة (is_system=false) التي
    تُنشئها اختبارات role_service تُحذف يدويًا بدل ذلك.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE password_reset_tokens, audit_logs, users, departments "
                "RESTART IDENTITY CASCADE"
            )
        )
        await conn.execute(text("DELETE FROM roles WHERE is_system = false"))
    yield


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def roles_by_name() -> dict[str, str]:
    """
    خريطة {اسم الدور: role_id} لكل الأدوار النظامية الخمسة — تُستخدم في
    الاختبارات لبناء payloads تحتاج role_id بدل اسم دور ثابت (بما أن
    الأدوار أصبحت ديناميكية).
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Role))
        return {r.name: str(r.role_id) for r in result.scalars().all()}


@pytest_asyncio.fixture
async def super_admin_user(roles_by_name: dict[str, str]) -> User:
    """إنشاء مستخدم super_admin مباشرة في القاعدة (بدون المرور عبر API)."""
    async with AsyncSessionLocal() as db:
        user = User(
            first_name="لمى",
            middle_name="تجريبي",
            last_name="الاختبار",
            username="super_admin_test",
            email="super_admin_test@example.com",
            password_hash=hash_password("StrongPass1"),
            role_id=roles_by_name["super_admin"],
            dep_id=None,
            must_change_password=False,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest_asyncio.fixture
async def super_admin_token(client: AsyncClient, super_admin_user: User) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "super_admin_test", "password": "StrongPass1"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def auth_headers(super_admin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {super_admin_token}"}
