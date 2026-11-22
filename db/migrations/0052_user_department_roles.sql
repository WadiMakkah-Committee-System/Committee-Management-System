-- =====================================================================
-- 0052_user_department_roles.sql
-- الهدف: السماح للمستخدم الواحد بالانتماء لأكثر من إدارة، بدور مختلف في
-- كل إدارة (تعيينات "إدارة + دور").
--
-- المثال المعتمد (لاما 2026-11-22): معاذ = نائب الرئيس في "مكتب الرئيس
-- التنفيذي" (دور المكتب التنفيذي) + مدير "الإدارة القانونية" (أدمن) +
-- مدير "إدارة الخدمات المشتركة" (أدمن، ونطاقه يشمل إداراتها التابعة).
--
-- قواعد العمل:
-- 1) user_roles يبقى كما هو: "أي أدوار يحمل المستخدم" + الدور الحالي
--    (users.role_id) ومبدّل الأدوار بالشريط العلوي بلا تغيير.
-- 2) الجدول الجديد يحدد "هذا الدور على أي إدارات": صف لكل (مستخدم، إدارة،
--    دور). الدور المسند بلا أي صف هنا = دور بلا إدارة محددة، فيُحسب نطاقه
--    على الإدارة الأساسية (users.dep_id) — نفس السلوك قبل هذا الملف.
-- 3) نطاق "department" للدور الحالي = الإدارات اللي يحمل فيها هذا الدور
--    تحديدًا (وليس كل إداراته)، و"department_tree" = نفسها + إداراتها التابعة.
--    فمعاذ وهو "أدمن" لا يملك صلاحيات أدمن على مكتب الرئيس التنفيذي.
-- 4) users.dep_id يصير "الإدارة الأساسية": للعرض، ولنطاق الأدوار بلا إدارة.
-- 5) عضوية الإدارة (أعضاء الإدارة، رؤية وثائق الإدارة) = الإدارة الأساسية +
--    كل إدارات تعييناته، بغض النظر عن الدور الحالي.
--
-- التغييرات:
-- أ) جدول user_department_roles، مربوط بـuser_roles (user_id, role_id) مع
--    ON DELETE CASCADE: إزالة دور من المستخدم تزيل تعييناته تلقائيًا، ولا
--    يمكن تعيين دور على إدارة إلا لو كان الدور مسندًا للمستخدم أصلًا.
-- ب) فهارس للبحث بالإدارة (أعضاء الإدارة) وبالمستخدم.
-- ج) تعبئة رجعية: كل دور مسند حاليًا × الإدارة الحالية للمستخدم.
-- د) RLS (نفس نمط 0046).
--
-- أثر على البيانات القائمة: لا تغيير في صلاحيات أي مستخدم — كل دور مسند
-- يصير مربوطًا بنفس إدارته الحالية، فالنطاق المحسوب هو نفسه بالضبط.
-- يُطبَّق مع تحديث الباك-إند بنفس الفرع (feature/multi-department-users).
-- =====================================================================

BEGIN;

-- ============================ أ) الجدول ============================
CREATE TABLE IF NOT EXISTS user_department_roles (
    user_id     UUID NOT NULL,
    role_id     UUID NOT NULL,
    -- RESTRICT: حذف الإدارات Soft Delete فقط بالتطبيق؛ لا حذف فعلي يمسح التعيينات بصمت.
    dep_id      UUID NOT NULL REFERENCES departments(dep_id) ON DELETE RESTRICT,
    assigned_by UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_id, dep_id),
    CONSTRAINT user_department_roles_role_assigned_fkey
        FOREIGN KEY (user_id, role_id)
        REFERENCES user_roles (user_id, role_id)
        ON DELETE CASCADE
);

-- ============================ ب) الفهارس ============================
-- PK يغطي البحث بالمستخدم (user_id أولًا). هذا لأعضاء الإدارة وعدّادها.
CREATE INDEX IF NOT EXISTS idx_user_department_roles_dep_id ON user_department_roles (dep_id);

-- ============================ ج) التعبئة الرجعية ============================
INSERT INTO user_department_roles (user_id, role_id, dep_id)
SELECT ur.user_id, ur.role_id, u.dep_id
FROM user_roles ur
JOIN users u ON u.user_id = ur.user_id
WHERE u.dep_id IS NOT NULL
ON CONFLICT (user_id, role_id, dep_id) DO NOTHING;

COMMENT ON TABLE user_department_roles IS
    'تعيينات المستخدم (إدارة + دور). دور مسند بلا صفوف هنا = نطاقه على users.dep_id (الإدارة الأساسية).';
COMMENT ON COLUMN users.dep_id IS
    'الإدارة الأساسية للمستخدم (للعرض ولنطاق أدواره غير المربوطة بإدارة). بقية إداراته في user_department_roles.';

-- ============================ د) RLS ============================
ALTER TABLE user_department_roles ENABLE ROW LEVEL SECURITY;

COMMIT;
