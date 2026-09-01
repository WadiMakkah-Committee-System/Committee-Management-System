-- =====================================================================
-- 0016_meetings_schema.sql
-- الهدف: Phase 1 (Database Schema فقط) من وحدة "إدارة الاجتماعات" —
--        FR-MEET-001 → FR-MEET-005 (SRS، §3.1.1/3.1.2) + إدارة جدول
--        الأعمال (§3.1.3). بدون أي تكامل مع Microsoft Teams/Graph API
--        وبدون أي من خدمات الذكاء الاصطناعي (§3.1.5) — قرار موثّق مع
--        صاحبة المشروع 2026-08-31: تُبنى البنية التحتية أولًا، والتكامل
--        الخارجي يُضاف لاحقًا بـmigration منفصل دون تعديل هذا الملف.
--
-- ملاحظات تصميم مهمة:
-- 1) لا يوجد جدول "مرفقات اجتماع" مستقل هنا عمدًا — جدول document_links
--    (0012_documents_schema.sql) صُمم أصلًا وبالنص الصريح ليكون "قابل
--    للربط لاحقًا باللجان/الاجتماعات/المهام/القرارات... بدون تعديل هذا
--    الـSchema عند بناء تلك الوحدات مستقبلًا" — الربط هنا هو بالضبط ذلك:
--    document_links.linked_entity_type = 'meeting' و linked_entity_id =
--    meetings.meeting_id. لا تكرار للغرض نفسه بجدول جديد.
-- 2) رئيس اللجنة الذي يدير الاجتماع هو committees.chair_user_id نفسه
--    (0013_committee_chair.sql) — لا يوجد عمود "منشئ الاجتماع" منفصل عن
--    اللجنة لأن BRS/SRS يحصران إنشاء/تعديل/حذف الاجتماع في "رئيس اللجنة"
--    حصرًا (رئاسة اللجنة، وليست رئاسة الاجتماع، هي مصدر الصلاحية) —
--    created_by مع ذلك يُخزَّن للتتبع فقط (من نفّذ الإنشاء فعليًا وقت
--    التسجيل)، وليس كمصدر تفويض إضافي.
-- 3) meeting_type نص حر (VARCHAR) وليس ENUM — BRS/SRS يذكران وجود "النوع"
--    كحقل مطلوب (BRS ص6: "كعنوانه ووصفه ونوعه") لكن لا يوردان أي قائمة
--    قيم محددة له في أي مكان بالوثيقتين. تقييده بـENUM الآن قيمًا لم
--    تُحدَّد صراحة من صاحبة المشروع اختراع غير موثَّق.
-- 4) عمود status يطابق حرفيًا التصنيف الوارد بـBRS (ص6، §3 إدارة
--    الاجتماعات): "عرض قائمة الاجتماعات (قادمة، جارية، منتهية، مسجلة)".
--    التحويل التلقائي بين هذه الحالات (بدء/انتهاء فعلي، أو توفر تسجيل)
--    يعتمد على حالة الاجتماع الفعلية داخل Teams — خارج نطاق هذا الـPhase
--    تمامًا (بند 1 أعلاه)؛ العمود موجود الآن بالقيمة الافتراضية
--    'upcoming' فقط حتى لا يحتاج الـSchema تعديلًا لاحقًا لمجرد إضافته.
-- 5) teams_meeting_id / teams_join_url: عمودان NULLABLE محجوزان صراحة
--    لمرحلة تكامل Teams القادمة (بناءً على طلب صاحبة المشروع صراحة إبقاء
--    مكان جاهز لهما الآن) — لا شيء يقرأهما أو يكتب فيهما في هذا الـPhase.
-- 6) لا جدول Status History منفصل — بنفس منطق committee_formation_requests
--    (0008)، أي تغيير حالة يُسجَّل لاحقًا بـaudit_logs (target_type =
--    'meeting') في طبقة الخدمة، وليس هنا.
-- =====================================================================

CREATE TYPE meeting_status AS ENUM (
    'upcoming',  -- قادمة
    'ongoing',   -- جارية
    'finished',  -- منتهية
    'recorded'   -- مسجلة
);

-- ============================== الاجتماع ==============================
CREATE TABLE meetings (
    meeting_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    committee_id    UUID NOT NULL REFERENCES committees(committee_id),
    title           VARCHAR(255) NOT NULL,
    description     TEXT,
    meeting_type    VARCHAR(100),                      -- نص حر — راجعي ملاحظة التصميم (3) أعلاه
    scheduled_at    TIMESTAMPTZ NOT NULL,               -- الموعد (FR-MEET-001)
    status          meeting_status NOT NULL DEFAULT 'upcoming',
    created_by      UUID NOT NULL REFERENCES users(user_id),  -- للتتبع فقط — راجعي ملاحظة (2)

    -- محجوزان لمرحلة تكامل Microsoft Teams القادمة — راجعي ملاحظة (5).
    teams_meeting_id VARCHAR(255),
    teams_join_url   TEXT,

    deleted_at      TIMESTAMPTZ,                        -- Soft Delete — اتساقًا مع committees/documents
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_meetings_committee_id  ON meetings (committee_id);
CREATE INDEX idx_meetings_scheduled_at  ON meetings (scheduled_at);
CREATE INDEX idx_meetings_status        ON meetings (status);

CREATE TRIGGER trg_meetings_set_updated_at
    BEFORE UPDATE ON meetings
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ============================== مشاركو الاجتماع ==============================
-- المشاركون = المدعوّون فعليًا للاجتماع (يُختارون عند الإنشاء من ضمن
-- أعضاء اللجنة عادةً — التحقق من ذلك مسؤولية طبقة الخدمة، وليس قيدًا هنا
-- بنفس نمط committee_members/committee_formation_request_members).
CREATE TABLE meeting_participants (
    meeting_id UUID NOT NULL REFERENCES meetings(meeting_id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES users(user_id),
    added_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (meeting_id, user_id)
);

CREATE INDEX idx_meeting_participants_user_id ON meeting_participants (user_id);

-- ============================== بنود جدول الأعمال ==============================
-- ترتيب العرض عبر sort_order بسيط (INT) بدل قائمة مرتبطة (Linked List)
-- — يكفي تمامًا لإعادة الترتيب بواجهة Drag & Drop مستقبلية (UPDATE بسيط
-- لعمود رقمي لكل بند)، بنفس النمط المستخدم بـpermissions.sort_order
-- (0006_roles_permissions.sql).
CREATE TABLE meeting_agenda_items (
    agenda_item_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id     UUID NOT NULL REFERENCES meetings(meeting_id) ON DELETE CASCADE,
    title          VARCHAR(255) NOT NULL,
    description    TEXT,
    sort_order     INT NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_meeting_agenda_items_meeting_id ON meeting_agenda_items (meeting_id);

CREATE TRIGGER trg_meeting_agenda_items_set_updated_at
    BEFORE UPDATE ON meeting_agenda_items
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ============================== Row Level Security ==============================
-- نفس النمط المطبَّق على بقية الجداول الجوهرية (committees/documents/...) —
-- الباك-إند المحلي يتصل مباشرة بقاعدة البيانات (ليس عبر Supabase API)،
-- فلا تأثير وظيفي محليًا؛ هذا فقط لإغلاق تنبيه "RLS Disabled" على مشروع
-- Supabase (لا توجد Policies بعد، بانتظار مراجعة سياسات الوصول الكاملة).
ALTER TABLE meetings              ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_participants  ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_agenda_items  ENABLE ROW LEVEL SECURITY;
