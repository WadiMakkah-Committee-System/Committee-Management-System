-- 0017_remove_committee_roles_category.sql
--
-- الهدف:
-- إزالة فئة الصلاحيات المصطنعة "committee_roles" (12 كود مجرّد أضافها
-- migration 0016) بناءً على طلب صريح من لاما (مراجعة 2026-09-01): أدوار
-- اللجان (رئيس اللجنة / عضو اللجنة) يجب أن تختار صلاحياتها من الفئات
-- الحقيقية الموجودة أصلًا في الكتالوج (اللجان، الاجتماعات، المهام،
-- القرارات، البنود المستخرجة من الذكاء الاصطناعي، الوثائق، المحاضر) —
-- وليس من فئة موازية مبسّطة/مجرّدة.
--
-- نص لاما (مترجم السياق، محفوظ للمرجعية): "ما أبغى قسم أدوار اللجان
-- يظهر، لأن الصلاحيات هنا مجردة تجريدية... أبغى يظهر لي قسم اللجان وقسم
-- الاجتماعات وقسم المهام وقسم القرارات وقسم البنود المستخرجة من الذكاء
-- الاصطناعي وقسم المحاضر... زي مثل حاط لي عرض الاجتماعات المشاركة في
-- الاجتماعات، طيب وين حذف الاجتماع، وين تعديل الاجتماع، وين الباقي؟"
--
-- أثر هذا التغيير على الإنفاذ بالباك-إند:
-- app/api/v1/committees.py::get_committee كان يتحقق من الكود
-- "committee.view" ضمن صلاحيات دور اللجنة (عبر
-- committee_service.get_committee_role_permission_codes) — أصبح يتحقق من
-- الكود الحقيقي "committees.view" (نفس الفئة committees، الموجود أصلًا،
-- ومُدرَج بالفعل ضمن ENFORCED_CATEGORIES بـschemas/role.py، فلا حاجة بعد
-- الآن لاستثناء ENFORCED_PERMISSION_CODES المنفصل — أُزيل أيضًا من الكود).
--
-- ملاحظة: عمودا permissions.kind وroles.kind/committee_role_slug (من
-- migration 0016) لا يُمسّان هنا — فصل "دور اللجنة" عن "الدور النظامي"
-- على مستوى roles يبقى صحيحًا تمامًا كما هو؛ فقط فئة الصلاحيات المصطنعة
-- هي ما يُحذف.

-- 1) حذف ارتباطات الأدوار بصلاحيات فئة committee_roles (احتياطًا؛
--    ON DELETE CASCADE على role_permissions.permission_id يكفي وحده،
--    لكن التصريح الصريح هنا أوضح وأأمن عند القراءة لاحقًا).
DELETE FROM role_permissions
WHERE permission_id IN (SELECT permission_id FROM permissions WHERE category = 'committee_roles');

-- 2) حذف صلاحيات فئة committee_roles الاثنتي عشرة نفسها.
DELETE FROM permissions WHERE category = 'committee_roles';

-- 3) ضمان بقاء الحد الأدنى الوظيفي: كلا دوري اللجنة (رئيس/عضو) يحتفظان
--    على الأقل بصلاحية "committees.view" الحقيقية حتى لا ينكسر وصولهم
--    لصفحة لجنتهم بعد حذف الفئة المصطنعة. أي صلاحيات إضافية (اجتماعات/
--    مهام/قرارات/بنود ذكاء اصطناعي/وثائق/محاضر) تُضاف يدويًا من شاشة
--    "الأدوار والصلاحيات" حسب ما تحدده لاما.
INSERT INTO role_permissions (role_id, permission_id, scope)
SELECT r.role_id, p.permission_id, 'own'
FROM roles r
CROSS JOIN permissions p
WHERE r.kind = 'committee' AND p.code = 'committees.view'
ON CONFLICT (role_id, permission_id) DO NOTHING;
