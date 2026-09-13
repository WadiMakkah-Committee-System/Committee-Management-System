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
