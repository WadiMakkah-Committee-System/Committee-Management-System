-- =====================================================================
-- 0038_users_import_permission.sql
-- الهدف: صلاحية جديدة "رفع ملف المستخدمين" (users.import) — طلب لاما
-- 2026-11-01: إضافة مستخدمين دفعة واحدة من ملف Excel بنفس أعمدة نموذج
-- "نموذج_بيانات_المستخدمين.xlsx"، مع توليد اسم مستخدم وكلمة مرور مؤقتة
-- لكل واحد وإرسالها لبريده.
--
-- - نفس قسم "المستخدمون" (users) بشاشة "الأدوار والصلاحيات" بجانب
--   "إضافة مستخدم" (users.create) — تظهر كشيك بوكس مستقل.
-- - تُمنح لأي دور super_admin فقط (is_super_admin) بنطاق 'all' — لا يوجد
--   تجاوز تلقائي لـsuper_admin بفحص الصلاحيات (راجعي
--   core/dependencies.require_permission)، فلا بد من منحها صراحة هنا.
--   منحها لأي دور آخر يتم يدويًا من نفس الشاشة.
-- - لا جداول جديدة: الاستيراد يكتب في users/departments/audit_logs القائمة.
-- =====================================================================

INSERT INTO permissions (code, category, label_ar, sort_order, kind) VALUES
    ('users.import', 'users', 'رفع ملف المستخدمين', 10, 'system')
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id, scope)
SELECT r.role_id, p.permission_id, 'all'
FROM roles r
JOIN permissions p ON p.code = 'users.import'
WHERE r.is_super_admin = true
ON CONFLICT (role_id, permission_id) DO NOTHING;
