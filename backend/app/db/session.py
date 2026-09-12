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

تحديث 2026-09-09 (بلاغ لاما — سلسلة أخطاء متتالية بسبب إعداد الـ Pooler،
راجعي كل القرارات موثّقة بالترتيب، تصحيح أخير بالبند 3 بعد تجربة فعلية):

1) EMAXCONNSESSION "max clients reached in session mode... pool_size: 15"
   من Supavisor: تبيّن إن DATABASE_URL بـ.env كان يشير فعليًا للمنفذ 5432
   (وضع Session — حصة عملاء متزامنين صغيرة وثابتة). صُحِّح المنفذ بـ.env
   إلى 6543 (وضع Transaction — حصة أكبر بكثير).

2) بعد التحويل لوضع Transaction، ظهر خطأ: asyncpg.exceptions.
   InvalidSQLStatementNameError ("prepared statement ... does not exist").
   السبب الدقيق: SQLAlchemy لدى asyncpg يخزّن كل جملة مُجهَّزة (PREPARE)
   بذاكرة داخلية خاصة بكائن الاتصال نفسه (dialect-level cache، حجمه
   الافتراضي 100 — منفصل تمامًا عن معامل asyncpg الأصلي statement_cache_size
   المستخدَم أدناه، فخ توثيقي شائع لأنهما يبدوان نفس الشي). بوضع
   Transaction، PgBouncer/Supavisor يبدّل اتصال السيرفر الفعلي خلف
   الكواليس بين كل معاملة منفصلة على نفس اتصال العميل — فجملة مُجهَّزة
   بذاكرة SQLAlchemy من معاملة سابقة تشير لاسم غير موجود إطلاقًا على
   السيرفر الفعلي الجديد الذي بدّله الـ Pooler.

   محاولتي الأولى هنا كانت NullPool (بلا أي Pooling محلي بـSQLAlchemy —
   كل طلب يفتح اتصالًا فعليًا جديدًا بالكامل بقاعدة البيانات). هذا فعلًا
   يمنع الخطأ (كل اتصال جديد بذاكرة فارغة، فلا يوجد كاش قديم يشير لسيرفر
   قديم) — لكنه سبب مشكلة أخطر: صفحة المحضر وحدها تفتح ٥-٦ طلبات متزامنة
   (تفاصيل الاجتماع + اللجنة + المحضر + القوالب + البنود المستخرجة +
   WebSocket)، فكل صفحة تفتح ٥-٦ اتصالات TCP/TLS جديدة كاملة لسيرفر
   Supabase البعيد (AWS eu-west-1) بنفس اللحظة — فعليًا تأكّدنا من هذا:
   تبويب Network بمتصفح لاما أظهر كل الطلبات (حتى طلبات CORS Preflight
   اللي ما تلمس القاعدة أصلًا) عالقة "Pending" لأكثر من 4 دقائق، وبنفس
   الوقت pg_stat_activity ما فيه ولا استعلام واحد نشط — يعني التعليق كان
   قبل الوصول لقاعدة البيانات أصلًا، بمرحلة إنشاء الاتصال نفسها (شبكة/
   TLS)، وهذا بالضبط ما يفسّر "الباك يعلّق بالكامل" اللي وصفته لاما.

   الحل الصحيح (نفس توثيق SQLAlchemy، القسم الأول "Prepared Statement
   Cache" مباشرة، أبسط من NullPool وما يحتاج التضحية بإعادة استخدام
   الاتصالات): تعطيل ذاكرة SQLAlchemy الداخلية نفسها عبر
   prepared_statement_cache_size=0 (معامل DBAPI مختلف تمامًا عن
   statement_cache_size — كلاهما مطلوبان معًا هنا). بهذا، SQLAlchemy ما
   يخزّن/يُعيد استخدام أي جملة مُجهَّزة بين طلبين منفصلين إطلاقًا، فلا
   يهم أبدًا هل الـ Pooler بدّل السيرفر الفعلي خلف الكواليس أو لا — مع
   إبقاء Pooling محلي طبيعي (QueuePool، حجم محدود صريح) فتُعاد الاتصالات
   الفعلية نفسها بين الطلبات المتتالية بدل فتح اتصال شبكي جديد بالكامل
   في كل مرة.

3) pool_size/max_overflow صريحان (5+5=10 حد أقصى) بدل الافتراضي (5+10=15
   يستهلك كامل حصة Supavisor وحده)، مع pool_pre_ping=True (يتحقق من صلاحية
   الاتصال المُعاد استخدامه بسرعة بدل اتصال ميت).

4) server_settings.idle_in_transaction_session_timeout=30s: شبكة أمان
   مستوى القاعدة نفسها، مستقلة عن أي خطأ مستقبلي بكود التطبيق. أي جلسة
   تعلق "idle in transaction" لأي سبب تُقتَل تلقائيًا من Postgres بعد 30
   ثانية بدل ما تبقى محجوزة للأبد. هذا الحل "على مستوى النظام كامله" اللي
   طلبته لاما 2026-09-09.
"""

import time as _perf_time
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core import perf_probe
from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    # تحديث 2026-09-10 (ب): التراجع عن NullPool (كان تعديل سابق بنفس اليوم) بعد بلاغ لاما: بعد تفعيل NullPool لحل DuplicatePreparedStatementError، صفحة المحضر رجعت تظهر فارغة (Skeleton رمادي معلّق للأبد). تبيّن أن هذا بالضبط العارض الموثّق أعلاه بتعليق 2026-09-09 البند (2): NullPool يفتح اتصال TCP/TLS جديداً بالكامل بكل طلب، وصفحة المحضر وحدها تطلق ٥-٦ طلبات متزامنة (اجتماع/لجنة/محضر/قوالب/بنود مستخرجة) فتعلق الطلبات بانتظار اتصالات جديدة بدل إعادة استخدام Pool محلي جاهز — وهو بالضبط سبب رفض NullPool يوم 2026-09-09 لصالح QueuePool بحجم صغير صريح (راجعي أعلاه). يعني تفعيل NullPool اليوم كان تراجعًا غير مقصود عن إصلاح الأمس.
    #
    # الحل المدمج (يحل المشكلتين معاً بدل التضحية بإحداهما): العودة لQueuePool محدود صراحة (كإصلاح 2026-09-09) — يمنع عاصفة اتصالات جديدة لكل صفحة — + pool_recycle قصير (5 دقائق) يجبر SQLAlchemy على التخلص من أي كائن اتصال asyncpg بعد هذه المدة واستبداله بآخر جديد، بدل إبقائه حيًا لساعات. هذا يحد من نفس سبب تصادم اسم الجملة المُجهّزة (عدّاد asyncpg الداخلي لكائن اتصال طويل العمر يتصادم مع سيرفر فعلي بدّله Supavisor) دون تكلفة فتح اتصال شبكي كامل بكل طلب مثل NullPool. مع إبقاء prepared_statement_cache_size=0/statement_cache_size=0 كما هي لمنع إعادة استخدام جملة مُجهّزة قديمة أيضًا.
    #
    # ملاحظة صريحة للاما: هذا حل وسط مبني على التوثيق المتاح، ليس ضمانًا رياضيًا مئة بالمئة أن DuplicatePreparedStatementError لن يعود إطلاقًا — إن عاد بعد هذا فالخطوة التالية تقليل pool_recycle أكثر (مثلاً دقيقتين)، وليس العودة لNullPool.
    # تحديث 2026-09-12 (تحقيق أداء لاما — طلبات 20-30 ثانية رغم أن كل
    # استعلام يُنفَّذ بأقل من 1.4 ثانية حسب pg_stat_statements): تبيّن أن
    # .env كان لا يزال يشير للمنفذ 5432 (وضع Session بـSupavisor، حصة
    # عملاء متزامنين صغيرة وثابتة — نفس الوضع اللي سبّب خطأ
    # EMAXCONNSESSION "pool_size: 15" الموثّق أعلاه بتعليق 2026-09-09،
    # رغم أن ذاك التعليق يصف التحويل لـ6543 كحل — يبدو إنه لم يُطبَّق
    # فعليًا وقتها أو رجع لاحقًا لـ5432 بالخطأ). مع أن Pool المحلي هنا
    # محدود بـ10 اتصالات كحد أقصى، فهو أصلًا يحجز حتى 10 من الـ15 عميل
    # المتاحين بوضع Session لنفسه وحده باستمرار (يُعاد تدويرها كل 5
    # دقائق فقط عبر pool_recycle، مو عند كل طلب) — يترك هامشًا ضئيلًا
    # جدًا. وبما أن كل صفحة تطلق 15-40 طلب متزامن، وكل طلب مصادَق عليه
    # يحتاج اتصال قاعدة بيانات واحد على الأقل عبر get_current_user قبل
    # ما يوصل لمنطق الـ endpoint نفسه، فالطلبات تنتظر دورها للحصول على
    # اتصال (محليًا بـQueuePool، وربما بوضع Session نفسه بـSupavisor) —
    # وهذا الانتظار غير مرئي إطلاقًا لـpg_stat_statements (يقيس فقط وقت
    # تنفيذ الاستعلام بعد ما يبدأ، مو وقت الانتظار قبله). التصحيح: إرجاع
    # المنفذ لـ6543 (وضع Transaction، حصة أكبر بكثير من Supavisor مخصَّصة
    # بالضبط لهذا النمط — طلبات قصيرة كثيرة متزامنة) بـ.env — مع إبقاء
    # prepared_statement_cache_size=0/statement_cache_size=0 كما هي بالضبط
    # لأنها هي الحل الموثّق أعلاه (تعليق 2026-09-09 البند 2) لمشكلة
    # DuplicatePreparedStatementError اللي كانت سبب مغادرة 6543 أول مرة —
    # فالتحويل الآن للمنفذ 6543 لا يعيد ذاك الخطأ. رفع pool_size/
    # max_overflow من 5+5 إلى 10+10 (20 كحد أقصى) بشكل متحفظ نسبةً لـ60
    # (SHOW max_connections على قاعدة Postgres نفسها)، وبما إن Transaction
    # mode لا يحجز عميل Session مخصَّص لكل اتصال محلي مثل ما كان يحصل
    # بوضع Session.
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=10,
    pool_recycle=300,
    connect_args={
        "prepared_statement_cache_size": 0,
        "statement_cache_size": 0,
        "server_settings": {"idle_in_transaction_session_timeout": "30000"},
    },
)

# ============================================================
# تحقيق أداء لاما 2026-09-12 — Event Hooks على مستوى الـ Engine نفسه
# ============================================================
# بدل تعديل كل خدمة على حدة لقياس كل استعلام يدويًا: هذي event hooks
# رسمية بتوثيق SQLAlchemy (before/after_cursor_execute لكل جملة SQL
# فعلية تُنفَّذ عبر هذا الـ engine، وconnect/checkout على مستوى الـ Pool
# نفسه) — تلتقط تلقائيًا كل استعلام بأي طلب يمر عبر هذا الملف، بدون لمس
# منطق أي خدمة. مؤقتة، تُحذف بعد التحقيق.


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _perf_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._perf_query_t0 = _perf_time.perf_counter()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _perf_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    t0 = getattr(context, "_perf_query_t0", None)
    if t0 is None:
        return
    dur_ms = round((_perf_time.perf_counter() - t0) * 1000, 1)
    short_sql = " ".join(statement.split())[:70]
    perf_probe.mark(f"sql: {short_sql}", dur_ms=dur_ms)


@event.listens_for(engine.sync_engine, "connect")
def _perf_on_new_physical_connection(dbapi_conn, connection_record):
    # يفتح فقط لما يُنشَأ اتصال TCP/TLS فعلي جديد بالكامل (Pool ما عنده
    # اتصال جاهز مُعاد استخدامه) — أبطأ حالة ممكنة لاتصال قاعدة بيانات.
    perf_probe.mark("db.NEW_PHYSICAL_CONNECTION_CREATED")


@event.listens_for(engine.sync_engine.pool, "checkout")
def _perf_on_pool_checkout(dbapi_conn, connection_record, connection_proxy):
    perf_probe.mark("db.pool_checkout")


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
