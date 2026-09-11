-- =====================================================================
-- 0031_task_priority_reminder.sql
-- الهدف: إضافة "الأولوية"، و"تذكير قبل الاستحقاق"، و"تنبيه فوري لرئيس
-- اللجنة عند التأخر" لوحدة المهام (tasks، migration 0024) — طلب صاحبة
-- المشروع 2026-09-11، بعد بحث في الأنظمة العالمية (Jira/Asana/
-- Microsoft Planner) حول حقول المهمة القياسية.
--
-- ملاحظات تصميم واجتهادات موثّقة:
-- 1) priority: enum بثلاث درجات (low/medium/high) — أبسط من نموذج Jira
--    الخماسي (Highest..Lowest)، يناسب حجم نظام إدارة لجان لا Backlog
--    برمجي ضخم. الافتراضي medium.
-- 2) "متأخرة" (Overdue) نفسها **لا** تُخزَّن كحالة أو عمود — قيمة محسوبة
--    بطبقة الواجهة من (end_date < اليوم AND status != completed)، بنفس
--    النمط الموثّق بحثيًا عن Jira. لا عمود لها بهذا الملف عمدًا.
-- 3) reminder_offset_days: عدد الأيام قبل end_date التي يُرسَل عندها
--    تذكير للمسؤول عن المهمة. افتراضي 1 (يوم واحد قبل الاستحقاق)،
--    قابل للتعديل اختياريًا من رئيس اللجنة عند إنشاء/تعديل المهمة.
-- 4) reminder_sent_at / overdue_notified_at: طابعا زمن لمنع تكرار
--    الإرسال من المهمة المجدولة (راجعي app/core/scheduler.py) التي
--    تفحص الجدول دوريًا — بدون Celery/APScheduler (لا اتصال شبكة
--    لتثبيت حزم جديدة ببيئة التطوير الحالية)؛ حلقة asyncio بسيطة داخل
--    عملية السيرفر نفسها كافية لحجم النظام هذا. overdue_notified_at
--    يُرسَل مرة واحدة فقط لحظة أول تأخر (ليس يوميًا)، بخلاف التذكير.
-- =====================================================================

CREATE TYPE task_priority AS ENUM (
    'low',      -- منخفضة
    'medium',   -- متوسطة — الافتراضية
    'high'      -- عالية
);

ALTER TABLE tasks
    ADD COLUMN priority             task_priority NOT NULL DEFAULT 'medium',
    ADD COLUMN reminder_offset_days SMALLINT NOT NULL DEFAULT 1
        CONSTRAINT tasks_reminder_offset_days_chk CHECK (reminder_offset_days BETWEEN 0 AND 30),
    ADD COLUMN reminder_sent_at     TIMESTAMPTZ,
    ADD COLUMN overdue_notified_at  TIMESTAMPTZ;

CREATE INDEX idx_tasks_priority ON tasks (priority);
