-- =====================================================================
-- 0041_meetings_teams_integration.sql
-- الهدف: تجهيز قاعدة البيانات لتكامل Microsoft Teams للاجتماعات عن بعد
-- (mode = 'remote') — قرار لاما 2026-11-02: الانتقال من Agora إلى Teams
-- (مطابقةً للـSRS §1.2: "يتكامل النظام مع مايكروسوفت تيمز").
--
-- قواعد العمل المعتمدة (لاما 2026-11-02):
-- 1) كل اجتماع remote يُنشأ له اجتماع Teams عبر Microsoft Graph، باسم حساب
--    منظِّم واحد مُعرَّف بالبيئة (TEAMS_ORGANIZER_EMAIL) — رئيس اللجنة
--    co-organizer وبقية الأعضاء attendees. لو فشل إنشاء اجتماع Teams يُرفض
--    إنشاء الاجتماع كاملًا (لا اجتماع remote بلا رابط).
-- 2) الاجتماع الحضوري (in_person) لا يُنشأ له اجتماع Teams إطلاقًا، ويبقى
--    مساره الصوتي الحالي (رفع تسجيل المتصفح → Gemini) كما هو.
-- 3) مسودة الاجتماع remote تُولَّد من تفريغ Teams الرسمي (Transcript) بدل
--    ملف صوتي مرفوع — لذا meeting_drafts.recording_id يصبح اختياريًا.
--
-- التغييرات:
-- أ) meetings.teams_organizer_id (جديد): معرّف Entra (Object ID) لحساب
--    المنظِّم وقت إنشاء اجتماع Teams. ضروري لأن كل استدعاءات Graph اللاحقة
--    (تعديل/حذف/سحب التفريغ والتسجيل) تتم عبر
--    /users/{organizerId}/onlineMeetings/{meetingId} — ولو تغيّر حساب
--    المنظِّم بالبيئة لاحقًا (مثلًا من حساب مؤقت إلى حساب مخصص
--    meetings@...) تبقى الاجتماعات القديمة قابلة للوصول عبر منظِّمها الأصلي.
--    teams_meeting_id/teams_join_url موجودان أصلًا منذ 0018 (محجوزان لهذه
--    المرحلة) — لا يُعاد إنشاؤهما.
-- ب) فهرس UNIQUE جزئي على meetings.teams_meeting_id: لا يرتبط اجتماع Teams
--    واحد بأكثر من اجتماع بالنظام.
-- ج) CHECK: حقول Teams الثلاثة تُعبَّأ معًا أو تبقى فارغة معًا، ولا تُعبَّأ
--    إلا لاجتماع remote.
-- د) meeting_drafts.source (جديد) + recording_id اختياري، مع CHECK يربطهما:
--    audio_upload يتطلب recording_id، وteams_transcript يمنعه.
--
-- أثر على البيانات القائمة: لا شيء — حقول Teams كلها NULL حاليًا (لم
-- تُستخدَم قبل هذه المرحلة)، وكل المسودات القائمة مصدرها audio_upload
-- تلقائيًا عبر القيمة الافتراضية ولها recording_id أصلًا. لو فشل أحد قيود
-- CHECK عند التطبيق فهذا يعني وجود بيانات غير متسقة يجب مراجعتها يدويًا
-- قبل إعادة المحاولة (لا تُعدَّل بيانات تلقائيًا هنا).
-- =====================================================================

BEGIN;

-- ============================== أ + ب + ج: الاجتماعات ==============================
ALTER TABLE meetings
    ADD COLUMN teams_organizer_id UUID;

CREATE UNIQUE INDEX uq_meetings_teams_meeting_id
    ON meetings (teams_meeting_id)
    WHERE teams_meeting_id IS NOT NULL;

ALTER TABLE meetings
    ADD CONSTRAINT chk_meetings_teams_fields_together CHECK (
        (teams_meeting_id IS NULL AND teams_join_url IS NULL AND teams_organizer_id IS NULL)
        OR
        (teams_meeting_id IS NOT NULL AND teams_join_url IS NOT NULL AND teams_organizer_id IS NOT NULL)
    );

ALTER TABLE meetings
    ADD CONSTRAINT chk_meetings_teams_only_remote CHECK (
        teams_meeting_id IS NULL OR mode = 'remote'
    );

-- ============================== د: مصدر المسودة ==============================
CREATE TYPE meeting_draft_source AS ENUM (
    'audio_upload',      -- تسجيل صوتي مرفوع من المتصفح (المسار الحالي — اجتماع حضوري)
    'teams_transcript'   -- تفريغ Teams الرسمي (اجتماع عن بعد)
);

ALTER TABLE meeting_drafts
    ADD COLUMN source meeting_draft_source NOT NULL DEFAULT 'audio_upload';

ALTER TABLE meeting_drafts
    ALTER COLUMN recording_id DROP NOT NULL;

ALTER TABLE meeting_drafts
    ADD CONSTRAINT chk_meeting_drafts_source_recording CHECK (
        (source = 'audio_upload' AND recording_id IS NOT NULL)
        OR
        (source = 'teams_transcript' AND recording_id IS NULL)
    );

COMMIT;
