"""
الهدف:
مهمة مجدولة داخل عملية السيرفر نفسها (بدون Celery/APScheduler — بيئة
التطوير الحالية بلا اتصال شبكة لتثبيت حزم جديدة؛ حلقة asyncio بسيطة
كافية لحجم النظام) تفحص دوريًا:

1) جدول tasks لإطلاق:
   أ) تذكير للمسؤول عن المهمة قبل الاستحقاق بعدد أيام = reminder_offset_days
      (الافتراضي يوم واحد، قابل للتخصيص من رئيس اللجنة عند الإنشاء/التعديل).
   ب) تنبيه فوري لرئيس اللجنة لحظة أول تأخر فعلي للمهمة (نفس يوم فوات
      الموعد، مرة واحدة فقط لكل تأخر).
   راجعي db/migrations/0031_task_priority_reminder.sql للاجتهادات الموثّقة
   (طلب صاحبة المشروع 2026-09-11، بعد بحث في الأنظمة العالمية).

2) جدول committees لإطلاق إشعار "انتهت فترة اللجنة" مرة واحدة فقط لحظة
   اكتشاف lifecycle_state == 'ended' فعليًا (اليوم > end_date) — جزء من
   "قاعدة فترة اللجنة" (طلب صاحبة المشروع 2026-09-13). راجعي
   db/migrations/0033_committee_expiry_notified_at.sql.

آلية منع التكرار (كلا الفحصين): عمود طابع زمن مخصَّص بكل جدول
(reminder_sent_at/overdue_notified_at بـtasks، expiry_notified_at
بـcommittees) — تُقارَن بتاريخ اليوم (date) أو بوجودها أصلًا، لا بالطابع
الزمني الكامل، فلا يتكرر نفس الإشعار حتى لو دارت الحلقة أكثر من مرة.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.committee import Committee
from app.models.task import Task, TaskStatus
from app.services.notification_service import (
    notify_committee_expired,
    notify_task_overdue,
    notify_task_reminder,
)

logger = logging.getLogger(__name__)

# فاصل الفحص — كل ساعة كافٍ لدقة "نفس اليوم" المطلوبة هنا (مو كل دقيقة).
_CHECK_INTERVAL_SECONDS = 60 * 60


async def _check_task_reminders_and_overdue() -> None:
    today = date.today()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Task).where(
                Task.deleted_at.is_(None),
                Task.status != TaskStatus.completed,
            )
        )
        tasks = result.scalars().unique().all()

        for task in tasks:
            days_left = (task.end_date - today).days

            if days_left == task.reminder_offset_days and (
                task.reminder_sent_at is None or task.reminder_sent_at.date() != today
            ):
                await notify_task_reminder(task)
                task.reminder_sent_at = datetime.now(UTC)

            if task.end_date < today and task.overdue_notified_at is None:
                await notify_task_overdue(task)
                task.overdue_notified_at = datetime.now(UTC)

        await db.commit()


async def _check_committee_expiry() -> None:
    """
    قاعدة فترة اللجنة (طلب صاحبة المشروع 2026-09-13): إشعار كل أعضاء
    اللجنة (ورئيسها) فور اكتشاف انتهاء فترتها فعليًا، مرة واحدة فقط لكل
    لجنة — راجعي docstring رأس الملف وnotify_committee_expired
    (app/services/notification_service.py).
    """
    today = date.today()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Committee).where(
                Committee.deleted_at.is_(None),
                Committee.end_date < today,
                Committee.expiry_notified_at.is_(None),
            )
        )
        committees = result.scalars().unique().all()

        for committee in committees:
            await notify_committee_expired(committee)
            committee.expiry_notified_at = datetime.now(UTC)

        if committees:
            await db.commit()


async def _scheduler_loop() -> None:
    while True:
        try:
            await _check_task_reminders_and_overdue()
        except Exception:  # noqa: BLE001 — فشل دورة واحدة لا يجب أن يوقف الحلقة كليًا
            logger.exception("فشل فحص تذكيرات/تأخر المهام المجدول")
        try:
            await _check_committee_expiry()
        except Exception:  # noqa: BLE001 — نفس فلسفة الفحص أعلاه، فحص مستقل تمامًا
            logger.exception("فشل فحص انتهاء فترة اللجان المجدول")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)


def start_scheduler() -> asyncio.Task:
    """يُستدعى مرة واحدة عند إقلاع التطبيق (app/main.py) — راجعي lifespan هناك."""
    return asyncio.create_task(_scheduler_loop())
