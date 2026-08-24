-- =====================================================================
-- 0009_committee_formation_enforcement.sql
-- الهدف: تفعيل الإنفاذ الفعلي (RBAC Enforcement) لوحدة "طلبات تشكيل
--        اللجان" — Phase 2 (Backend APIs + Business Logic + Workflow).
--        الجداول والكتالوج نفسه أُنشئا مسبقًا (0008 و0006) كـ"بيانات
--        تحضيرية فقط"، هذا الملف لا يضيف أي جدول أو عمود جديد — فقط:
--        1) ربط الصلاحيات الموجودة أصلًا بالكتالوج بالأدوار الفعلية،
--           حسب مصفوفة الصلاحيات المعتمدة (permissions.xlsx) حرفيًا.
--        2) توسعة enum سجل التدقيق (audit_action) بقيم جديدة تخص انتقالات
--           حالة طلب تشكيل اللجنة (submit/escalate/approve/reject) —
--           بدل إعادة استخدام "update" العام لعمليات لها دلالة عمل مختلفة
--           ومهمة للتتبع (من أرسل الطلب، من رفعه، من اعتمده أو رفضه).
--
-- ملاحظة مهمة (قرار عمل موثّق بعد نقاش مع المستخدمة): صلاحيات
-- committees.members.add / committees.members.remove / committees.update
-- تبقى موجودة بالكتالوج لكن **لا تُربط بأي دور هنا ولا يوجد لها أي
-- Endpoint في هذه المرحلة** — عضوية اللجنة وبياناتها مقفلة نهائيًا بعد
-- الاعتماد لكل الأدوار بدون استثناء (قرار يخالف صراحة SRS Use Case #5 وما
-- ورد بـpermissions.xlsx، والمستخدمة ستحدّث تلك الوثائق لتعكس هذا القرار).
-- =====================================================================

-- ============================== توسعة سجل التدقيق ==============================
ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'submit';
ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'escalate';
ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'approve';
ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'reject';

-- ============================== ربط الأدوار بصلاحيات طلبات تشكيل اللجان ==============================
-- حسب permissions.xlsx حرفيًا:
--   admin                       → طلب إنشاء اللجنة للمكتب التنفيذي، عرض اللجان المصرح بها لكل عضو
--   executive_office_manager /
--   executive_office_secretary  → عرض/تعديل/رفع طلب تشكيل اللجنة (كلها "المكتب التنفيذي")
--   executive_president         → موافقة أو رفض تشكيل اللجنة (حصريًا)
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id
FROM roles r
CROSS JOIN permissions p
WHERE (r.name = 'admin' AND p.code IN ('committees.request.create', 'committees.view_authorized'))
   OR (r.name IN ('executive_office_manager', 'executive_office_secretary')
       AND p.code IN ('committees.request.view', 'committees.request.update', 'committees.request.escalate'))
   OR (r.name = 'executive_president' AND p.code = 'committees.request.approve')
ON CONFLICT (role_id, permission_id) DO NOTHING;
