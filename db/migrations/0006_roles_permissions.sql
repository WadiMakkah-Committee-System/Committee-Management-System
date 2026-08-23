-- =====================================================================
-- 0006_roles_permissions.sql
-- الهدف: نظام أدوار وصلاحيات ديناميكي بالكامل (Roles & Permissions)
--        يسمح لـ super_admin بإنشاء أدوار جديدة وتحديد صلاحياتها من
--        الواجهة مباشرة، دون أي تعديل على الكود أو قاعدة البيانات.
--
-- ملاحظة مهمة: كتالوج الصلاحيات هنا يغطي كل الأقسام الموثّقة (9 أقسام)،
-- لكن الإنفاذ الفعلي (Enforcement) في الـ API حاليًا مفعّل فقط لقسمي
-- "الإدارات" و"المستخدمين" — بقية الأقسام (اللجان، الاجتماعات، المهام،
-- القرارات، البنود المستخرجة، الوثائق، المحاضر) موجودة كبيانات كتالوج
-- فقط تحضيرًا للمراحل القادمة، ولا يوجد أي endpoint يتحقق منها بعد.
-- =====================================================================

CREATE TABLE permissions (
    permission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code          VARCHAR(100) NOT NULL,
    category      VARCHAR(50)  NOT NULL,
    label_ar      VARCHAR(200) NOT NULL,
    sort_order    INT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_permissions_code ON permissions (code);
CREATE INDEX idx_permissions_category ON permissions (category);

CREATE TABLE roles (
    role_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name           VARCHAR(100) NOT NULL,
    description    TEXT,
    is_system      BOOLEAN NOT NULL DEFAULT false,  -- أدوار جاهزة لا يمكن حذفها
    is_super_admin BOOLEAN NOT NULL DEFAULT false,  -- الدور الجذري المحمي من الحذف/الإيقاف الكامل
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_roles_name ON roles (lower(name));
CREATE TRIGGER trg_roles_set_updated_at
    BEFORE UPDATE ON roles
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

CREATE TABLE role_permissions (
    role_id       UUID NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(permission_id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

-- ============================== كتالوج الصلاحيات ==============================
INSERT INTO permissions (code, category, label_ar, sort_order) VALUES
    ('departments.create', 'departments', 'إضافة إدارة', 1),
    ('departments.view', 'departments', 'عرض إدارة', 2),
    ('departments.update', 'departments', 'تعديل إدارة', 3),
    ('departments.delete', 'departments', 'حذف إدارة', 4),
    ('departments.members.view', 'departments', 'عرض أعضاء إدارة', 5),
    ('departments.members.remove', 'departments', 'حذف أعضاء إدارة', 6),
    ('departments.members.add', 'departments', 'إضافة أعضاء الإدارة', 7),
    ('departments.members.update', 'departments', 'تعديل أعضاء إدارة', 8),
    ('users.suspend', 'users', 'إيقاف مؤقت للحساب', 9),
    ('users.create', 'users', 'إضافة مستخدم', 10),
    ('users.update', 'users', 'تعديل مستخدم', 11),
    ('users.delete', 'users', 'حذف مستخدم', 12),
    ('users.reactivate', 'users', 'تفعيل الحساب', 13),
    ('users.view', 'users', 'عرض بيانات المستخدم', 14),
    ('users.login', 'users', 'تسجيل الدخول', 15),
    ('users.logout', 'users', 'تسجيل الخروج', 16),
    ('committees.members.add', 'committees', 'إضافة عضو داخل اللجنة', 17),
    ('committees.members.remove', 'committees', 'حذف عضو داخل اللجنة', 18),
    ('committees.update', 'committees', 'تعديل بيانات اللجنة', 19),
    ('committees.request.create', 'committees', 'طلب إنشاء اللجنة للمكتب التنفيذي', 20),
    ('committees.request.view', 'committees', 'عرض طلب تشكيل اللجنة', 21),
    ('committees.request.update', 'committees', 'تعديل طلب تشكيل اللجنة', 22),
    ('committees.request.escalate', 'committees', 'رفع طلب إنشاء اللجنة للرئيس التنفيذي', 23),
    ('committees.request.approve', 'committees', 'موافقة أو رفض تشكيل اللجنة', 24),
    ('committees.view_authorized', 'committees', 'عرض اللجان المصرح بها لكل عضو', 25),
    ('meetings.schedule', 'meetings', 'جدولة اجتماع', 26),
    ('meetings.update', 'meetings', 'تعديل بيانات الاجتماع', 27),
    ('meetings.delete', 'meetings', 'حذف الاجتماع', 28),
    ('meetings.view', 'meetings', 'عرض الاجتماع', 29),
    ('meetings.view_details', 'meetings', 'عرض تفاصيل الاجتماع', 30),
    ('meetings.agenda.create', 'meetings', 'إنشاء جدول أعمال', 31),
    ('meetings.agenda.view', 'meetings', 'عرض جدول أعمال', 32),
    ('meetings.agenda.item.delete', 'meetings', 'حذف بند جدول أعمال', 33),
    ('meetings.agenda.item.add', 'meetings', 'إضافة بند بجدول الأعمال', 34),
    ('meetings.agenda.item.update', 'meetings', 'تعديل بند جدول الأعمال', 35),
    ('meetings.attachments.add', 'meetings', 'إضافة مرفقات للاجتماع', 36),
    ('meetings.attachments.view', 'meetings', 'عرض المرفقات', 37),
    ('meetings.attachments.delete', 'meetings', 'حذف المرفقات', 38),
    ('meetings.record_audio', 'meetings', 'تسجيل الاجتماع صوتيًا', 39),
    ('meetings.draft.summarize', 'meetings', 'تحويل المسودة إلى ملخص', 40),
    ('meetings.draft.view', 'meetings', 'عرض المسودة', 41),
    ('meetings.summary.view', 'meetings', 'عرض ملخص المسودة', 42),
    ('tasks.create', 'tasks', 'إنشاء مهمة', 43),
    ('tasks.status.update', 'tasks', 'تحديث حالة المهمة', 44),
    ('tasks.view_all', 'tasks', 'عرض جميع المهام', 45),
    ('tasks.view_details', 'tasks', 'عرض تفاصيل المهام', 46),
    ('tasks.update', 'tasks', 'تعديل المهمة', 47),
    ('tasks.delete', 'tasks', 'حذف المهمة', 48),
    ('decisions.view', 'decisions', 'عرض قرار', 49),
    ('decisions.create', 'decisions', 'إنشاء قرار', 50),
    ('decisions.update', 'decisions', 'تعديل قرار', 51),
    ('decisions.vote.open', 'decisions', 'طرح قرار للتصويت', 52),
    ('decisions.delete', 'decisions', 'حذف قرار', 53),
    ('decisions.vote.cast', 'decisions', 'التصويت على القرار', 54),
    ('decisions.vote.view_result', 'decisions', 'عرض نتيجة التصويت', 55),
    ('decisions.approve', 'decisions', 'اعتماد القرار', 56),
    ('ai_items.extract', 'ai_items', 'استخراج قائمة بنود من ملخص الذكاء الاصطناعي', 57),
    ('ai_items.view', 'ai_items', 'عرض قائمة البنود', 58),
    ('ai_items.assign', 'ai_items', 'تعيين بند', 59),
    ('ai_items.delete', 'ai_items', 'حذف بند', 60),
    ('ai_items.update', 'ai_items', 'تعديل بند', 61),
    ('ai_items.add', 'ai_items', 'إضافة بند', 62),
    ('documents.upload', 'documents', 'رفع وثيقة', 63),
    ('documents.export', 'documents', 'تصدير وثيقة', 64),
    ('documents.search', 'documents', 'بحث عن وثيقة', 65),
    ('documents.view', 'documents', 'عرض الوثيقة', 66),
    ('documents.search_content', 'documents', 'بحث داخل محتوى الوثيقة', 67),
    ('documents.search_all_agent', 'documents', 'بحث داخل جميع الوثائق (إيجينت)', 68),
    ('minutes.templates.view', 'minutes', 'عرض قوالب محاضر', 69),
    ('minutes.templates.select', 'minutes', 'اختيار قالب للمحضر', 70),
    ('minutes.view', 'minutes', 'عرض المحضر', 71),
    ('minutes.update', 'minutes', 'تعديل محتوى المحضر', 72),
    ('minutes.approve', 'minutes', 'اعتماد المحضر', 73),
    ('minutes.sign', 'minutes', 'توقيع المحضر', 74),
    ('minutes.export', 'minutes', 'تصدير الملف', 75);

-- ============================== الأدوار الأساسية (نظامية) ==============================
-- هذه الأدوار الخمسة كانت مضمَّنة سابقًا كـ Enum ثابت في العمود role — الآن أصبحت
-- صفوفًا عادية في جدول roles، قابلة للتعديل (الوصف/الصلاحيات) لكن لا يمكن حذفها
-- أو تغيير اسمها (is_system = true) حفاظًا على استقرار النظام.
INSERT INTO roles (name, description, is_system, is_super_admin) VALUES
    ('super_admin', 'المسؤول الأعلى — صلاحية كاملة على كل أجزاء النظام', true, true),
    ('admin', 'مسؤول إدارة', true, false),
    ('executive_president', 'الرئيس التنفيذي', true, false),
    ('executive_office_manager', 'مدير المكتب التنفيذي', true, false),
    ('executive_office_secretary', 'سكرتير المكتب التنفيذي', true, false);

-- super_admin يحصل على كل الصلاحيات في الكتالوج (كل الأقسام) تلقائيًا
INSERT INTO role_permissions (role_id, permission_id)
SELECT (SELECT role_id FROM roles WHERE name = 'super_admin'), permission_id FROM permissions;

-- ============================== ربط المستخدمين بالأدوار الجديدة ==============================
ALTER TABLE users ADD COLUMN role_id UUID REFERENCES roles(role_id);

UPDATE users u SET role_id = r.role_id FROM roles r WHERE r.name = u.role::text;

ALTER TABLE users ALTER COLUMN role_id SET NOT NULL;
CREATE INDEX idx_users_role_id ON users (role_id);

-- التخلص من عمود/نوع الدور الثابت القديم بعد نقل كل البيانات بنجاح
ALTER TABLE users DROP COLUMN role;
DROP TYPE user_role;

