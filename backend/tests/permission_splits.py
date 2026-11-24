"""
الهدف:
مساعد اختبارات — migration 0050 فصلت وظائف كانت تتبع صلاحية أخرى ضمنيًا
لأكواد مستقلة (مثال: تمديد الاجتماع كان يتبع meetings.update وصار
meetings.extend)، ومنحت كل كود جديد تلقائيًا لكل دور يملك الكود المصدر.

الاختبارات اللي تمنح أدوار اللجان صلاحيات مباشرة بالقاعدة (بديل PATCH
/roles) كانت تمنح الكود المصدر فقط — فتفشل بعد 0050 (403) لأن الكود
يتحقق الآن من الكود الجديد. with_split_codes تحاكي نفس منح 0050: منح الكود
المصدر يمنح معه أكواده المفصولة.

الخريطة نسخة من جدول الربط في db/migrations/0050 — حدّثيها معه لو تغيّر.
"""

SPLIT_CODES: dict[str, tuple[str, ...]] = {
    "meetings.update": ("meetings.extend",),
    "meetings.join": ("meetings.guests.manage",),
    "meetings.view": ("meetings.attendance.view",),
    "minutes.approve": ("minutes.review", "minutes.return", "minutes.send_signature"),
    "minutes.view": ("minutes.export",),
    "tasks.update": ("tasks.reassign",),
    "tasks.status.update": ("tasks.attachments.manage",),
    "decisions.create": ("decisions.attachments.add",),
    "committees.update": (
        "committees.extend",
        "committees.members.roles",
        "committees.members.add",
        "committees.members.remove",
    ),
}


def with_split_codes(codes: list[str]) -> list[str]:
    """الأكواد المطلوبة + أكوادها المفصولة (بلا تكرار، بنفس الترتيب)."""
    expanded = list(codes)
    for code in codes:
        expanded.extend(SPLIT_CODES.get(code, ()))
    return list(dict.fromkeys(expanded))
