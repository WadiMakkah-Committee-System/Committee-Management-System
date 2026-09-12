"""
الهدف:
مهمة مجدولة داخل عملية السيرفر نفسها (بدون Celery/APScheduler — بيئة
التطوير الحالية بلا اتصال شبكة لتثبيت حزم جديدة؛ حلقة asyncio بسيطة
كافية لحجم النظام) تفحص جدول tasks دوريًا لإطلاق:

1) تذكير للمسؤول عن المهمة قبل الاستحقاق بعدد أيام = reminder_offset_days
   (الافتراضي يوم واحد، قابل للتخصيص من رئيس اللجنة عند الإنشاء/التعديل).
2) تنبيه فوري لرئيس اللجنة لحظة أول تأخر فعلي للمهمة (نفس يوم فوات
   الموعد، مرة واحدة فقط لكل تأخر).

راجعي db/migrations/0031_task_priority_reminder.sql للاجتهادات الموثّقة
(طلب صاحبة المشروع 2026-09-11، بعد بحث في الأنظمة العالمية).

آلية منع التكرار: reminder_sent_at/overdue_notified_at بجدول tasks —
تُقارَن بتاريخ اليوم (date)، لا بالطابع الزمني الكامل، فلا يُعاد إرسال
نفس التذكير مرتين بنفس اليوم حتى لو دارت الحلقة أكثر من مرة. تمديد
الموعد (task_service.update_task) يُصفّرهما، فتُستأنف الدورة من جديد.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.task import Task, TaskStatus
from app.services.notification_service import notify_task_overdue, notify_task_reminder

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


async def _scheduler_loop() -> None:
    while True:
        try:
            await _check_task_reminders_and_overdue()
        except Exception:  # noqa: BLE001 — فشل دورة واحدة لا يجب أن يوقف الحلقة كليًا
            logger.exception("فشل فحص تذكيرات/تأخر المهام المجدول")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)


def start_scheduler() -> asyncio.Task:
    """يُستدعى مرة واحدة عند إقلاع التطبيق (app/main.py) — راجعي lifespan هناك."""
    return asyncio.create_task(_scheduler_loop())
