-- =====================================================================
-- 0020_meetings_mode_location.sql
-- الهدف: استبدال meeting_type (نص حر) بحقل mode مقيَّد (عن بعد/حضوري)
-- + location (مكان الاجتماع داخل الشركة، إلزامي فقط لو حضوري) — طلب
-- صريح من صاحبة المشروع 2026-09-01: "نوع الاجتماع" هو بالضبط هذا الخيار
-- الثنائي، وليس نصًا حرًا كما افترضنا سابقًا في 0018 (لا توجد بيانات حية
-- تعتمد على meeting_type الحر — صف واحد فقط بقيمة NULL، فالحذف آمن).
--
-- ملاحظة مزامنة (2026-09-02): هذا الملف طُبِّق مباشرة على قاعدة Supabase
-- الحقيقية قبل أن يُنسخ إلى هذا المستودع محليًا — أعيد إنشاؤه هنا حرفيًا
-- (من supabase_migrations.schema_migrations) ليطابق الفعلي 100%، بدل
-- الملف المحلي القديم بنفس الاسم الذي كان يضيف location فقط ويُبقي على
-- meeting_type (لم يُطبَّق قط على القاعدة الحقيقية بهذا التصميم).
-- =====================================================================

CREATE TYPE meeting_mode AS ENUM ('remote', 'in_person');

ALTER TABLE meetings DROP COLUMN meeting_type;

ALTER TABLE meetings ADD COLUMN mode meeting_mode NOT NULL DEFAULT 'remote';
ALTER TABLE meetings ALTER COLUMN mode DROP DEFAULT;

ALTER TABLE meetings ADD COLUMN location VARCHAR(255);

ALTER TABLE meetings ADD CONSTRAINT meetings_location_required_when_in_person_chk CHECK (
    (mode = 'in_person' AND location IS NOT NULL) OR (mode = 'remote')
);
