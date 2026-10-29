-- نوع مدة اللجنة: دائمة (permanent) أو مؤقتة (temporary) — طلب صاحبة
-- المشروع 2026-10-29.
--
-- قرار موثّق يخالف FR-COM-002 بالـSRS (الذي يشترط تاريخ نهاية لكل لجنة)،
-- بقرار صريح من صاحبة المشروع، والـSRS سيُحدَّث لاحقًا:
-- - مؤقتة: تاريخ البداية والنهاية إلزاميان (end_date > start_date) — نفس
--   السلوك السابق تمامًا.
-- - دائمة: بلا أي تاريخ (start_date وend_date كلاهما NULL)، وتُعتبر جارية
--   (ongoing) دائمًا من لحظة الاعتماد.
-- - النوع يُحدَّد بطلب التشكيل فقط، ويُنسَخ للجنة عند الاعتماد، ولا يتغيّر
--   بعدها (يُفرض بطبقة الخدمة: update_committee يرفض تعديل فترة لجنة دائمة).
--
-- كل الطلبات واللجان القائمة لها تواريخ أصلًا، فتصبح 'temporary' تلقائيًا
-- عبر القيمة الافتراضية — بلا أي فقدان أو تغيير لبيانات قائمة.

CREATE TYPE committee_duration_type AS ENUM (
    'temporary',  -- مؤقتة: بفترة محددة (بداية + نهاية)
    'permanent'   -- دائمة: بلا تواريخ
);

-- ============================== طلبات التشكيل ==============================
ALTER TABLE committee_formation_requests
    ADD COLUMN duration_type committee_duration_type NOT NULL DEFAULT 'temporary';

ALTER TABLE committee_formation_requests
    ALTER COLUMN start_date DROP NOT NULL,
    ALTER COLUMN end_date   DROP NOT NULL,
    DROP CONSTRAINT chk_committee_formation_requests_dates;

ALTER TABLE committee_formation_requests
    ADD CONSTRAINT chk_committee_formation_requests_dates CHECK (
        (duration_type = 'temporary'
            AND start_date IS NOT NULL AND end_date IS NOT NULL AND end_date > start_date)
        OR
        (duration_type = 'permanent' AND start_date IS NULL AND end_date IS NULL)
    );

-- ============================== اللجان المعتمدة ==============================
ALTER TABLE committees
    ADD COLUMN duration_type committee_duration_type NOT NULL DEFAULT 'temporary';

ALTER TABLE committees
    ALTER COLUMN start_date DROP NOT NULL,
    ALTER COLUMN end_date   DROP NOT NULL,
    DROP CONSTRAINT chk_committees_dates;

ALTER TABLE committees
    ADD CONSTRAINT chk_committees_dates CHECK (
        (duration_type = 'temporary'
            AND start_date IS NOT NULL AND end_date IS NOT NULL AND end_date > start_date)
        OR
        (duration_type = 'permanent' AND start_date IS NULL AND end_date IS NULL)
    );

-- ملاحظة: فهرس idx_committees_end_date_pending_expiry (0033) يبقى كما هو —
-- اللجان الدائمة (end_date IS NULL) لا تطابق شرط "end_date < اليوم" بفحص
-- الانتهاء المجدول (app/core/scheduler.py)، فلا تُشعَر بانتهاء أبدًا.
