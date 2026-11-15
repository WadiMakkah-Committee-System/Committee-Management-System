"""
الهدف:
تنسيق نصوص "القالب العام" للمحاضر بالعربي: التاريخ الهجري (أم القرى) والميلادي
مع اسم اليوم، الوقت بنظام 12 ساعة (صباحًا/مساءً)، والترتيب بالكلمات (الأول،
الثاني، الحادي عشر...).

المسؤولية: دوال نقية بلا قاعدة بيانات ولا تأثيرات جانبية — سهلة الاختبار.

الاعتماديات: hijridate (تحويل أم القرى — معتمدة من صاحب المشروع 2026-11-15).
التوقيت: الرياض بإزاحة ثابتة +3 (السعودية بلا توقيت صيفي) — نفس أسلوب
minutes_pdf_service.
"""

from datetime import datetime, timedelta, timezone

from hijridate import Gregorian

RIYADH = timezone(timedelta(hours=3))

# datetime.weekday(): الاثنين = 0 ... الأحد = 6.
_WEEKDAYS = ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد")

_ORDINAL_1_TO_10 = {
    1: "الأول",
    2: "الثاني",
    3: "الثالث",
    4: "الرابع",
    5: "الخامس",
    6: "السادس",
    7: "السابع",
    8: "الثامن",
    9: "التاسع",
    10: "العاشر",
}
# الآحاد داخل الأعداد المركبة (11–19 و21–99): "الحادي" بدل "الأول".
_ORDINAL_UNITS_COMPOUND = {
    1: "الحادي",
    2: "الثاني",
    3: "الثالث",
    4: "الرابع",
    5: "الخامس",
    6: "السادس",
    7: "السابع",
    8: "الثامن",
    9: "التاسع",
}
_ORDINAL_TENS = {
    20: "العشرون",
    30: "الثلاثون",
    40: "الأربعون",
    50: "الخمسون",
    60: "الستون",
    70: "السبعون",
    80: "الثمانون",
    90: "التسعون",
}


def to_riyadh(value: datetime) -> datetime:
    """
    الهدف: تحويل وقت (بمنطقة زمنية) لتوقيت الرياض.
    المدخلات: value — datetime؛ لو بلا منطقة زمنية يُعامل كـUTC (قيم القاعدة UTC).
    المخرجات: datetime بتوقيت الرياض.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(RIYADH)


def ordinal_ar(number: int) -> str:
    """
    الهدف: العدد الترتيبي بالكلمات (مذكّر) — "الموضوع الأول"، "الاجتماع الحادي عشر".

    المدخلات: number — عدد صحيح موجب.
    المخرجات: نص الترتيب. من 1 إلى 99 بالكلمات؛ غير ذلك يرجع الرقم نفسه
    (مثل "100") حتى لا يفشل التوليد في حالة نادرة.
    """
    if number in _ORDINAL_1_TO_10:
        return _ORDINAL_1_TO_10[number]
    if 11 <= number <= 19:
        return f"{_ORDINAL_UNITS_COMPOUND[number - 10]} عشر"
    if 20 <= number <= 99:
        tens, units = divmod(number, 10)
        tens_word = _ORDINAL_TENS[tens * 10]
        if units == 0:
            return tens_word
        # "الحادي والعشرون"، "الثاني والثلاثون".
        return f"{_ORDINAL_UNITS_COMPOUND[units]} و{tens_word}"
    return str(number)


def hijri_date_text(value: datetime) -> str | None:
    """
    الهدف: التاريخ الهجري (أم القرى) بصيغة 1446/07/16.
    المدخلات: value — datetime (يُحوَّل للرياض أولًا).
    المخرجات: النص، أو None لو التاريخ خارج نطاق تقويم أم القرى المدعوم
    (1343–1500هـ تقريبًا) — يُكتفى حينها بالميلادي.
    """
    local = to_riyadh(value)
    try:
        hijri = Gregorian(local.year, local.month, local.day).to_hijri()
    except (OverflowError, ValueError):
        return None
    return f"{hijri.year:04d}/{hijri.month:02d}/{hijri.day:02d}"


def date_text(value: datetime) -> str:
    """
    الهدف: نص تاريخ الترويسة كما في المحضر الأصلي:
    "الخميس 1446/07/16هـ الموافق 2025/01/16م".

    المدخلات: value — موعد الاجتماع.
    المخرجات: النص (بدون الهجري لو خارج نطاق أم القرى).
    """
    local = to_riyadh(value)
    weekday = _WEEKDAYS[local.weekday()]
    gregorian = f"{local.year:04d}/{local.month:02d}/{local.day:02d}م"
    hijri = hijri_date_text(local)
    if hijri is None:
        return f"{weekday} {gregorian}"
    return f"{weekday} {hijri}هـ الموافق {gregorian}"


def clock_text(value: datetime) -> str:
    """
    الهدف: الوقت بنظام 12 ساعة: "05:00 مساءً" / "09:30 صباحاً".
    المدخلات: value — datetime. المخرجات: النص بتوقيت الرياض.
    قاعدة: 00:xx ← 12:xx صباحاً، و12:xx ← 12:xx مساءً.
    """
    local = to_riyadh(value)
    hour12 = local.hour % 12 or 12
    period = "صباحاً" if local.hour < 12 else "مساءً"
    return f"{hour12:02d}:{local.minute:02d} {period}"


def time_text(value: datetime) -> str:
    """الهدف: نص "الزمان" في الترويسة: "الساعة 05:00 مساءً". المدخلات: موعد البداية."""
    return f"الساعة {clock_text(value)}"
