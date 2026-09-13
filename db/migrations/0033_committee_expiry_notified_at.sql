-- عمود منع تكرار إشعار "انتهت فترة اللجنة" — جزء من "قاعدة فترة اللجنة"
-- (طلب صاحبة المشروع 2026-09-13). راجعي app/core/scheduler.py
-- (_check_committee_expiry) وapp/services/notification_service.py
-- (notify_committee_expired) لآلية الاستخدام الكاملة، ونفس نمط
-- reminder_sent_at/overdue_notified_at بجدول tasks (الهجرة 0031).

ALTER TABLE committees ADD COLUMN expiry_notified_at TIMESTAMPTZ;

CREATE INDEX idx_committees_end_date_pending_expiry
    ON committees (end_date)
    WHERE deleted_at IS NULL AND expiry_notified_at IS NULL;
