-- =====================================================================
-- 0047_meeting_guests.sql
-- الهدف: دخول ضيوف من خارج المنصة للاجتماع برابط (قرار لاما 2026-11-10).
--
-- ⚠️ استثناء موثّق من NFR-SEC-001 (التحقق من هوية المستخدم قبل الوصول) ومن
-- FR-MEET-001/002 (الاجتماعات للأدمن/رئيس اللجنة/عضو اللجنة فقط) — بقرار
-- لاما. التخفيف: الضيف لا يدخل إلا بعد قبول صريح من شخص داخل الاجتماع،
-- ويُنشأ له حساب مؤقت تُسجَّل باسمه كل عملياته (NFR-SEC-004)، وصلاحيته
-- محصورة باجتماع واحد فقط.
--
-- قواعد العمل المعتمدة (لاما 2026-11-10):
-- 1) لكل اجتماع رابط ضيوف واحد عام يُنسخ ويُرسل لأشخاص محددين.
-- 2) الضيف يفتح الرابط ← يكتب اسمه ← فحص المايك والكاميرا ← ينتظر.
-- 3) أي شخص داخل الاجتماع يقبله أو يرفضه.
-- 4) بعد القبول: يسوي داخل الاجتماع كل ما يسويه عضو اللجنة (يشمل التصويت
--    والكتابة بالمحضر وتنزيل المرفقات)، ويظهر بجانب اسمه "ضيف".
-- 5) يُكتب في المحضر "ضيف خارجي".
-- 6) الضيف = مستخدم مؤقت بجدول users (الخيار "أ" — لاما 2026-11-10) حتى
--    تعمل له كل المزايا المربوطة بـusers (التصويت/المحضر/الحضور/التدقيق)
--    بدون تعديل كل وحدة على حدة.
--
-- التغييرات:
-- أ) users.is_guest + users.guest_meeting_id: يميّزان حساب الضيف ويربطانه
--    باجتماع واحد. قيد CHECK يضمن تلازمهما. حساب الضيف: role_id = NULL (لا
--    صلاحيات نظامية إطلاقًا)، كلمة مرور عشوائية غير معروفة لأحد (لا يقدر
--    يسجل دخول بها)، اسم مستخدم/إيميل داخليان فريدان.
-- ب) meetings.guest_link_token: رمز رابط الضيوف (عشوائي طويل، ليس
--    meeting_id). NULL = الرابط غير مفعّل. تغيير الرمز = إيقاف الرابط القديم.
-- ج) meeting_guest_requests: طلبات الدخول (منتظر/مقبول/مرفوض/ملغى). الضيف
--    يتابع طلبه برمز سري يُحفظ مُجزّأً (hash) فقط. user_id يُعبَّأ عند القبول.
-- د) تفعيل RLS على الجدول الجديد (نفس نمط 0045/0046).
--
-- أثر على البيانات القائمة: لا شيء — أعمدة جديدة بقيم افتراضية، وجدول جديد.
-- =====================================================================

BEGIN;

-- ============================ أ) حسابات الضيوف ============================
ALTER TABLE users
    ADD COLUMN is_guest BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN guest_meeting_id UUID REFERENCES meetings(meeting_id);

ALTER TABLE users
    ADD CONSTRAINT users_guest_meeting_chk
    CHECK (is_guest = (guest_meeting_id IS NOT NULL));

COMMENT ON COLUMN users.is_guest IS
    'حساب ضيف مؤقت (0047) — لا يظهر بقوائم المستخدمين، بلا دور نظامي، ولا يسجل دخول بكلمة مرور';
COMMENT ON COLUMN users.guest_meeting_id IS
    'الاجتماع الوحيد المسموح لحساب الضيف — NULL لكل المستخدمين العاديين';

-- استبعاد الضيوف من قوائم المستخدمين بلا تكلفة على المستخدمين العاديين.
CREATE INDEX idx_users_guest_meeting_id ON users (guest_meeting_id) WHERE is_guest;

-- ============================ ب) رابط الضيوف ============================
ALTER TABLE meetings
    ADD COLUMN guest_link_token VARCHAR(64);

COMMENT ON COLUMN meetings.guest_link_token IS
    'رمز رابط دخول الضيوف (0047) — NULL = غير مفعّل؛ تغييره يوقف الرابط السابق';

CREATE UNIQUE INDEX uq_meetings_guest_link_token
    ON meetings (guest_link_token)
    WHERE guest_link_token IS NOT NULL;

-- ============================ ج) طلبات دخول الضيوف ============================
CREATE TYPE meeting_guest_request_status AS ENUM (
    'pending',    -- ينتظر القبول
    'admitted',   -- مقبول (أُنشئ له حساب ضيف — user_id)
    'rejected',   -- مرفوض
    'cancelled'   -- ألغاه الضيف بنفسه أو انتهى الاجتماع قبل البت فيه
);

CREATE TABLE meeting_guest_requests (
    request_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id           UUID NOT NULL REFERENCES meetings(meeting_id) ON DELETE CASCADE,
    display_name         VARCHAR(100) NOT NULL,
    -- رمز سري يتابع به الضيف حالة طلبه (يُعطى له مرة واحدة) — hash فقط.
    request_secret_hash  VARCHAR(255) NOT NULL,
    status               meeting_guest_request_status NOT NULL DEFAULT 'pending',
    user_id              UUID REFERENCES users(user_id),       -- حساب الضيف بعد القبول
    decided_by           UUID REFERENCES users(user_id),       -- من قَبِل/رفض
    decided_at           TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT meeting_guest_requests_name_chk
        CHECK (char_length(btrim(display_name)) BETWEEN 2 AND 100),
    CONSTRAINT meeting_guest_requests_admitted_user_chk
        CHECK ((status = 'admitted') = (user_id IS NOT NULL)),
    CONSTRAINT meeting_guest_requests_decision_chk
        CHECK (
            (status IN ('admitted', 'rejected')) = (decided_by IS NOT NULL AND decided_at IS NOT NULL)
        )
);

CREATE INDEX idx_meeting_guest_requests_meeting_status
    ON meeting_guest_requests (meeting_id, status);
CREATE UNIQUE INDEX uq_meeting_guest_requests_user_id
    ON meeting_guest_requests (user_id)
    WHERE user_id IS NOT NULL;

CREATE TRIGGER trg_meeting_guest_requests_set_updated_at
    BEFORE UPDATE ON meeting_guest_requests
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ============================ د) RLS ============================
ALTER TABLE meeting_guest_requests ENABLE ROW LEVEL SECURITY;

COMMIT;
