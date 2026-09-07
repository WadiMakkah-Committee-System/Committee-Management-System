-- =====================================================================
-- 0025_decision_vote_options.sql
-- الهدف: خيارات تصويت مخصّصة يحدّدها رئيس اللجنة عند فتح التصويت (بدل
-- الخيارين الثابتين موافق/غير موافق) — قرار صريح من صاحبة المشروع
-- 2026-09-07: "الي يحدد بيانات التصويت رئيس اللجنة بس والأعضاء يقررون".
--
-- ملاحظة ترقيم: أُعيد ترقيم هذا الملف من 0021 (تصادم مع
-- 0021_document_links_role.sql من لاما، نفس الرقم لملفين مختلفين) إلى
-- 0025 (بعد 0024_tasks_schema.sql، آخر ملف موجود وقت هذا التغيير).
--
-- ملاحظة تصميم مهمة (كيف تبقى الأغلبية التلقائية "ذكية" مع خيارات حرة):
-- كل خيار له is_approving (تحدّده رئيسة اللجنة وقت كتابة الخيارات — علامة
-- "يُحسب موافقة"، وليس افتراضًا تلقائيًا من النص). عند إغلاق التصويت
-- (_maybe_close_voting بـdecision_service.py):
--   - لو فيه خيار واحد على الأقل is_approving=true: الأغلبية = مجموع
--     أصوات كل الخيارات المعلَّمة is_approving مقابل إجمالي الأصوات، بنفس
--     قاعدة >50% السابقة تمامًا (تعميم للحالة الثنائية القديمة موافق/غير
--     موافق، وليست قاعدة جديدة).
--   - لو ولا خيار معلَّم (استطلاع رأي بحت، بلا مفهوم "موافقة" أصلًا): لا
--     رفض تلقائي — يبقى القرار بحالة 'voting' بعد الإغلاق، ورئيسة اللجنة
--     تعتمده يدويًا بناءً على النتائج المعروضة (تقدير شخصي، لا خوارزمية).
-- =====================================================================

CREATE TABLE decision_vote_options (
    option_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id  UUID NOT NULL REFERENCES decisions(decision_id) ON DELETE CASCADE,
    label        VARCHAR(255) NOT NULL,
    is_approving BOOLEAN NOT NULL DEFAULT false,
    sort_order   INT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_decision_vote_options_decision_id ON decision_vote_options (decision_id);

-- decision_votes: يصوّت العضو لخيار محدَّد بدل قيمة enum ثابتة
-- (decision_vote_choice) — لا بيانات حقيقية بعد (بيانات تجريبية فقط)،
-- فالتغيير المباشر آمن.
ALTER TABLE decision_votes ADD COLUMN option_id UUID REFERENCES decision_vote_options(option_id);
ALTER TABLE decision_votes DROP COLUMN choice;
ALTER TABLE decision_votes ALTER COLUMN option_id SET NOT NULL;

DROP TYPE decision_vote_choice;
