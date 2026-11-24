"""
الهدف:
تواريخ اختبارات نسبية لتاريخ التشغيل — بدل تواريخ ثابتة تنتهي صلاحيتها مع
الوقت (فترة اللجنة الثابتة 2026-09-01 → 2026-12-01 خلّت اختبارات الاجتماعات
تفشل لما صارت مواعيد اجتماعاتها بالماضي، وكانت بتنكسر كلها بعد 2026-12-01).

- COMMITTEE_START / COMMITTEE_END: فترة لجنة تغطي الماضي القريب وسنة قادمة.
- VOTING_START / VOTING_END: فترة تصويت قرار تشمل اليوم.
- future_slot(days, hour): موعد اجتماع مستقبلي (بداية، نهاية بعد ساعة) ISO.
- past_slot(days, hour): موعد اجتماع ماضٍ داخل فترة اللجنة.
"""

from datetime import UTC, date, datetime, time, timedelta

_TODAY = date.today()

COMMITTEE_START = (_TODAY - timedelta(days=60)).isoformat()
COMMITTEE_END = (_TODAY + timedelta(days=365)).isoformat()
VOTING_START = (_TODAY - timedelta(days=1)).isoformat()
VOTING_END = (_TODAY + timedelta(days=30)).isoformat()


def _slot(day: date, hour: int) -> tuple[str, str]:
    start = datetime.combine(day, time(hour, 0), tzinfo=UTC)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), (start + timedelta(hours=1)).strftime(fmt)


def future_slot(days: int, hour: int = 10) -> tuple[str, str]:
    return _slot(_TODAY + timedelta(days=days), hour)


def past_slot(days: int, hour: int = 9) -> tuple[str, str]:
    return _slot(_TODAY - timedelta(days=days), hour)

# تاريخان داخل فترة اللجنة لقرارات/مهام (البداية ≤ النهاية): اليوم وبعد شهر.
DATE_A = _TODAY.isoformat()
DATE_B = (_TODAY + timedelta(days=30)).isoformat()
