-- =====================================================================
-- 0025_meeting_recordings_and_drafts.sql
-- الهدف: تسجيل الاجتماع صوتيًا + تحويله لمسودة بالذكاء الاصطناعي —
-- تطبيق فعلي لصلاحيات meetings.record_audio / meetings.draft.summarize /
-- meetings.draft.view / meetings.summary.view المزروعة أصلًا بكتالوج
-- الصلاحيات (0006_roles_permissions.sql، أسطر 86-89) منذ بداية المشروع
-- ولم تُستخدَم بعد بأي جدول فعلي — هذا أول استخدام حقيقي لها.
--
-- ملاحظة تصميم مهمة: هذا منفصل تمامًا عن فئة الصلاحيات "minutes"
-- (محضر رسمي بقوالب/اعتماد/توقيع/تصدير — minutes.templates.*/approve/
-- sign/export، 0006 أسطر 116-122) — تلك مرحلة لاحقة غير مطلوبة الآن
-- (لا Workflow اعتماد/توقيع هنا، فقط توليد مسودة يقدر رئيس اللجنة
-- يراجعها). لا تُلمس فئة minutes بهذا الملف إطلاقًا.
--
-- قرار مزود الذكاء الاصطناعي (بالاتفاق مع صاحبة المشروع 2026-09-06):
-- Google Gemini (Free Tier) — يقبل ملف صوتي مباشرة ويسوي تفريغ نص +
-- تمييز متحدثين + تلخيص بطلب واحد (راجعي app/core/gemini_client.py
-- وapp/services/meeting_draft_service.py للتفاصيل). لا Whisper ولا
-- OpenAI بهذي المرحلة.
--
-- ============================== التسجيل الصوتي ==============================
-- صف واحد لكل تسجيل مرفوع (نظريًا ممكن أكثر من تسجيل لنفس الاجتماع لو
-- انقطع التسجيل وأعيد رفعه — الأحدث هو المعتمد لتوليد المسودة، لا قيد
-- UNIQUE على meeting_id عمدًا). الملف الفعلي يُخزَّن بنفس Supabase
-- Storage Bucket المستخدَم لوحدة الوثائق (راجعي app/core/storage_client.py)
-- تحت مسار منفصل، وليس عبر document_links — التسجيل الصوتي ليس "وثيقة"
-- بمنطق تلك الوحدة (لا رؤية مركّبة departments/committees له، فقط
-- صلاحية meetings.record_audio/draft.view مباشرة).
CREATE TABLE meeting_recordings (
    recording_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id        UUID NOT NULL REFERENCES meetings(meeting_id),
    storage_path      TEXT NOT NULL,
    file_name         VARCHAR(255) NOT NULL,
    mime_type         VARCHAR(100) NOT NULL,
    file_size_bytes   BIGINT NOT NULL,
    duration_seconds  INTEGER,                              -- من الواجهة (اختياري)، لا نحسبه بالباك-إند

    recorded_by       UUID NOT NULL REFERENCES users(user_id),
    recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at        TIMESTAMPTZ
);

CREATE INDEX idx_meeting_recordings_meeting_id ON meeting_recordings (meeting_id);

-- ============================== المسودة الناتجة من الذكاء الاصطناعي ==============================
-- صف واحد لكل اجتماع (UNIQUE على meeting_id) — إعادة التوليد تستبدل
-- محتوى نفس الصف (updated_at يتحدّث)، لا نراكم نسخًا قديمة (لا حاجة
-- موثّقة لها بهذي المرحلة، بخلاف meeting_recordings أعلاه).
CREATE TYPE meeting_draft_status AS ENUM (
    'pending',     -- طُلب التوليد، لسا ما بدأ فعليًا (نادرًا ما تُرى — العملية مزامنة حاليًا)
    'processing',  -- جاري الاستدعاء لـGemini
    'completed',   -- توليد ناجح، المحتوى جاهز
    'failed'       -- فشل الاستدعاء أو رجع محتوى غير صالح — راجعي error_message
);

CREATE TABLE meeting_drafts (
    draft_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id      UUID NOT NULL UNIQUE REFERENCES meetings(meeting_id),
    recording_id    UUID NOT NULL REFERENCES meeting_recordings(recording_id),

    status          meeting_draft_status NOT NULL DEFAULT 'pending',
    error_message   TEXT,                                   -- فقط لو status='failed'

    -- محتوى المسودة (كل الحقول NULL لحد ما تكتمل العملية بنجاح) —
    -- راجعي MEETING_DRAFT_PROMPT بـgemini_client.py للـSchema الدقيق
    -- المطابق لهذه الأعمدة.
    full_transcript JSONB,   -- [{speaker, start_time, text}] — كل الكلام مع "مين قاله"
    summary         TEXT,    -- ملخص عام (3-6 جمل)
    decisions       JSONB,   -- [{text, proposed_by, approved}]
    action_items    JSONB,   -- [{text, assignee, due_date}]
    key_points      JSONB,   -- [نص] نقاط مهمة

    generated_by    UUID NOT NULL REFERENCES users(user_id), -- رئيس اللجنة اللي طلب التوليد
    generated_at    TIMESTAMPTZ,                              -- وقت اكتمال آخر توليد ناجح

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_meeting_drafts_meeting_id ON meeting_drafts (meeting_id);

CREATE TRIGGER trg_meeting_drafts_set_updated_at
    BEFORE UPDATE ON meeting_drafts
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ============================== Row Level Security ==============================
ALTER TABLE meeting_recordings ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_drafts     ENABLE ROW LEVEL SECURITY;
