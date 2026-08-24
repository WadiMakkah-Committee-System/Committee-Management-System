-- =====================================================================
-- 0008_committee_formation.sql
-- الهدف: Phase 1 من وحدة "إدارة اللجان" — طلب تشكيل اللجنة (دورة حياة
--        كاملة من المسودة حتى الاعتماد/الرفض)، واللجنة المعتمدة الناتجة
--        عنه، مع الفصل بين "الأعضاء المقترحون بالطلب" و"أعضاء اللجنة
--        المعتمدة" (منفصلان بقصد — عضوية اللجنة تُقفل نهائيًا عند
--        الاعتماد ولا تُعدَّل من خلال هذه الوحدة بعد ذلك).
--
-- ملاحظات تصميم مهمة:
-- 1) لا يوجد أي جدول/عمود صلاحيات جديد هنا — الوحدة تعتمد بالكامل على
--    كتالوج الصلاحيات الموجود مسبقًا (permissions/roles/role_permissions
--    من 0006_roles_permissions.sql)، والذي يحتوي أصلًا على كل أكواد
--    الصلاحيات اللازمة لهذه الوحدة (committees.request.create/view/
--    update/escalate/approve، committees.members.add/remove،
--    committees.update، committees.view_authorized) — راجع تعليق
--    0006 نفسه: "الإنفاذ الفعلي مفعّل حاليًا لقسمي الإدارات والمستخدمين
--    فقط... اللجان... موجودة كبيانات كتالوج فقط تحضيرًا للمراحل القادمة"
--    — هذه هي تلك المرحلة القادمة، وتُنفَّذ في Phase 2 (Backend APIs)
--    عبر require_permission(...) الموجودة، دون أي تعديل على نظام
--    الأدوار والصلاحيات نفسه.
-- 2) سجل تغييرات الحالة (Status History) لا يحصل على جدول مستقل —
--    جدول audit_logs (0004) صُمم أصلًا ليكون عامًا لأي كيان مستقبلي
--    ("لجان، اجتماعات، قرارات..." — تعليق حرفي بذلك الملف)، فتُسجَّل
--    كل عملية إرسال/إعادة/رفع/اعتماد/رفض هناك (target_type =
--    'committee_formation_request') بدل تكرار نفس البنية بجدول جديد.
-- 3) الإشعارات داخل النظام (المطلوبة عند الاعتماد/الرفض) خارج نطاق
--    هذا الـPhase — لا يوجد جدول notifications عام في المشروع بعد
--    (شاشة "الإشعارات" لسا "قريبًا")، وليست من ضمن الكيانات المطلوب
--    فصلها في هذه الوحدة تحديدًا. تُحل عند بناء تلك الوحدة أو عند
--    الحاجة الفعلية في Phase 2/3.
-- =====================================================================

-- ============================== حالة طلب التشكيل ==============================
CREATE TYPE committee_request_status AS ENUM (
    'draft',            -- مسودة
    'submitted',        -- تم الإرسال
    'under_review',     -- قيد المراجعة
    'returned',         -- معاد للتعديل
    'pending_approval', -- بانتظار الاعتماد
    'approved',         -- تمت الموافقة (نهائية)
    'rejected'          -- تم الرفض (نهائية)
);

-- ============================== طلب تشكيل اللجنة ==============================
CREATE TABLE committee_formation_requests (
    request_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    committee_name    VARCHAR(200) NOT NULL,
    statement         TEXT,                                   -- بيان اللجنة
    start_date        DATE NOT NULL,
    end_date          DATE NOT NULL,
    status            committee_request_status NOT NULL DEFAULT 'draft',
    requested_by      UUID NOT NULL REFERENCES users(user_id), -- مقدّم الطلب
    return_reason     TEXT,                                   -- آخر سبب إعادة (السجل الكامل في audit_logs)
    rejection_reason  TEXT,                                   -- سبب الرفض النهائي
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_committee_formation_requests_dates CHECK (end_date > start_date)
);

CREATE INDEX idx_committee_formation_requests_status       ON committee_formation_requests (status);
CREATE INDEX idx_committee_formation_requests_requested_by ON committee_formation_requests (requested_by);

CREATE TRIGGER trg_committee_formation_requests_set_updated_at
    BEFORE UPDATE ON committee_formation_requests
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ============================== الأعضاء المقترحون بالطلب ==============================
-- قابلون للتعديل (إضافة/حذف) فقط أثناء حالة draft أو returned — تُفرض هذه
-- القاعدة في طبقة الخدمة (Service) بـ Phase 2، وليست هنا.
CREATE TABLE committee_formation_request_members (
    request_id UUID NOT NULL REFERENCES committee_formation_requests(request_id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES users(user_id),
    added_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (request_id, user_id)
);

CREATE INDEX idx_committee_formation_request_members_user_id ON committee_formation_request_members (user_id);

-- ============================== اللجنة المعتمدة ==============================
CREATE TABLE committees (
    committee_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              VARCHAR(200) NOT NULL,
    statement         TEXT,
    start_date        DATE NOT NULL,
    end_date          DATE NOT NULL,
    source_request_id UUID NOT NULL UNIQUE REFERENCES committee_formation_requests(request_id),
    deleted_at        TIMESTAMPTZ,                            -- Soft Delete (اتساقًا مع بقية الكيانات الجوهرية)
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_committees_dates CHECK (end_date > start_date)
);

CREATE TRIGGER trg_committees_set_updated_at
    BEFORE UPDATE ON committees
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ============================== أعضاء اللجنة المعتمدة ==============================
-- نسخة مقفلة عند لحظة الاعتماد (تُنشأ مرة واحدة من الأعضاء المقترحين بالطلب
-- عند الموافقة) — لا تُعدَّل بعد ذلك عبر هذه الوحدة (اتُّفق على أن عضوية
-- اللجنة المعتمدة نهائية ولا تُدار بعد الاعتماد، خلافًا لعضوية الإدارة).
CREATE TABLE committee_members (
    committee_id UUID NOT NULL REFERENCES committees(committee_id) ON DELETE CASCADE,
    user_id      UUID NOT NULL REFERENCES users(user_id),
    added_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (committee_id, user_id)
);

CREATE INDEX idx_committee_members_user_id ON committee_members (user_id);

-- ============================== Row Level Security ==============================
-- نفس النمط المطبَّق على بقية الجداول (departments/users/roles/permissions/
-- role_permissions/audit_logs) — الباك-إند المحلي يتصل مباشرة بقاعدة
-- البيانات (ليس عبر Supabase API)، فلا تأثير وظيفي محليًا؛ هذا فقط
-- لإغلاق تنبيه "RLS Disabled" على مشروع Supabase (لا توجد Policies بعد،
-- بانتظار مراجعة سياسات الوصول الكاملة لاحقًا).
ALTER TABLE committee_formation_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE committee_formation_request_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE committees ENABLE ROW LEVEL SECURITY;
ALTER TABLE committee_members ENABLE ROW LEVEL SECURITY;
