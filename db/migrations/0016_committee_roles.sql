-- =====================================================================
-- 0016_committee_roles.sql
-- الهدف: "أدوار اللجان" (Committee Roles: رئيس اللجنة/عضو اللجنة) —
-- بلاغ لاما 2026-08-31. تعيد نفس الحاجة اللي أُلغيت بـmigration 0013
-- (2026-08-27) لكن بتصميم مختلف جوهريًا هذي المرة: هناك كانت "رئيس
-- لجنة"/"عضو لجنة" دورًا عامًا بلا نطاق فعلي (فأُلغيت)؛ هنا صلاحيات
-- Committee Role مرتبطة فعليًا بعضوية المستخدم داخل لجنة محددة، وتُنفَّذ
-- بالـBackend فعليًا (راجعي app/services/committee_service.py::
-- get_committee_role_permission_codes وapp/api/v1/committees.py::
-- get_committee بعد هذا الملف).
--
-- ============================ 1) kind على roles/permissions ============================
-- تمييز الأدوار/الصلاحيات "النظامية" (تُسنَد كـuser.role_id، تُدار من
-- تبويب "الأدوار والصلاحيات" الحالي) عن "أدوار اللجان" (تُسنَد فقط عبر
-- عضوية committee_members، ولا تظهر أبدًا بقائمة الأدوار عند إنشاء
-- مستخدم — قرار صريح من لاما). عمود بسيط (VARCHAR + CHECK) بنفس نمط
-- scope بـmigration 0014، وليس ENUM حقيقي، لنفس السبب (تعديل مستقبلي
-- بأمر ALTER بسيط بدل قفل كامل).
ALTER TABLE roles
    ADD COLUMN kind VARCHAR(20) NOT NULL DEFAULT 'user';
ALTER TABLE roles
    ADD CONSTRAINT roles_kind_chk CHECK (kind IN ('user', 'committee'));

-- معرّف ثابت (غير قابل للتعديل من الواجهة، بخلاف name القابل للتعديل
-- كبقية الأدوار) يميّز "رئيس اللجنة" عن "عضو اللجنة" بشكل موثوق —
-- بدل الاعتماد على الاسم النصي (قابل للتعديل) أو ترتيب الإنشاء.
ALTER TABLE roles
    ADD COLUMN committee_role_slug VARCHAR(20) NULL;
ALTER TABLE roles
    ADD CONSTRAINT roles_committee_slug_chk
    CHECK (committee_role_slug IS NULL OR committee_role_slug IN ('chair', 'member'));
CREATE UNIQUE INDEX uq_roles_committee_slug ON roles (committee_role_slug)
    WHERE committee_role_slug IS NOT NULL;

ALTER TABLE permissions
    ADD COLUMN kind VARCHAR(20) NOT NULL DEFAULT 'system';
ALTER TABLE permissions
    ADD CONSTRAINT permissions_kind_chk CHECK (kind IN ('system', 'committee'));

-- ============================ 2) الدورين الثابتين ============================
-- is_system = true عمدًا: هذا العمود لم يعد يمنح أي حماية فعلية بطبقة
-- الخدمة (قرار موثّق سابق — راجعي app/models/role.py) لكنه لا يزال يُستخدم
-- بـtests/conftest.py لاستثناء الأدوار من التفريغ (TRUNCATE) بين
-- الاختبارات؛ لازم يبقى true حتى لا يُحذف هذان الدوران الثابتان بالخطأ.
-- الحماية الفعلية الوحيدة (منع الحذف من الواجهة) تُفرض بطبقة الخدمة
-- (role_service.delete_role) بالاعتماد على kind='committee'، وليس على
-- is_system.
INSERT INTO roles (name, description, is_system, is_super_admin, kind, committee_role_slug)
VALUES
    ('رئيس اللجنة', 'صلاحيات رئيس اللجنة داخل اللجنة التي يرأسها فقط — تُمنح تلقائيًا عند تحديده رئيسًا بطلب تشكيل اللجنة.', true, false, 'committee', 'chair'),
    ('عضو اللجنة', 'صلاحيات عضو اللجنة داخل اللجنة التي هو عضو فيها فقط.', true, false, 'committee', 'member');

-- ============================ 3) كتالوج صلاحيات اللجان ============================
-- قسم واحد جديد "أدوار اللجان" (category = committee_roles) — عمدًا
-- منفصل عن قسم "اللجان" الحالي (committees) لأن ذاك يخص صلاحيات النظام
-- العامة (own/department/all)، بينما هذا خاص فقط بمن هو عضو باللجنة
-- المحددة. is_enforced (schemas/role.py) تُحسب من العضوية بـ
-- ENFORCED_CATEGORIES بالكود، فلا حاجة لعمود إضافي هنا.
INSERT INTO permissions (code, category, label_ar, sort_order, kind) VALUES
    ('committee.view', 'committee_roles', 'عرض بيانات اللجنة', 1, 'committee'),
    ('committee.members.view', 'committee_roles', 'عرض أعضاء اللجنة', 2, 'committee'),
    ('committee.meetings.view', 'committee_roles', 'عرض الاجتماعات', 3, 'committee'),
    ('committee.meetings.manage', 'committee_roles', 'إدارة الاجتماعات', 4, 'committee'),
    ('committee.meetings.participate', 'committee_roles', 'المشاركة في الاجتماعات', 5, 'committee'),
    ('committee.agenda.manage', 'committee_roles', 'إدارة جدول الأعمال', 6, 'committee'),
    ('committee.tasks.manage', 'committee_roles', 'إدارة المهام', 7, 'committee'),
    ('committee.tasks.view_assigned', 'committee_roles', 'عرض المهام المسندة إليه', 8, 'committee'),
    ('committee.tasks.update_assigned', 'committee_roles', 'تحديث حالة المهام المسندة إليه', 9, 'committee'),
    ('committee.decisions.view', 'committee_roles', 'عرض القرارات', 10, 'committee'),
    ('committee.decisions.manage', 'committee_roles', 'إدارة القرارات', 11, 'committee'),
    ('committee.documents.view', 'committee_roles', 'عرض وثائق اللجنة', 12, 'committee');

-- منح افتراضي عند الزرع (أمثلة لاما 2026-08-31 بالضبط) — قابل للتعديل
-- الكامل لاحقًا من واجهة "الأدوار والصلاحيات → أدوار اللجان"، وليس ثابتًا
-- بالكود (هذا فقط منح ابتدائي، وليس فرضًا دائمًا). scope='all' ثابت لكل
-- صلاحيات اللجان — عمود scope بـrole_permissions لا معنى فعليًا له هنا
-- (النطاق الحقيقي هو "هل أنت عضو بهذه اللجنة تحديدًا"، محسوب من عضوية
-- committee_members وليس من هذا العمود).
INSERT INTO role_permissions (role_id, permission_id, scope)
SELECT r.role_id, p.permission_id, 'all'
FROM roles r
JOIN permissions p ON p.code IN (
    'committee.view', 'committee.members.view', 'committee.meetings.manage',
    'committee.agenda.manage', 'committee.tasks.manage', 'committee.decisions.view',
    'committee.decisions.manage', 'committee.documents.view'
)
WHERE r.committee_role_slug = 'chair';

INSERT INTO role_permissions (role_id, permission_id, scope)
SELECT r.role_id, p.permission_id, 'all'
FROM roles r
JOIN permissions p ON p.code IN (
    'committee.view', 'committee.members.view', 'committee.meetings.view',
    'committee.meetings.participate', 'committee.decisions.view',
    'committee.tasks.view_assigned', 'committee.tasks.update_assigned',
    'committee.documents.view'
)
WHERE r.committee_role_slug = 'member';

-- ============================ 4) الدور الفعلي لكل عضو لجنة ============================
-- committee_members كان جدول ربط بسيط (لا يحمل أي صفة لكل عضو) — يتحوّل
-- الآن إلى Association Object حقيقي (نفس نمط RolePermission بـmigration
-- 0014، ونفس السبب بالضبط: عمود إضافي لكل صف لا يمكن التعبير عنه بجدول
-- secondary= بسيط). راجعي app/models/committee.py::CommitteeMember.
ALTER TABLE committee_members
    ADD COLUMN committee_role_id UUID REFERENCES roles(role_id);

-- تعبئة رجعية (Backfill): كل عضو حاليًا يحمل committee_role_id حسب هل
-- هو رئيس اللجنة (committees.chair_user_id) أو عضو عادي — وإلا لن يقدر
-- أي عضو حالي بأي لجنة معتمدة سابقًا يستخدم أي صلاحية Committee Role.
UPDATE committee_members cm
SET committee_role_id = (
    CASE
        WHEN cm.user_id = c.chair_user_id
            THEN (SELECT role_id FROM roles WHERE committee_role_slug = 'chair')
        ELSE (SELECT role_id FROM roles WHERE committee_role_slug = 'member')
    END
)
FROM committees c
WHERE c.committee_id = cm.committee_id;

ALTER TABLE committee_members
    ALTER COLUMN committee_role_id SET NOT NULL;
