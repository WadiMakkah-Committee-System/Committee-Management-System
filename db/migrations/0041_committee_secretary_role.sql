-- =====================================================================
-- 0041_committee_secretary_role.sql
-- الهدف: دور لجنة ثالث "أمين سر اللجنة" (طلب المدير، أوصلته لجين
-- 2026-11-08) — بنفس نمط رئيس/عضو اللجنة بالضبط (migration 0016):
-- committee_role_slug='secretary'، يُسنَد فقط عبر عضوية committee_members
-- حسب secretary_user_id بطلب التشكيل، وليس دورًا نظاميًا (kind='user').
--
-- ملاحظة تمييز: الدور النظامي الموجود مسبقًا "امين سر" (kind='user'،
-- role_id=09e05516...، يستخدمه حاليًا مهند الغامدي) شيء مختلف تمامًا —
-- ذاك منصب تنظيمي عام بالشركة، وهذا دور خاص بلجنة محددة فقط (قد يكون
-- أمين سر لجنة معينة شخصًا مختلفًا تمامًا عن صاحب المنصب العام، أو حتى
-- نفس الشخص). لا علاقة بينهما ولا يُعدَّل الدور النظامي القائم هنا.

-- 1) توسعة قيد committee_role_slug ليسمح بـ'secretary' جنب chair/member.
ALTER TABLE roles DROP CONSTRAINT roles_committee_slug_chk;
ALTER TABLE roles ADD CONSTRAINT roles_committee_slug_chk
    CHECK (committee_role_slug IS NULL OR committee_role_slug IN ('chair', 'member', 'secretary'));

-- 2) الدور الثابت نفسه — نفس نمط إدخال 0016 بالضبط.
INSERT INTO roles (name, description, is_system, is_super_admin, kind, committee_role_slug)
VALUES (
    'أمين سر اللجنة',
    'صلاحيات أمين سر اللجنة داخل اللجنة التي عُيّن فيها فقط — تُمنح تلقائيًا عند تحديده أمين سر بطلب تشكيل اللجنة.',
    true, false, 'committee', 'secretary'
);

-- 3) منح افتراضي عند الزرع — مطابق تمامًا لصلاحيات "عضو اللجنة" كنقطة
-- بداية معقولة (قابل للتعديل الكامل لاحقًا من واجهة "الأدوار والصلاحيات
-- → أدوار اللجان" بدون أي حاجة لتعديل كود، نفس مبدأ 0016).
INSERT INTO role_permissions (role_id, permission_id, scope)
SELECT r.role_id, p.permission_id, 'all'
FROM roles r
JOIN permissions p ON p.code IN (
    'committee.view', 'committee.members.view', 'committee.meetings.view',
    'committee.meetings.participate', 'committee.decisions.view',
    'committee.tasks.view_assigned', 'committee.tasks.update_assigned',
    'committee.documents.view'
)
WHERE r.committee_role_slug = 'secretary';

-- 4) عمود secretary_user_id على طلب التشكيل واللجنة المعتمدة — اختياري
-- (NULL جائز) بعكس chair_user_id الإلزامي منطقيًا، لأن أمين السر إضافة
-- اختيارية حسب طلب المدير ("وفي حاجة كمان")، وليست ركنًا أساسيًا للجنة
-- كالرئيس. نفس نمط chair_user_id تمامًا من ناحية الربط (FK إلى users،
-- ON DELETE لا داعي له صراحة هنا لأنه NULL-able وغير محدد بأي قيد حذف
-- خاص بعكس الأعمدة الأخرى — نفس سلوك chair_user_id الحالي تمامًا).
ALTER TABLE committee_formation_requests
    ADD COLUMN secretary_user_id UUID REFERENCES users(user_id);
ALTER TABLE committees
    ADD COLUMN secretary_user_id UUID REFERENCES users(user_id);
