"""
الهدف:
تشغيل مهمة async "منفصلة" فعليًا عن دورة حياة الطلب — بديل عن
BackgroundTasks الخاصة بـ FastAPI/Starlette للمهام التي لا تحتاج (ولا يجب
أن تنتظر) انتهاء الطلب نفسه.

المسؤولية:
run_detached(coro): يجدول coroutine على نفس الـ event loop عبر
asyncio.create_task، ويحتفظ بمرجع له (راجعي الملاحظة أدناه) حتى انتهائه —
بدون أي علاقة بكائن Response أو بتنظيف Dependencies الخاصة بالطلب.

تحقيق أداء لاما 2026-09-15 (تحليل.pdf — "Database session can remain
occupied during email work"، severity: HIGH): تتبّع pg_stat_activity
الفعلي (راجعي app/core/email_client.py، تعليق 2026-09-10) أثبت مسبقًا أن
FastAPI تُنظّف Dependency ذات yield (get_db) بعد انتهاء BackgroundTasks لا
قبلها — أي أن استخدام background_tasks.add_task(...) لإرسال بريد إشعار
كان يُبقي جلسة قاعدة بيانات الطلب الأصلي محجوزة (idle، لا تُعيد للـ Pool)
طوال مدة محاولة الاتصال بـ SMTP، حتى بعد إصلاح 2026-09-10 (timeout=10
صريح) الذي حدّ المدة لكنه لم يُلغِ الحجز نفسه. هذا صحيح بصرف النظر هل
الدالة المجدولة تلمس db أصلًا (كل دوال notification_service.notify_* هنا
لا تأخذ db كمعامل إطلاقًا — تقرأ فقط خصائص كائنات ORM محمَّلة مسبقًا ضمن
نفس معاملة الطلب، آمنة بعد إغلاق الجلسة بفضل expire_on_commit=False —
راجعي app/db/session.py).

run_detached تحل هذا جذريًا (لا مجرد تقليل مدته): الجدولة عبر
asyncio.create_task منفصلة تمامًا عن AsyncExitStack الخاص بالطلب — دالة
الراوت تُنهي تنفيذها وتُعيد الاستجابة، فتُغلَق جلسة get_db وتعود للـ Pool
فورًا، بينما مهمة البريد تكمل عملها بمعزل تام على نفس الـ event loop
(لا Thread/Process منفصل — لا حاجة لبنية طابور/عامل مستقلة بحجم هذا
المشروع، ونفس دوال notify_* أصلًا لا تحتاج db كما سبق).

ملاحظة توثيقية مهمة (asyncio docs — "Important" تحت create_task): الـ
event loop يحتفظ فقط بمرجع ضعيف (weak reference) للمهمة، فلو لم يُحتفَظ
بمرجع قوي بمكان آخر يمكن جمعها (garbage collected) في منتصف تنفيذها —
_pending_tasks أدناه هو ذاك المرجع القوي (نمط موثّق رسميًا)، ويُزال منه
تلقائيًا عبر add_done_callback فور الانتهاء (نجاحًا أو فشلًا) لتفادي أي
تسريب ذاكرة طويل المدى.

يُستخدَم حاليًا من: api/v1/meetings.py، api/v1/tasks.py، api/v1/decisions.py،
api/v1/committees.py — كل استدعاءات إشعارات البريد بعد commit ناجح، بدلًا
من background_tasks.add_task المُزالة من كل هذي الملفات.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

# مرجع قوي إلزامي (راجعي الـ docstring أعلاه) — بدونه قد تُجمَع المهمة
# (garbage collected) قبل اكتمالها.
_pending_tasks: set[asyncio.Task] = set()


def run_detached(coro: Coroutine[Any, Any, None]) -> None:
    """يجدول coroutine (مثال: notification_service.notify_meeting_created(...))
    ليعمل بمعزل تام عن الطلب الحالي — بديل عن background_tasks.add_task
    لهذا السبب تحديدًا. أي استثناء غير متوقع منها يُسجَّل هنا (بدل أن
    يضيع بصمت أو يظهر كـ"Task exception was never retrieved" بالسجلات) —
    احتياط إضافي فقط، فكل دوال notify_* وsend_email أصلًا تُمسك كل
    استثناءاتها داخليًا ولا ترفع شيئًا للمستدعي."""
    task = asyncio.create_task(coro)
    _pending_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _pending_tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.exception(
                "مهمة خلفية منفصلة (run_detached) فشلت بشكل غير متوقع", exc_info=t.exception()
            )

    task.add_done_callback(_on_done)
