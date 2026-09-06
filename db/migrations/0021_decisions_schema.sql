-- =====================================================================
-- 0021_decisions_schema.sql
-- الهدف: وحدة "إدارة القرارات" — القرارات المستقلة فقط (تُصدَر مباشرة من
-- واجهة القرارات، §5.1/§7 BRS-SRS) — بدون القرارات المستخرجة من بند
-- اجتماع بالذكاء الاصطناعي (تلك تُبنى لاحقًا مع تكامل AI/Teams، قرار
-- صاحبة المشروع 2026-09-02). لا تُلمس meetings.* بهذا الملف إطلاقًا.
--
-- ملاحظات تصميم واجتهادات موثّقة (بالاتفاق مع صاحبة المشروع 2026-09-02):
-- 1) التعديل/الحذف (FR-017/018: "متاح فقط قبل اعتماد القرار" حرفيًا) —
--    يُمنعان فعليًا من لحظة status != 'pending' (أي من لحظة فتح التصويت،
--    وليس فقط بعد الاعتماد الفعلي) — تعديل قرار وسط تصويت جارٍ غير منطقي
--    عمليًا، رغم أن النص الحرفي يذكر "الاعتماد" فقط.
-- 2) موعد اختياري لإغلاق التصويت (voting_deadline، عمود جديد لا يذكره
--    BRS/SRS صراحة) — يحل تعارضًا ظاهريًا بين FR-011 ("النتيجة تُعرض فور
--    اكتمال تصويت الجميع") وFR-012 ("أغلبية المصوّتين فعليًا" — يفترض
--    مشاركة جزئية جائزة). بدون موعد → يُغلق التصويت فقط عند اكتمال الجميع
--    (يطابق FR-011 حرفيًا). بموعد → يُغلق تلقائيًا عند حلوله حتى لو لم
--    يصوّت الجميع، والنتيجة تُحسب على من صوّت فعليًا (يطابق FR-012 حرفيًا).
--    نمط شائع بمنصات الحوكمة العالمية (Diligent/BoardEffect/OnBoard).
-- 3) بدون أي تذكيرات (يدوية أو تلقائية) بهذه المرحلة — صاحبة المشروع
--    ستبنيها بنفسها لاحقًا بعد بناء بنية جدولة مهام عامة بالمشروع (لا
--    توجد حاليًا — لا Celery ولا APScheduler).
-- 4) المنفذون (decision_assignees) يجب أن يكونوا من أعضاء اللجنة نفسها
--    فقط (بما فيهم رئيسها) — بنفس قيد meeting_participants بالضبط
--    (BRS/SRS لا ينص صراحة، تأكيد صريح من صاحبة المشروع 2026-09-02).
-- 5) بدون أي ربط بالوثائق (document_links) بهذه المرحلة — يُبنى من طرف
--    آخر بالفريق حاليًا (تفاديًا للتعارض)، سيُدفع على GitHub قريبًا.
-- 6) لا يوجد جدول "إشعارات" فعلي بالمشروع بعد (Notifications) — الأحداث
--    التي يذكر BRS/SRS إرسال إشعار عندها (اعتماد/رفض) تُسجَّل بـaudit_logs
--    فقط بطبقة الخدمة، بنفس النمط المتّبع أصلًا بوحدة الاجتماعات (لا يوجد
--    تسليم فعلي للإشعار — بنية الإشعارات نفسها غير موجودة بالمشروع كله).
-- =====================================================================

CREATE TYPE decision_classification AS ENUM (
    'final',   -- قرار نهائي — يُعتمد مباشرة بدون تصويت (§5.4)
    'voting'   -- قرار خاضع للتصويت الجماعي (§5.5)
);

CREATE TYPE decision_status AS ENUM (
    'pending',   -- مسجَّل، بانتظار اعتماد مباشر (نهائي) أو فتح تصويت
    'voting',    -- التصويت مفتوح حاليًا
    'approved',  -- معتمَد (نهائي بالاعتماد المباشر، أو بالتصويت+الأغلبية)
    'rejected'   -- مرفوض تلقائيًا (تصويت لم يحقق الأغلبية)
);

CREATE TYPE decision_vote_choice AS ENUM ('approve', 'reject');

-- ============================== القرار ==============================
CREATE TABLE decisions (
    decision_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    committee_id     UUID NOT NULL REFERENCES committees(committee_id),
    title            VARCHAR(255) NOT NULL,               -- اسم القرار (FR-005)
    classification   decision_classification NOT NULL,
    status           decision_status NOT NULL DEFAULT 'pending',

    start_date       DATE NOT NULL,                       -- تاريخ بداية التنفيذ
    end_date         DATE NOT NULL,                        -- تاريخ نهاية التنفيذ

    -- التصويت — راجعي ملاحظة التصميم (2) أعلاه.
    voting_opened_at   TIMESTAMPTZ,
    voting_deadline     TIMESTAMPTZ,   -- اختياري — NULL يعني: أغلق فقط عند اكتمال الجميع
    voting_closed_at    TIMESTAMPTZ,

    rejection_reason TEXT,             -- تُسجَّل تلقائيًا عند الرفض الآلي (FR-014)

    created_by       UUID NOT NULL REFERENCES users(user_id),

    deleted_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT decisions_end_after_start_chk CHECK (end_date >= start_date)
);

CREATE INDEX idx_decisions_committee_id ON decisions (committee_id);
CREATE INDEX idx_decisions_status       ON decisions (status);

CREATE TRIGGER trg_decisions_set_updated_at
    BEFORE UPDATE ON decisions
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ============================== المنفذون ==============================
-- من أعضاء اللجنة فقط (بمن فيهم رئيسها) — راجعي ملاحظة التصميم (4).
CREATE TABLE decision_assignees (
    decision_id UUID NOT NULL REFERENCES decisions(decision_id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(user_id),
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (decision_id, user_id)
);

CREATE INDEX idx_decision_assignees_user_id ON decision_assignees (user_id);

-- ============================== الأصوات ==============================
-- عضو واحد = صوت واحد لكل قرار (بما فيه رئيس اللجنة، FR-010) — قابل
-- للتغيير طالما status='voting' (upsert بطبقة الخدمة، لا قيد هنا يمنعه).
CREATE TABLE decision_votes (
    decision_id UUID NOT NULL REFERENCES decisions(decision_id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(user_id),
    choice      decision_vote_choice NOT NULL,
    voted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (decision_id, user_id)
);

-- ============================== Row Level Security ==============================
ALTER TABLE decisions           ENABLE ROW LEVEL SECURITY;
ALTER TABLE decision_assignees  ENABLE ROW LEVEL SECURITY;
ALTER TABLE decision_votes      ENABLE ROW LEVEL SECURITY;
