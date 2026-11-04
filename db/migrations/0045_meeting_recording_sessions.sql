-- =====================================================================
-- 0045_meeting_recording_sessions.sql
-- الهدف: الرجوع من Microsoft Teams إلى Agora للاجتماعات عن بعد (قرار لاما
-- 2026-11-04 — "ما عاد عجبني تيمز مع تسجيل الدخول مايكروسوفت")، مع تسجيل
-- صوتي لكل الأعضاء يُرفع على دفعات أثناء الاجتماع.
--
-- قواعد العمل المعتمدة (لاما 2026-11-04):
-- 1) التسجيل صوت فقط، لكن يشمل صوت كل الأعضاء (مو مايك الرئيس بس).
-- 2) التسجيل يبدأ بزر من رئيس اللجنة (لا تلقائي).
-- 3) "ما أبي أي سلبيات": التسجيل القديم كان يُرفع مرة وحدة بنهاية الاجتماع —
--    لو انقفلت صفحة الرئيس أو انقطع النت يضيع كله. الحين يُرفع على دفعات
--    (قطعة كل ~30 ثانية)، فأقصى خسارة عند الانقطاع آخر قطعة فقط.
-- 4) Teams محفوظ (فرع archive/teams-integration + إعداد MEETING_PROVIDER)،
--    وأعمدة teams_* بجدول meetings تبقى كما هي — ما نحذف شي.
--
-- التغييرات:
-- أ) meeting_recording_sessions: جلسة تسجيل واحدة (من ضغطة "تسجيل" لحد
--    "إيقاف"). القطع نفسها ملفات بالتخزين (Supabase Storage) تحت مسار الجلسة؛
--    هذا الجدول يتابع حالتها:
--    - status: recording (جارية) / finalized (دُمجت بملف واحد بـmeeting_recordings)
--      / failed (تعذّر الدمج — error_message).
--    - last_seq: رقم آخر قطعة وصلت (القطع مرقّمة من 0) — الدمج يقرأ 0..last_seq.
--    - last_chunk_at: لاكتشاف جلسة "يتيمة" (صفحة الرئيس انقفلت بدون إيقاف):
--      المجدوِل يدمجها تلقائيًا بعد دقائق من آخر قطعة، فما يضيع التسجيل.
--    - recording_id: الملف النهائي بعد الدمج (يدخل مسار المسودة الحالي كما هو).
-- ب) فهرس فريد جزئي: جلسة تسجيل "جارية" وحدة فقط لكل اجتماع.
-- ج) تفعيل RLS على الجدول الجديد + جدولي 0044 (نسيناه هناك) — الباك-إند
--    يتصل بصلاحية مالك الجداول فلا يتأثر، وواجهة Supabase العامة (anon) تُمنع.
--
-- أثر على البيانات القائمة: لا شيء (جدول جديد + تفعيل RLS بلا سياسات).
-- =====================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS meeting_recording_sessions (
    session_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id      UUID NOT NULL REFERENCES meetings(meeting_id) ON DELETE CASCADE,
    started_by      UUID NOT NULL REFERENCES users(user_id),
    mime_type       VARCHAR(100) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'recording'
                    CHECK (status IN ('recording', 'finalized', 'failed')),
    last_seq        INTEGER NOT NULL DEFAULT -1 CHECK (last_seq >= -1),
    total_bytes     BIGINT NOT NULL DEFAULT 0 CHECK (total_bytes >= 0),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_chunk_at   TIMESTAMPTZ,
    finalized_at    TIMESTAMPTZ,
    recording_id    UUID REFERENCES meeting_recordings(recording_id) ON DELETE SET NULL,
    error_message   TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_recording_sessions_one_active
    ON meeting_recording_sessions (meeting_id)
    WHERE status = 'recording';

CREATE INDEX IF NOT EXISTS idx_recording_sessions_active_last_chunk
    ON meeting_recording_sessions (last_chunk_at)
    WHERE status = 'recording';

ALTER TABLE meeting_recording_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_transcript_segments ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_agenda_sessions ENABLE ROW LEVEL SECURITY;

COMMIT;
