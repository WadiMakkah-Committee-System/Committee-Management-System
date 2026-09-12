"""
الهدف:
إشعارات المستخدمين بحدوث الأحداث المهمة عبر قناتين مستقلتين:

1) بريد إلكتروني (SMTP) — كان مقصورًا على الاجتماعات فقط (طلب لاما
   2026-09-06)، لم يتغيّر بهذا التحديث.
2) إشعارات داخل النظام (In-app، جدول notifications — راجعي رأس
   db/migrations/0027_notifications_schema.sql) — جديدة بهذا التحديث
   (طلب صاحبة المشروع 2026-09-07)، تغطي المهام واللجان والقرارات
   والاجتماعات معًا.

القناتان مستقلتان تمامًا: حدث معيّن قد يُرسِل بريدًا فقط، أو يكتب إشعارًا
داخل النظام فقط، أو كلاهما — كل دالة notify_* أدناه تقرر ما تحتاجه فعليًا.
الاجتماعات حاليًا الوحيدة التي تستخدم القناتين معًا؛ باقي الوحدات
(مهام/لجان/قرارات) إشعارات داخل النظام فقط بهذه المرحلة (لا طلب صريح
بالبريد لها).

آلية الاستدعاء (كلا القناتين): تُستدعى دائمًا كـBackgroundTasks من راوتات
الـAPI (بعد db.commit() الناجح) — وليس بشكل مباشر داخل معاملة قاعدة
البيانات — حتى لا يُبطئ الإشعار استجابة العملية الأصلية نفسها (نفس قرار
البريد الموثّق أصلًا، يشمل الآن أيضًا كتابة إشعارات داخل النظام لأنها
كتابة DB إضافية مستقلة عن معاملة الطلب الأصلي).

ملاحظة تقنية مهمة لإشعارات داخل النظام تحديدًا (بخلاف البريد): البريد
يقرأ فقط كائنات محمَّلة أصلًا بالذاكرة (lazy="selectin" + expire_on_commit
=False)، فلا يحتاج جلسة قاعدة بيانات جديدة. كتابة صف بجدول notifications
تحتاج جلسة فعلية، وجلسة الطلب الأصلية (get_db) تكون مغلقة فعليًا وقت
تنفيذ BackgroundTask — لذلك كل دوال الكتابة هنا تفتح جلستها الخاصة عبر
AsyncSessionLocal مباشرة (راجعي db/session.py). فشل الكتابة (أو فشل
البريد) لا يُرفَع أبدًا للمستدعي — يُسجَّل بالسجلات فقط (logger.exception)؛
إشعار فاشل لا يجب أن يظهر كخطأ بعملية أصلية نجحت فعليًا.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email_client import send_email
from app.core.redis_client import redis_client
from app.db.session import AsyncSessionLocal
from app.models.committee_request import CommitteeFormationRequest
from app.models.decision import Decision
from app.models.meeting import Meeting
from app.models.meeting_minutes import MeetingMinutes
from app.models.notification import Notification
from app.models.role import Permission, RolePermission
from app.models.task import Task, TaskStatus
from app.models.user import User


class NotificationNotFoundError(Exception):
    """الإشعار غير موجود، أو موجود لكن ليس ملكًا للمستخدم الحالي (نفس المعاملة أمنيًا)."""


class NotificationForbiddenError(Exception):
    """الإشعار موجود لكنه ملك مستخدم آخر."""

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


async def notify_meeting_created(meeting: Meeting, *, actor_user_id: uuid.UUID | None = None) -> None:
    """FR-MEET-001: إشعار كل أعضاء اللجنة فور جدولة اجتماع جديد (بريد + داخل النظام)."""
    subject = f"اجتماع جديد: {meeting.title}"
    body = _wrap_html(
        f"<p>تم جدولة اجتماع جديد ضمن لجنة <strong>{meeting.committee.name}</strong>:</p>"
        f"<h3>{meeting.title}</h3>"
        f"<ul>{_meeting_details_html(meeting)}</ul>"
    )
    await send_email(to=_participant_emails(meeting), subject=subject, html_body=body)
    await _notify_many(
        [p.user_id for p in meeting.participants],
        event_type="meeting_created",
        title=f"اجتماع جديد: {meeting.title}",
        body=f"ضمن لجنة {meeting.committee.name} — {_format_value('scheduled_at', meeting.scheduled_at)}.",
        related_entity_type="meeting",
        related_entity_id=meeting.meeting_id,
        exclude_user_id=actor_user_id,
    )


async def notify_meeting_cancelled(meeting: Meeting, *, actor_user_id: uuid.UUID | None = None) -> None:
    """FR-MEET-004: إشعار كل أعضاء اللجنة فور إلغاء (حذف) اجتماع قادم (بريد + داخل النظام)."""
    subject = f"إلغاء اجتماع: {meeting.title}"
    body = _wrap_html(
        f"<p>تم إلغاء الاجتماع التالي ضمن لجنة <strong>{meeting.committee.name}</strong>:</p>"
        f"<h3>{meeting.title}</h3>"
        f"<ul>{_meeting_details_html(meeting)}</ul>"
    )
    await send_email(to=_participant_emails(meeting), subject=subject, html_body=body)
    await _notify_many(
        [p.user_id for p in meeting.participants],
        event_type="meeting_cancelled",
        title=f"إلغاء اجتماع: {meeting.title}",
        body=f"ضمن لجنة {meeting.committee.name}.",
        related_entity_type="meeting",
        related_entity_id=meeting.meeting_id,
        exclude_user_id=actor_user_id,
    )


async def notify_meeting_updated(
    meeting: Meeting, changes: dict[str, tuple], *, actor_user_id: uuid.UUID | None = None
) -> None:
    """
    FR-MEET-003: إشعار كل أعضاء اللجنة عند تعديل أحد "الحقول المهمة" فقط
    (راجعي docstring الملف أعلاه) — changes: {اسم_الحقل: (قديم, جديد)}،
    من meeting_service.update_meeting. لا تُرسِل شيئًا لو changes فارغة
    (تعديل سطحي كالعنوان/الوصف فقط) — بريد وداخل النظام معًا.
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

    changed_fields_ar = "، ".join(_FIELD_LABELS.get(f, f) for f in changes)
    await _notify_many(
        [p.user_id for p in meeting.participants],
        event_type="meeting_updated",
        title=f"تعديل اجتماع: {meeting.title}",
        body=f"تغيّر: {changed_fields_ar}.",
        related_entity_type="meeting",
        related_entity_id=meeting.meeting_id,
        exclude_user_id=actor_user_id,
    )


# =====================================================================
# إشعارات داخل النظام (In-app) — لبنات أساسية مشتركة لكل الوحدات
# =====================================================================


async def _write_notifications(rows: list[dict]) -> None:
    """
    يكتب صفًا أو أكثر بجدول notifications دفعة واحدة، بجلسة قاعدة بيانات
    مستقلة (AsyncSessionLocal) — راجعي docstring رأس الملف لسبب ذلك. لا
    يرفع أي استثناء للمستدعي عند الفشل (نفس فلسفة send_email تمامًا).
    """
    if not rows:
        return
    try:
        async with AsyncSessionLocal() as session:
            session.add_all([Notification(**row) for row in rows])
            await session.commit()
    except Exception:
        logger.exception("فشل كتابة إشعار (إشعارات) داخل النظام")


async def _users_with_permission(session, code: str) -> list[uuid.UUID]:
    """
    كل مستخدم نشِط (status=active، غير محذوف) يملك -عبر دوره النظامي-
    الصلاحية `code` بنطاق department أو all. نطاق own لا يكفي لبثّ جماعي
    — نفس القيد المطبَّق فعليًا بـcommittee_service._require_access لهذه
    الصلاحيات بالضبط (مثال: تعديل الطلب بعد إرساله "متاح فقط للمكتب
    التنفيذي"، أي department/all فقط). Snapshot وقت الاستدعاء فقط (راجعي
    ملاحظة التصميم 1 برأس migration 0027) — لا استعلام حي لاحقًا.
    """
    stmt = (
        select(User.user_id)
        .join(RolePermission, RolePermission.role_id == User.role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(
            Permission.code == code,
            RolePermission.scope.in_(("department", "all")),
            User.deleted_at.is_(None),
            User.status == "active",
        )
        .distinct()
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def _notify_user(
    recipient_user_id: uuid.UUID,
    *,
    event_type: str,
    title: str,
    body: str | None = None,
    related_entity_type: str | None = None,
    related_entity_id: uuid.UUID | None = None,
) -> None:
    """إشعار لمستخدم واحد محدَّد بذاته (مثال: صاحب طلب لجنة عند اعتماده)."""
    await _write_notifications(
        [
            {
                "recipient_user_id": recipient_user_id,
                "event_type": event_type,
                "title": title,
                "body": body,
                "related_entity_type": related_entity_type,
                "related_entity_id": related_entity_id,
            }
        ]
    )
    await _invalidate_unread_count(recipient_user_id)


async def _notify_many(
    recipient_ids: Iterable[uuid.UUID],
    *,
    event_type: str,
    title: str,
    body: str | None = None,
    related_entity_type: str | None = None,
    related_entity_id: uuid.UUID | None = None,
    exclude_user_id: uuid.UUID | None = None,
) -> None:
    """
    إشعار لقائمة مستخدمين معروفة سلفًا (من كائن محمَّل بالذاكرة أصلًا —
    مثال: meeting.participants أو decision.assignees) — بخلاف
    _notify_permission_holders أدناه (تلك تحتاج استعلام قاعدة بيانات
    لاكتشاف القائمة، وليست معروفة سلفًا).
    """
    unique_ids = {uid for uid in recipient_ids if uid != exclude_user_id}
    await _write_notifications(
        [
            {
                "recipient_user_id": uid,
                "event_type": event_type,
                "title": title,
                "body": body,
                "related_entity_type": related_entity_type,
                "related_entity_id": related_entity_id,
            }
            for uid in unique_ids
        ]
    )
    for uid in unique_ids:
        await _invalidate_unread_count(uid)


async def _notify_permission_holders(
    permission_code: str,
    *,
    event_type: str,
    title: str,
    body: str | None = None,
    related_entity_type: str | None = None,
    related_entity_id: uuid.UUID | None = None,
    exclude_user_id: uuid.UUID | None = None,
) -> None:
    """
    إشعار جماعي لكل من يملك `permission_code` بنطاق department/all وقت
    الاستدعاء (مثال: تقديم طلب لجنة جديد → كل من يملك
    committees.request.update حاليًا، أيًّا كان الدور الذي يحملها —
    المكتب التنفيذي اليوم، أو أي دور يُمنح هذي الصلاحية مستقبلًا بدون أي
    تعديل كود هنا).
    """
    try:
        async with AsyncSessionLocal() as session:
            recipient_ids = await _users_with_permission(session, permission_code)
    except Exception:
        logger.exception("فشل جلب مستلمي إشعار جماعي (%s)", permission_code)
        return

    await _notify_many(
        recipient_ids,
        event_type=event_type,
        title=title,
        body=body,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        exclude_user_id=exclude_user_id,
    )


# =====================================================================
# المهام — راجعي app/services/task_service.py لنقاط الإطلاق الفعلية
# =====================================================================

_TASK_STATUS_LABELS: dict[TaskStatus, str] = {
    TaskStatus.todo: "للقيام",
    TaskStatus.in_progress: "جارية",
    TaskStatus.on_hold: "معلّقة",
    TaskStatus.completed: "مكتملة",
}


async def notify_task_created(task: Task, *, actor_user_id: uuid.UUID) -> None:
    """FR-TASK-001/002: إشعار المسؤول الأول عن المهمة عند إنشائها (ما لم يكن هو المنشئ نفسه)."""
    if task.assignee_user_id == actor_user_id:
        return
    await _notify_user(
        task.assignee_user_id,
        event_type="task_created",
        title=f"مهمة جديدة: {task.title}",
        body=f"أُسندت إليك ضمن لجنة {task.committee.name}.",
        related_entity_type="task",
        related_entity_id=task.task_id,
    )


async def notify_task_reassigned(task: Task, *, actor_user_id: uuid.UUID) -> None:
    """إشعار المسؤول الجديد فقط (المسؤول السابق لا يحتاج إشعارًا — يظهر له بمسار المهمة إن كان لا يزال بلجنته)."""
    if task.assignee_user_id == actor_user_id:
        return
    await _notify_user(
        task.assignee_user_id,
        event_type="task_reassigned",
        title=f"أُسندت إليك مهمة: {task.title}",
        body=f"ضمن لجنة {task.committee.name}.",
        related_entity_type="task",
        related_entity_id=task.task_id,
    )


async def notify_task_status_changed(task: Task, *, actor_user_id: uuid.UUID) -> None:
    """
    إشعار "الطرف الآخر" بتغيير حالة المهمة: لو حدّثها المسؤول عنها، يُشعَر
    رئيس اللجنة؛ لو حدّثها رئيس اللجنة (أو غيره ممن يملك صلاحية)، يُشعَر
    المسؤول عنها — بدون إشعار الفاعل نفسه بفعله.
    """
    status_label = _TASK_STATUS_LABELS.get(task.status, task.status.value)
    recipients: set[uuid.UUID] = {task.assignee_user_id, task.committee.chair_user_id}
    recipients.discard(actor_user_id)
    recipients.discard(None)
    await _notify_many(
        recipients,
        event_type="task_status_changed",
        title=f"تحديث حالة مهمة: {task.title}",
        body=f"الحالة الجديدة: {status_label}.",
        related_entity_type="task",
        related_entity_id=task.task_id,
    )


async def notify_task_reminder(task: Task) -> None:
    """
    تذكير للمسؤول عن المهمة قبل الاستحقاق بـ reminder_offset_days —
    تُستدعى من المهمة المجدولة فقط (app/core/scheduler.py)، لا من راوتات
    الـAPI (لا "فاعل" بشري هنا، النظام نفسه يُطلقها).
    """
    await _notify_user(
        task.assignee_user_id,
        event_type="task_reminder",
        title=f"تذكير: اقترب موعد استحقاق مهمة {task.title}",
        body=f"موعد الاستحقاق: {task.end_date.strftime('%Y-%m-%d')}.",
        related_entity_type="task",
        related_entity_id=task.task_id,
    )


async def notify_task_overdue(task: Task) -> None:
    """
    تنبيه فوري لرئيس اللجنة لحظة أول تأخر فعلي للمهمة (نفس يوم فوات
    الموعد، بدون انتظار) — طلب صاحبة المشروع 2026-09-11 بعد بحث في
    الأنظمة العالمية (Escalation). تُستدعى من المهمة المجدولة فقط
    (app/core/scheduler.py)، مرة واحدة فقط لكل تأخر (يُمنع التكرار
    بـ overdue_notified_at بطبقة الـscheduler). لا رئيس للجنة
    (chair_user_id فارغ) = لا إشعار.
    """
    if task.committee.chair_user_id is None:
        return
    await _notify_user(
        task.committee.chair_user_id,
        event_type="task_overdue",
        title=f"مهمة متأخرة: {task.title}",
        body=(
            f"تجاوزت موعد الاستحقاق ({task.end_date.strftime('%Y-%m-%d')}) "
            "والمسؤول عنها لم يُنهها بعد. يمكنك تمديد الموعد، إعادة إسنادها، أو تعليقها."
        ),
        related_entity_type="task",
        related_entity_id=task.task_id,
    )


# =====================================================================
# طلبات تكوين اللجان — راجعي app/services/committee_service.py
# =====================================================================


async def notify_committee_request_submitted(
    request: CommitteeFormationRequest, *, actor_user_id: uuid.UUID
) -> None:
    """إرسال/إعادة إرسال الطلب → بث لكل من يملك committees.request.update (المكتب التنفيذي)."""
    await _notify_permission_holders(
        "committees.request.update",
        event_type="committee_request_submitted",
        title=f"طلب لجنة بانتظار المراجعة: {request.committee_name}",
        related_entity_type="committee_request",
        related_entity_id=request.request_id,
        exclude_user_id=actor_user_id,
    )


async def notify_committee_request_returned_to_admin(
    request: CommitteeFormationRequest, *, actor_user_id: uuid.UUID
) -> None:
    """المكتب التنفيذي يرجع الطلب لصاحبه → إشعار لصاحب الطلب فقط."""
    if request.requested_by == actor_user_id:
        return
    await _notify_user(
        request.requested_by,
        event_type="committee_request_returned_to_admin",
        title=f"طلب لجنتك أُعيد إليك للتعديل: {request.committee_name}",
        body=request.return_reason,
        related_entity_type="committee_request",
        related_entity_id=request.request_id,
    )


async def notify_committee_request_returned_to_office(
    request: CommitteeFormationRequest, *, actor_user_id: uuid.UUID
) -> None:
    """الرئيس التنفيذي يرجع الطلب للمكتب التنفيذي → بث لمن يملك committees.request.update."""
    await _notify_permission_holders(
        "committees.request.update",
        event_type="committee_request_returned_to_office",
        title=f"طلب لجنة أُعيد من الرئيس التنفيذي: {request.committee_name}",
        body=request.return_reason,
        related_entity_type="committee_request",
        related_entity_id=request.request_id,
        exclude_user_id=actor_user_id,
    )


async def notify_committee_request_escalated(
    request: CommitteeFormationRequest, *, actor_user_id: uuid.UUID
) -> None:
    """رفع الطلب للاعتماد → بث لمن يملك committees.request.approve (الرئيس التنفيذي)."""
    await _notify_permission_holders(
        "committees.request.approve",
        event_type="committee_request_escalated",
        title=f"طلب لجنة بانتظار اعتمادك: {request.committee_name}",
        related_entity_type="committee_request",
        related_entity_id=request.request_id,
        exclude_user_id=actor_user_id,
    )


async def notify_committee_request_approved(
    request: CommitteeFormationRequest, *, actor_user_id: uuid.UUID
) -> None:
    """إشعار صاحب الطلب باعتماده نهائيًا."""
    if request.requested_by == actor_user_id:
        return
    await _notify_user(
        request.requested_by,
        event_type="committee_request_approved",
        title=f"تم اعتماد طلب لجنتك: {request.committee_name}",
        related_entity_type="committee_request",
        related_entity_id=request.request_id,
    )


async def notify_committee_request_rejected(
    request: CommitteeFormationRequest, *, actor_user_id: uuid.UUID
) -> None:
    """إشعار صاحب الطلب برفضه، مع سبب الرفض."""
    if request.requested_by == actor_user_id:
        return
    await _notify_user(
        request.requested_by,
        event_type="committee_request_rejected",
        title=f"تم رفض طلب لجنتك: {request.committee_name}",
        body=request.rejection_reason,
        related_entity_type="committee_request",
        related_entity_id=request.request_id,
    )


# =====================================================================
# القرارات — راجعي app/services/decision_service.py
# =====================================================================


async def notify_decision_created(decision: Decision, *, actor_user_id: uuid.UUID) -> None:
    """قرار جديد → إشعار كل أعضاء اللجنة (decision.assignees، مشتقّة تلقائيًا من العضوية)."""
    await _notify_many(
        [u.user_id for u in decision.assignees],
        event_type="decision_created",
        title=f"قرار جديد: {decision.title}",
        body=f"ضمن لجنة {decision.committee.name}.",
        related_entity_type="decision",
        related_entity_id=decision.decision_id,
        exclude_user_id=actor_user_id,
    )


async def notify_decision_voting_opened(decision: Decision, *, actor_user_id: uuid.UUID) -> None:
    """
    فتح التصويت → إشعار كل أعضاء اللجنة (decision.assignees). تبسيط
    متعمَّد: المُصوِّتون الفعليون (_committee_voter_ids بـdecision_service)
    مجموعة فرعية منهم غالبًا، لكن دالة الإشعارات هنا لا تستورد دوالًا
    خاصة (_prefixed) من خدمة أخرى (فصل طبقات) — التنبيه لكل الأعضاء عن
    فتح التصويت غير ضار حتى لمن لا يصوّت فعليًا.
    """
    await _notify_many(
        [u.user_id for u in decision.assignees],
        event_type="decision_voting_opened",
        title=f"فُتح التصويت على قرار: {decision.title}",
        body=f"ضمن لجنة {decision.committee.name}.",
        related_entity_type="decision",
        related_entity_id=decision.decision_id,
        exclude_user_id=actor_user_id,
    )


async def notify_decision_approved(decision: Decision, *, actor_user_id: uuid.UUID) -> None:
    """اعتماد القرار نهائيًا → إشعار كل أعضاء اللجنة."""
    await _notify_many(
        [u.user_id for u in decision.assignees],
        event_type="decision_approved",
        title=f"تم اعتماد القرار: {decision.title}",
        body=f"ضمن لجنة {decision.committee.name}.",
        related_entity_type="decision",
        related_entity_id=decision.decision_id,
        exclude_user_id=actor_user_id,
    )


async def notify_decision_rejected(decision: Decision) -> None:
    """
    رفض تلقائي لعدم تحقق الأغلبية (decision_service._maybe_close_voting) →
    إشعار كل أعضاء اللجنة. بدون actor_user_id (بخلاف باقي دوال decision.*
    أعلاه) عمدًا: هذا حدث آلي بحت لا يُطلقه أي مستخدم بفعل مباشر (يحدث
    كسليًا عند أي تفاعل يصادف انتهاء موعد التصويت أو اكتمال تصويت الجميع
    — راجعي docstring decision_service.py)، فلا يوجد "فاعل" منطقي يُستثنى
    من الإشعار.
    """
    await _notify_many(
        [u.user_id for u in decision.assignees],
        event_type="decision_rejected",
        title=f"تم رفض القرار: {decision.title}",
        body=decision.rejection_reason or f"ضمن لجنة {decision.committee.name}.",
        related_entity_type="decision",
        related_entity_id=decision.decision_id,
    )


# =====================================================================
# استعلامات المستخدم على إشعاراته — يستخدمها راوت app/api/v1/notifications.py
# مباشرة بجلسة الطلب العادية (get_db)، بخلاف كل ما سبق أعلاه (يفتح جلسته
# الخاصة لأنه يُستدعى من BackgroundTasks). كل دالة هنا تتحقق من الملكية
# صراحة (recipient_user_id == actor.user_id) — مستخدم لا يقدر يقرأ أو
# يعلّم كمقروء إشعار مستخدم آخر، حتى لو خمّن معرّفه (IDOR).
# =====================================================================


async def list_notifications(
    db: AsyncSession,
    *,
    actor: User,
    unread_only: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Notification], int]:
    """إشعارات المستخدم الحالي فقط، الأحدث أولًا — مع العدد الكلي لدعم الصفحات (نفس نمط audit_log)."""
    conditions = [Notification.recipient_user_id == actor.user_id]
    if unread_only:
        conditions.append(Notification.is_read.is_(False))

    total = (
        await db.execute(select(func.count()).select_from(Notification).where(*conditions))
    ).scalar_one()

    result = await db.execute(
        select(Notification)
        .where(*conditions)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(result.scalars().all())
    return items, total


_UNREAD_COUNT_CACHE_TTL_SECONDS = 5
_UNREAD_COUNT_KEY_PREFIX = "unread_count:"


def _unread_count_key(user_id: uuid.UUID) -> str:
    return f"{_UNREAD_COUNT_KEY_PREFIX}{user_id}"


async def _invalidate_unread_count(user_id: uuid.UUID) -> None:
    """يُستدعى فور كتابة إشعار جديد أو تعليمه كمقروء، حتى لا ينتظر
    الجرس بالـTopbar انتهاء الـTTL ليعكس التغيير."""
    try:
        await redis_client.delete(_unread_count_key(user_id))
    except Exception:
        logger.exception("فشل إبطال عداد الإشعارات المخزَّن بـRedis")


async def get_unread_count(db: AsyncSession, *, actor: User) -> int:
    """
    عداد جرس الإشعارات بالـTopbar — يُستدعى بشكل متكرر (polling) من كل
    صفحة. تحديث 2026-09-12 (تشخيص بطء الأداء): الاستعلام نفسه تافه (COUNT
    مفهرس)، لكن كل استدعاء كان يفتح اتصال DB جديدًا كاملًا (المشكلة
    موثّقة بـdb/session.py)، فالتكلفة الفعلية بالكامل كانت "فتح الاتصال"
    لا "تنفيذ الاستعلام". نخزّن الناتج بـRedis لثوانٍ قليلة بدل ما نضرب
    قاعدة البيانات بكل استدعاء — يُبطَل فورًا عند تغيّر فعلي (راجعي
    _invalidate_unread_count)، فأسوأ سيناريو هو تأخر عرض بمقدار الـTTL
    فقط في حالة نادرة، لا أكثر.
    """
    cache_key = _unread_count_key(actor.user_id)
    try:
        cached = await redis_client.get(cache_key)
        if cached is not None:
            return int(cached)
    except Exception:
        logger.exception("فشل قراءة عداد الإشعارات من Redis — نكمل بالاستعلام المباشر")

    result = await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.recipient_user_id == actor.user_id,
            Notification.is_read.is_(False),
        )
    )
    count = result.scalar_one()

    try:
        await redis_client.set(cache_key, str(count), ex=_UNREAD_COUNT_CACHE_TTL_SECONDS)
    except Exception:
        logger.exception("فشل تخزين عداد الإشعارات بـRedis")

    return count


async def _load_own_notification(db: AsyncSession, *, actor: User, notification_id: uuid.UUID) -> Notification:
    notification = await db.get(Notification, notification_id)
    if notification is None:
        raise NotificationNotFoundError("الإشعار غير موجود")
    if notification.recipient_user_id != actor.user_id:
        raise NotificationForbiddenError("لا يمكنك الوصول لإشعار مستخدم آخر")
    return notification


async def mark_as_read(db: AsyncSession, *, actor: User, notification_id: uuid.UUID) -> Notification:
    notification = await _load_own_notification(db, actor=actor, notification_id=notification_id)
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(notification)
        await _invalidate_unread_count(actor.user_id)
    return notification


async def mark_all_as_read(db: AsyncSession, *, actor: User) -> int:
    """يعلّم كل إشعارات المستخدم الحالي غير المقروءة كمقروءة، ويُرجع عددها."""
    result = await db.execute(
        select(Notification).where(
            Notification.recipient_user_id == actor.user_id,
            Notification.is_read.is_(False),
        )
    )
    unread = list(result.scalars().all())
    now = datetime.now(UTC)
    for notification in unread:
        notification.is_read = True
        notification.read_at = now
    if unread:
        await db.commit()
        await _invalidate_unread_count(actor.user_id)
    return len(unread)


async def notify_minutes_sent_for_signature(
    minutes: MeetingMinutes, meeting: Meeting, *, actor_user_id: uuid.UUID
) -> None:
    """إرسال المحضر للتوقيع (SRS §7.2) → إشعار كل موقّع متوقَّع (صفوف
    meeting_minutes_signatures، مملوءة تلقائيًا بكل أعضاء اللجنة لحظة
    الإرسال — راجعي meeting_minutes_service.send_for_signature)."""
    await _notify_many(
        [s.user_id for s in minutes.signatures],
        event_type="minutes_sent_for_signature",
        title=f"محضر بانتظار توقيعك: {meeting.title}",
        body="راجعي محضر الاجتماع ووقّعيه إلكترونيًا.",
        related_entity_type="meeting",
        related_entity_id=meeting.meeting_id,
        exclude_user_id=actor_user_id,
    )


async def notify_minutes_completed(minutes: MeetingMinutes, meeting: Meeting) -> None:
    """اكتملت كل التوقيعات (اعتماد وأرشفة تلقائيان) → إشعار كل موقّع.
    بدون actor_user_id (بخلاف الدالة أعلاه) عمدًا: هذا حدث آلي عند
    اكتمال آخر توقيع، لا فاعل واحد منطقي يُستثنى منه (نفس منطق
    notify_decision_rejected أعلاه)."""
    await _notify_many(
        [s.user_id for s in minutes.signatures],
        event_type="minutes_completed",
        title=f"اكتملت توقيعات المحضر: {meeting.title}",
        body="أصبح المحضر وثيقة رسمية معتمدة ومؤرشفة.",
        related_entity_type="meeting",
        related_entity_id=meeting.meeting_id,
    )
