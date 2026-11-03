-- =====================================================================
-- 0044_meeting_live_transcript_and_agenda_sessions.sql
-- الهدف: الدفعة 3 من تحسينات الاجتماع (قرار لاما 2026-11-03):
-- الترجمة النصية الحية + "وش فاتني؟" + إحصائيات الاجتماع.
--
-- قواعد العمل المعتمدة (لاما 2026-11-03):
-- 1) الترجمة النصية يشغّلها رئيس اللجنة للكل، وكل عضو يقدر يخفي العرض عنده.
--    الجمل المكتملة (Final) تُحفظ بالمنصة — جهاز الرئيس هو اللي يرسلها (مصدر
--    واحد، بدون تكرار).
-- 2) "وش فاتني؟" يلخّص بـGemini آخر دقائق من هذا النص.
-- 3) الإحصائيات بعد الاجتماع: مدة كلام كل عضو (تقديرية من النص)، والوقت
--    الفعلي لكل بند مقارنةً بالمؤقت.
--
-- التغييرات:
-- أ) meeting_transcript_segments: جملة مكتملة لكل صف — المتحدث (مستخدم المنصة
--    لو عرفناه + الاسم الظاهر)، النص، وقت قولها، والبند قيد المناقشة وقتها.
--    client_key + UNIQUE: نفس الجملة لو انرسلت مرتين (إعادة محاولة) ما تتكرر.
-- ب) meeting_agenda_sessions: كل فترة مناقشة لبند (بداية/نهاية/مدة المؤقت
--    المختارة) — كانت لحظية فقط (Redis)، والحين تُحفظ للإحصائيات.
--
-- أثر على البيانات القائمة: لا شيء (جداول جديدة).
-- =====================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS meeting_transcript_segments (
    segment_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id       UUID NOT NULL REFERENCES meetings(meeting_id) ON DELETE CASCADE,
    client_key       VARCHAR(200) NOT NULL,
    speaker_user_id  UUID REFERENCES users(user_id) ON DELETE SET NULL,
    speaker_name     VARCHAR(200) NOT NULL DEFAULT '',
    text             TEXT NOT NULL,
    spoken_at        TIMESTAMPTZ NOT NULL,
    language         VARCHAR(20),
    agenda_item_id   UUID REFERENCES meeting_agenda_items(agenda_item_id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_transcript_segments_client_key UNIQUE (meeting_id, client_key)
);

CREATE INDEX IF NOT EXISTS idx_transcript_segments_meeting_time
    ON meeting_transcript_segments (meeting_id, spoken_at);

CREATE TABLE IF NOT EXISTS meeting_agenda_sessions (
    session_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id       UUID NOT NULL REFERENCES meetings(meeting_id) ON DELETE CASCADE,
    agenda_item_id   UUID NOT NULL REFERENCES meeting_agenda_items(agenda_item_id) ON DELETE CASCADE,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at         TIMESTAMPTZ,
    planned_seconds  INTEGER CHECK (planned_seconds IS NULL OR planned_seconds > 0)
);

CREATE INDEX IF NOT EXISTS idx_agenda_sessions_meeting ON meeting_agenda_sessions (meeting_id, started_at);

COMMIT;
