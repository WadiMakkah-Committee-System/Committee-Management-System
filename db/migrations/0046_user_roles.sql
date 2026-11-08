-- =====================================================================
-- 0046_user_roles.sql
-- الهدف: السماح للمستخدم الواحد بحمل أكثر من دور نظامي (مثال: نائب الرئيس
-- التنفيذي = "مكتب الرئيس التنفيذي" + "ادمن" للإدارة القانونية)، مع
-- "مبدّل دور" يختار به المستخدم الدور اللي يشتغل فيه حاليًا.
--
-- قواعد العمل المعتمدة (صاحب المشروع 2026-11-08):
-- 1) بعض المستخدمين دور واحد فقط، وبعضهم أكثر من دور — كلها تُسنَد من
--    شاشة المستخدمين بالمنصة (بدون أي تعديل يدوي بقاعدة البيانات).
-- 2) المستخدم متعدد الأدوار يبدّل دوره الحالي من الشريط العلوي، ويشوف
--    صلاحيات الدور الحالي فقط (هيكلة "مبدّل الأدوار" وليس العرض المدمج).
-- 3) الدور الحالي محفوظ على مستوى الحساب (وليس التبويب).
-- 4) أدوار اللجان (رئيس/عضو — roles.kind = 'committee') خارج هذا الجدول
--    تمامًا: تبقى تُسنَد فقط عبر committee_members لكل لجنة على حدة
--    (FR-UM-023، migration 0016).
--
-- التغييرات:
-- أ) جدول user_roles: الأدوار النظامية المسندة لكل مستخدم (many-to-many).
-- ب) users.role_id يبقى كما هو، لكن معناه يصير "الدور الحالي" (Active
--    Role). السبب (أداء): كل فحوصات الصلاحيات بالباك-إند تقرأ هذا العمود
--    أصلًا ضمن استعلام المصادقة الواحد بكل طلب — فبقاؤه هو نفسه يعني صفر
--    استعلامات إضافية بكل طلب.
-- ج) قيد مركّب (users.user_id, users.role_id) → user_roles: يضمن على مستوى
--    قاعدة البيانات (وليس الكود فقط) أن الدور الحالي دائمًا أحد أدوار
--    المستخدم المسندة — فلا يقدر أي خلل بالكود "يفعّل" دورًا غير مُسنَد.
--    DEFERRABLE INITIALLY DEFERRED: يُفحص عند COMMIT وليس عند كل جملة،
--    عشان إنشاء مستخدم (صف users ثم صفوف user_roles) وتبديل/إزالة الدور
--    الحالي داخل نفس المعاملة يشتغلون بدون مشكلة ترتيب.
--    role_id = NULL مسموح (مستخدم بلا دور — قرار migration 0014): القيد
--    المركّب لا يُفحص أصلًا لو أحد أعمدته NULL (MATCH SIMPLE الافتراضي).
-- د) Trigger يمنع إسناد دور من نوع 'committee' عبر user_roles.
-- هـ) تعبئة رجعية: كل مستخدم حالي يُنسخ دوره الحالي إلى user_roles.
-- و) تفعيل RLS على الجدول الجديد (نفس نمط 0045).
--
-- أثر على البيانات القائمة: لا تغيير على أي مستخدم — كل مستخدم يبقى بنفس
-- دوره وصلاحياته بالضبط (دوره الحالي يصير أول وأوحد دور مُسنَد له).
--
-- تنبيه تشغيل: هذا الملف يُطبَّق مع تحديث الباك-إند بنفس الفرع
-- (feature/multi-role-users) وليس قبله — كود إنشاء/تعديل المستخدم الحالي
-- يكتب users.role_id فقط بدون صف user_roles، فيرفضه القيد (ج) عند الحفظ.
-- =====================================================================

BEGIN;

-- ============================ 0) فحص مسبق ============================
-- لو فيه مستخدم دوره الحالي من نوع 'committee' (لا يُفترض وجوده — الواجهة
-- لا تعرض أدوار اللجان عند إسناد دور لمستخدم)، نوقف الهجرة برسالة واضحة
-- بدل ما نغيّر بياناته بصمت.
DO $$
DECLARE
    bad_count INT;
BEGIN
    SELECT count(*) INTO bad_count
    FROM users u
    JOIN roles r ON r.role_id = u.role_id
    WHERE r.kind <> 'user';

    IF bad_count > 0 THEN
        RAISE EXCEPTION
            '0046_user_roles: يوجد % مستخدم دوره الحالي دور لجنة (roles.kind <> ''user'') — صحّحوا أدوارهم ثم أعيدوا تطبيق الهجرة',
            bad_count;
    END IF;
END $$;

-- ============================ أ) جدول الأدوار المسندة ============================
-- بلا updated_at عمدًا: صف الربط لا يُعدَّل أبدًا (إما يُضاف أو يُحذف) —
-- نفس نمط committee_members (added_at فقط).
CREATE TABLE IF NOT EXISTS user_roles (
    user_id     UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    -- بلا ON DELETE: حذف دور مُسنَد لمستخدمين يُرفض — طبقة الخدمة
    -- (role_service.delete_role) تفحص وجود مستخدمين مسنَد لهم الدور قبل الحذف.
    role_id     UUID NOT NULL REFERENCES roles(role_id),
    -- من أسند الدور (للتتبع) — NULL للصفوف المنقولة بالتعبئة الرجعية أدناه.
    assigned_by UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_id)
);

-- المفتاح الأساسي يغطي البحث بالمستخدم (user_id أول عمود)؛ هذا الفهرس
-- للبحث بالدور: عدّاد مستخدمي كل دور، فحص حذف الدور، واستهداف الإشعارات
-- (كل المستخدمين اللي عندهم دور يملك صلاحية معيّنة).
CREATE INDEX IF NOT EXISTS idx_user_roles_role_id ON user_roles (role_id);

-- ============================ د) منع أدوار اللجان ============================
CREATE OR REPLACE FUNCTION user_roles_enforce_user_kind()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM roles WHERE role_id = NEW.role_id AND kind = 'user'
    ) THEN
        RAISE EXCEPTION 'user_roles: الدور % ليس دورًا نظاميًا (أدوار اللجان تُسنَد عبر committee_members فقط)', NEW.role_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_user_roles_enforce_user_kind ON user_roles;
CREATE TRIGGER trg_user_roles_enforce_user_kind
    BEFORE INSERT OR UPDATE OF role_id ON user_roles
    FOR EACH ROW
    EXECUTE FUNCTION user_roles_enforce_user_kind();

-- ============================ هـ) التعبئة الرجعية ============================
-- يشمل المستخدمين المحذوفين حذفًا ناعمًا (deleted_at) أيضًا — القيد (ج)
-- يُطبَّق على كل صفوف users بلا استثناء.
INSERT INTO user_roles (user_id, role_id)
SELECT u.user_id, u.role_id
FROM users u
WHERE u.role_id IS NOT NULL
ON CONFLICT (user_id, role_id) DO NOTHING;

-- ============================ ج) الدور الحالي من الأدوار المسندة ============================
ALTER TABLE users
    ADD CONSTRAINT users_active_role_assigned_fkey
    FOREIGN KEY (user_id, role_id)
    REFERENCES user_roles (user_id, role_id)
    DEFERRABLE INITIALLY DEFERRED;

COMMENT ON COLUMN users.role_id IS
    'الدور الحالي (Active Role) — يجب أن يكون أحد أدوار المستخدم في user_roles (users_active_role_assigned_fkey). NULL = مستخدم بلا دور.';
COMMENT ON TABLE user_roles IS
    'الأدوار النظامية المسندة لكل مستخدم (many-to-many). أدوار اللجان خارج هذا الجدول (committee_members).';

-- ============================ و) RLS ============================
-- الباك-إند يتصل بصلاحية مالك الجداول فلا يتأثر؛ واجهة Supabase العامة (anon) تُمنع.
ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;

COMMIT;
