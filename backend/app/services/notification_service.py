"""
الهدف:
إشعارات البريد الإلكتروني لأعضاء اللجنة عند إنشاء/تعديل/إلغاء اجتماع —
طلب لاما 2026-09-06: "الاشعارات توصل للبريد اذا انشاء اجتماع او حذفه او
عدل معلوماته للاعضاء".

آلية الاستدعاء: تُستدعى دائمًا كـBackgroundTasks من راوتات meetings.py
(بعد db.commit() الناجح) — وليس بشكل مباشر داخل معاملة قاعدة البيانات —
حتى لا يُبطئ إرسال البريد استجابة إنشاء/تعديل/حذف الاجتماع نفسها (راجعي
core/email_client.py لتفصيل هذا القرار، ونفس روح تحسين أداء
get_current_user بتحديث 2026-09-06 — لا نضيف زمن انتظار جديد لعملية
أساسية بسبب عملية ثانوية كالبريد).

النطاق: تُرسَل لكل Meeting.participants (أعضاء اللجنة المُضافين تلقائيًا
عند الإنشاء — راجعي meeting_service.create_meeting)، بما فيهم منشئ
الاجتماع نفسه إن كان من ضمنهم. Meeting.committee وMeeting.participants
كلاهما lazy="selectin" (محمَّلان أصلًا بالكامل بذاكرة الكائن من طلب الـAPI
نفسه) — لا حاجة لأي استعلام قاعدة بيانات إضافي هنا، حتى لو استُدعيت هذه
الدالة بعد إغلاق جلسة قاعدة البيانات (raجعي db/session.py: expire_on_commit
=False — القيم المحمَّلة أصلًا تبقى صالحة بالذاكرة).

عند التعديل تحديدًا: تُرسَل فقط لو تغيّر أحد "الحقول المهمة" — قرار لاما
2026-09-06 ("الحقول المهمة فقط") لتفادي إزعاج الأعضاء برسالة لكل تعديل
سطحي (تصحيح خطأ إملائي بالعنوان مثلًا). الحقول المهمة: موعد البداية،
موعد النهاية، نوع الاجتماع (حضوري/عن بُعد)، المكان — تُحسَب بـ
meeting_service.update_meeting نفسها (قبل التعديل مباشرة) وتُمرَّر هنا
جاهزة كـchanges.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.core.email_client import send_email
from app.models.meeting import Meeting

logger = logging.getLogger(__name__)

_DATETIME_FMT = "%Y-%m-%d الساعة %H:%M"

_FIELD_LABELS: dict[str, str] = {
    "scheduled_at": "موعد البداية",
    "scheduled_end_at": "موعد النهاية",
    "mode": "نوع الاجتماع",
    "location": "المكان",
}


def _format_value(field: str, value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        return value.strftime(_DATETIME_FMT)
    if field == "mode":
        return "حضوري" if value == "in_person" else "عن بُعد"
    return str(value)


def _meeting_details_html(meeting: Meeting) -> str:
    rows = [
        f"<li><strong>اللجنة:</strong> {meeting.committee.name}</li>",
        f"<li><strong>موعد البداية:</strong> {_format_value('scheduled_at', meeting.scheduled_at)}</li>",
    ]
    if meeting.scheduled_end_at:
        rows.append(
            f"<li><strong>موعد النهاية:</strong> "
            f"{_format_value('scheduled_end_at', meeting.scheduled_end_at)}</li>"
        )
    if meeting.mode == "in_person":
        rows.append(f"<li><strong>المكان:</strong> {meeting.location or '-'}</li>")
    else:
        rows.append("<li><strong>نوع الاجتماع:</strong> عن بُعد</li>")
    return "".join(rows)


def _participant_emails(meeting: Meeting) -> list[str]:
    return [p.email for p in meeting.participants if p.email]


def _wrap_html(body_inner: str) -> str:
    return (
        '<div dir="rtl" style="font-family: Tahoma, Arial, sans-serif; '
        'font-size: 14px; color: #1f2937; line-height: 1.7;">'
        f"{body_inner}"
        "</div>"
    )


async def notify_meeting_created(meeting: Meeting) -> None:
    """FR-MEET-001: إشعار كل أعضاء اللجنة فور جدولة اجتماع جديد."""
    subject = f"اجتماع جديد: {meeting.title}"
    body = _wrap_html(
        f"<p>تم جدولة اجتماع جديد ضمن لجنة <strong>{meeting.committee.name}</strong>:</p>"
        f"<h3>{meeting.title}</h3>"
        f"<ul>{_meeting_details_html(meeting)}</ul>"
    )
    await send_email(to=_participant_emails(meeting), subject=subject, html_body=body)


async def notify_meeting_cancelled(meeting: Meeting) -> None:
    """FR-MEET-004: إشعار كل أعضاء اللجنة فور إلغاء (حذف) اجتماع قادم."""
    subject = f"إلغاء اجتماع: {meeting.title}"
    body = _wrap_html(
        f"<p>تم إلغاء الاجتماع التالي ضمن لجنة <strong>{meeting.committee.name}</strong>:</p>"
        f"<h3>{meeting.title}</h3>"
        f"<ul>{_meeting_details_html(meeting)}</ul>"
    )
    await send_email(to=_participant_emails(meeting), subject=subject, html_body=body)


async def notify_meeting_updated(meeting: Meeting, changes: dict[str, tuple]) -> None:
    """
    FR-MEET-003: إشعار كل أعضاء اللجنة عند تعديل أحد "الحقول المهمة" فقط
    (راجعي docstring الملف أعلاه) — changes: {اسم_الحقل: (قديم, جديد)}،
    من meeting_service.update_meeting. لا تُرسِل شيئًا لو changes فارغة
    (تعديل سطحي كالعنوان/الوصف فقط).
    """
    if not changes:
        return

    change_rows = "".join(
        f"<li><strong>{_FIELD_LABELS.get(field, field)}:</strong> "
        f"من {_format_value(field, old)} إلى {_format_value(field, new)}</li>"
        for field, (old, new) in changes.items()
    )
    subject = f"تعديل اجتماع: {meeting.title}"
    body = _wrap_html(
        f"<p>تم تعديل بيانات الاجتماع التالي ضمن لجنة <strong>{meeting.committee.name}</strong>:</p>"
        f"<h3>{meeting.title}</h3>"
        f"<p>التغييرات:</p><ul>{change_rows}</ul>"
        f"<p>البيانات الحالية الكاملة:</p><ul>{_meeting_details_html(meeting)}</ul>"
    )
    await send_email(to=_participant_emails(meeting), subject=subject, html_body=body)
