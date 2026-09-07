-- =====================================================================
-- 0028_meeting_extracted_items.sql
-- الهدف: "البنود المستخرجة من الاجتماع" (FR-TASK-005 إلى FR-TASK-012 +
-- FR-DEC-001 إلى FR-DEC-004، §4.2/§5.2 SRS) — قائمة بنود عامة (نص فقط،
-- بدون تصنيف مسبق) يستخرجها الذكاء الاصطناعي من ملخص الاجتماع بناءً على
-- طلب رئيس اللجنة (أو يضيفها يدويًا)، ثم يقوم رئيس اللجنة يدويًا إما
-- بحذف كل بند أو "تعيينه" كـ"مهمة" أو "قرار" — يُبنى الآن مع تكامل AI،
-- بالضبط كما أُجِّل صراحة برأسي migration 0021 و0024. راجعي رأس
-- app/models/meeting_extracted_item.py للتصميم الكامل والاجتهادات
-- الموثّقة (قرار صاحبة المشروع 2026-09-07: شاشة ترياج واحدة بصفحة
-- تفاصيل الاجتماع، بدون فصل UI بين المهام/القرارات).
--
-- الجدول لا يخزّن بيانات المهمة/القرار نفسها (تاريخ/مسؤول/تصنيف) — فقط
-- نص البند + حالته + مرجع للسجل الفعلي بعد "التعيين" (tasks/decisions
-- تُنشأ عبر task_service/decision_service الموجودَين أصلًا، بلا تكرار
-- منطق التحقق).
-- =====================================================================

CREATE TYPE meeting_extracted_item_status AS ENUM (
    'pending',            -- بانتظار قرار رئيس اللجنة (تعيين/حذف)
    'assigned_task',      -- حُوِّل إلى مهمة فعلية (linked_task_id)
    'assigned_decision'   -- حُوِّل إلى قرار فعلي (linked_decision_id)
);

CREATE TABLE meeting_extracted_items (
    item_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id         UUID NOT NULL REFERENCES meetings(meeting_id) ON DELETE CASCADE,
    text               TEXT NOT NULL,

    source             VARCHAR(10) NOT NULL DEFAULT 'ai',  -- 'ai' | 'manual'
    status             meeting_extracted_item_status NOT NULL DEFAULT 'pending',

    linked_task_id     UUID REFERENCES tasks(task_id) ON DELETE SET NULL,
    linked_decision_id UUID REFERENCES decisions(decision_id) ON DELETE SET NULL,

    created_by         UUID NOT NULL REFERENCES users(user_id),

    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT meeting_extracted_items_source_chk CHECK (source IN ('ai', 'manual'))
);

CREATE INDEX idx_meeting_extracted_items_meeting_id ON meeting_extracted_items (meeting_id);
CREATE INDEX idx_meeting_extracted_items_status     ON meeting_extracted_items (status);

CREATE TRIGGER trg_meeting_extracted_items_set_updated_at
    BEFORE UPDATE ON meeting_extracted_items
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

ALTER TABLE meeting_extracted_items ENABLE ROW LEVEL SECURITY;
