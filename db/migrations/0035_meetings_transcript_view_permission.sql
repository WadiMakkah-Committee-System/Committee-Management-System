-- =====================================================================
-- 0035_meetings_transcript_view_permission.sql
-- الهدف: تفصيل صلاحية عرض مسودة الاجتماع إلى ثلاث صلاحيات مستقلة قابلة
-- للمنح كل واحدة على حدة (طلب لاما 2026-09-16): "عرض التفريغ الصوتي"
-- (جديدة هنا)، "عرض ملخص الاجتماع" (meetings.summary.view — موجودة
-- بالكتالوج منذ 0006 لكن لم تُستخدَم بأي تحقق فعلي حتى الآن)، و"عرض
-- البنود المستخرجة" (ai_items.view — موجودة أيضًا منذ 0006 بنفس الحال).
--
-- خلفية القرار: لاما منحت meetings.draft.view وmeetings.summary.view
-- يدويًا لدور "عضو اللجنة" من شاشة "الأدوار والصلاحيات" واختبرت — ما
-- زال العضو يواجه "ليست لديك الصلاحية". السبب الفعلي المكتشَف بعد
-- المراجعة: قسم "البنود المستخرجة" بصفحة تفاصيل الاجتماع
-- (frontend/src/features/meetings/MeetingDetailPage.tsx، الشرط عند
-- السطر ~1175) كان مشروطًا بمتغيّر canManage محسوب بالكامل من صلاحية
-- meetings.update/meetings.delete النظامية أو كون المستخدم رئيس اللجنة
-- تحديدًا — بصرف النظر كليًا عن أي صلاحية Committee Role تُمنح فعليًا
-- من هذه الشاشة. هذا الملف يعالج الجزء الخاص بقاعدة البيانات (صلاحية
-- جديدة + منحها لعضو اللجنة)؛ إصلاح canManage نفسه بالفرونت-إند وربط
-- meetings.summary.view/ai_items.view فعليًا بالباك-إند (بعد هذا الملف
-- في نفس الدفعة) هما ما يُصلح المشكلة الفعلية المُبلَّغ عنها.
--
-- 1) صلاحية جديدة: عرض التفريغ الصوتي الكامل للمسودة (full_transcript)
--    — نفس فئة "الاجتماعات" (meetings) بالضبط مثل meetings.draft.view/
--    meetings.summary.view المجاورتين لها (لاما تراجع هذه الصلاحيات من
--    قسم "الاجتماعات" بالواجهة، وليس "البنود المستخرجة من الذكاء
--    الاصطناعي" كما افتُرض ابتدائيًا).
INSERT INTO permissions (code, category, label_ar, sort_order, kind) VALUES
    ('meetings.transcript.view', 'meetings', 'عرض التفريغ الصوتي', 90, 'system');

-- 2) إعادة تسمية ai_items.view لتطابق نص لاما الحرفي بالضبط ("عرض البنود
--    المستخرجة") — كانت "عرض قائمة البنود" (فرق تسمية فقط، الكود نفسه،
--    أول ربط فعلي حقيقي لها بالإنفاذ يأتي بتعديل meeting_service.py
--    بعد هذا الملف مباشرة).
UPDATE permissions SET label_ar = 'عرض البنود المستخرجة' WHERE code = 'ai_items.view';

-- 3) منح الصلاحيات الثلاث (الجديدة + الموجودتين غير المفعّلتين) لعضو
--    اللجنة — طلب لاما الصريح. رئيس اللجنة لا يحتاج منحًا هنا: يملك
--    meetings.draft.view أصلًا (وصول كامل غير مجزّأ)، ومنطق get_draft/
--    list_extracted_items (بعد هذا الملف) يقبل أيًّا من الصلاحيتين
--    (الكاملة أو الجزئية) — OR وليس AND.
INSERT INTO role_permissions (role_id, permission_id, scope)
SELECT r.role_id, p.permission_id, 'all'
FROM roles r
JOIN permissions p ON p.code IN (
    'meetings.transcript.view', 'meetings.summary.view', 'ai_items.view'
)
WHERE r.committee_role_slug = 'member'
ON CONFLICT (role_id, permission_id) DO NOTHING;
