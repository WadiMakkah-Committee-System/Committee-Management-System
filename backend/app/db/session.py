"""
الهدف:
إدارة الاتصال بقاعدة البيانات (PostgreSQL) عبر SQLAlchemy Async Engine،
وتوفير جلسات (Sessions) لكل طلب HTTP بشكل معزول وآمن.

المسؤولية:
- إنشاء Engine واحد يُعاد استخدامه طوال عمر التطبيق (Connection Pooling).
- توفير async generator (get_db) يُستخدم كـ FastAPI Dependency، يفتح جلسة
  لكل طلب ويغلقها تلقائيًا بعد انتهائه (حتى لو حصل استثناء).

الاعتماديات:
SQLAlchemy (async) + asyncpg كـ driver، app.core.config لقراءة DATABASE_URL.

ملاحظات:
- الاتصال بقاعدة الإنتاج (Supabase) يجب أن يكون عبر قناة تتجاوز RLS
  (Service Role / Direct Connection) لأن فرض الصلاحيات (RBAC) مسؤولية
  الـ Backend فقط، حسب قاعدة الأمان في CLAUDE.md — الـ RLS مفعّل على
  مستوى القاعدة كطبقة حماية إضافية ضد أي وصول مباشر عبر REST API العام.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,  # يتحقق من صلاحية الاتصال قبل استخدامه (يتجنب اتصالات ميتة)
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI Dependency: تفتح جلسة قاعدة بيانات جديدة لكل طلب، وتضمن إغلاقها
    دائمًا (حتى عند حدوث خطأ)، مع التراجع التلقائي (rollback) عند الفشل.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
