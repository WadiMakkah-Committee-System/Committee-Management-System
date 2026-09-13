"""
أداة قياس أداء مؤقتة (تحقيق أداء لاما 2026-09-12) — تسجّل توقيت كل مرحلة
داخل معالجة الطلب الواحد (فك التوكن/Redis/اتصال قاعدة البيانات/كل
استعلام SQL على حدة/التسلسل) بدقة مللي ثانية نسبةً لبداية الطلب، وتُرجعها
كـheader على نفس الاستجابة (X-Perf-Trace) + تطبعها بسطر واحد بـstdout
(يظهر بسجلات Render Logs مباشرة) — بدل أي افتراض لمكان الوقت.

مؤقتة بالكامل لغرض هذا التحقيق فقط — تُزال بعد تحديد السبب الجذري
الفعلي ولا تبقى بالإنتاج.
"""

import time
from contextlib import contextmanager
from contextvars import ContextVar

_trace: ContextVar[list | None] = ContextVar("_perf_trace", default=None)
_origin: ContextVar[float | None] = ContextVar("_perf_origin", default=None)

# تشخيص إضافي 2026-09-13 (بلاغ لاما — لازم نعرف مين استدعى كل استعلام،
# ومحاولة traceback.extract_stack() بداخل event hook متزامن بـ
# app/db/session.py فشلت تمامًا: كل استعلام رجع by=? بكل التكرارات
# الأربعة اللي قاسيناها — يعني جسر greenlet الخاص بـSQLAlchemy async لا
# يُبقي إطارات (frames) سلسلة الاستدعاء غير المتزامنة الأصلية ظاهرة
# بالـstack من داخل الـgreenlet وقت before/after_cursor_execute.
#
# الحل البديل: ContextVar صريح بدل تخمين الـstack — نفس الآلية المستخدمة
# أصلًا هنا لـ_trace/_origin أعلاه (وتعمل بشكل مثبت: mark() المستدعاة من
# داخل event hook بـsession.py تصل فعليًا لنفس trace list المضبوطة وقت
# بداية الطلب بالـmiddleware، عبر نفس القفزة لـgreenlet). السبب: SQLAlchemy
# يعمل contextvars.copy_context() صراحة عند greenlet_spawn، فأي قيمة
# تُضبط بكود async قبل أي await db.execute(...) تصل فعليًا لـevent hook
# المتزامن حتى بعد القفزة لـgreenlet منفصل — بعكس traceback.extract_stack()
# اللي يقرأ فقط إطارات الـgreenlet الحالي نفسه.
_caller: ContextVar[str] = ContextVar("_perf_caller", default="?")


@contextmanager
def caller(label: str):
    """يضبط تسمية "المستدعي الحالي" أثناء تنفيذ الكتلة — استعملها ملتفة
    حول أي await db.execute(...)/await db.get(...) (أو دالة خدمة كاملة
    تحتوي استعلامًا واحدًا رئيسيًا) عشان كل استعلام SQL يُطلقه SQLAlchemy
    أثناءها (بما فيها استعلامات selectin التلقائية المتتابعة اللي تحصل
    ضمن نفس await الواحد) يُنسَب لها بالتتبّع. يُعيد القيمة السابقة تلقائيًا
    عند الخروج (حتى لو استثناء) عشان الاستدعاءات المتداخلة تُنسَب بدقة."""
    token = _caller.set(label)
    try:
        yield
    finally:
        _caller.reset(token)


def current_caller() -> str:
    return _caller.get()


def start_trace() -> None:
    _trace.set([])
    _origin.set(time.perf_counter())


def _now_ms() -> float | None:
    origin = _origin.get()
    if origin is None:
        return None
    return round((time.perf_counter() - origin) * 1000, 1)


def mark(label: str, dur_ms: float | None = None) -> None:
    trace = _trace.get()
    if trace is None:
        return
    trace.append({"label": label, "at_ms": _now_ms(), "dur_ms": dur_ms})


@contextmanager
def timed(label: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        mark(label, dur_ms=round((time.perf_counter() - t0) * 1000, 1))


def trace_summary(max_entries: int = 500) -> str:
    trace = _trace.get()
    if not trace:
        return ""
    parts = []
    for e in trace[:max_entries]:
        if e["dur_ms"] is not None:
            parts.append(f"{e['label']}={e['dur_ms']}ms@{e['at_ms']}ms")
        else:
            parts.append(f"{e['label']}@{e['at_ms']}ms")
    suffix = f" (+{len(trace) - max_entries} more)" if len(trace) > max_entries else ""
    return " | ".join(parts) + suffix
