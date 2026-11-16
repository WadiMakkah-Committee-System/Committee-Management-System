-- =====================================================================
-- 0050_permissions_split_and_permanent_committees.sql
-- طلب لاما 2026-11-16:
--
-- (1) وظائف موجودة بالنظام بلا شيك بوكس مستقل بشاشة "الأدوار والصلاحيات"
--     (كانت تتبع صلاحية أخرى ضمنيًا — مثال: تمديد الاجتماع كان يتبع
--     "تعديل بيانات الاجتماع"). كل وظيفة صار لها كود مستقل.
--
--     ⚠️ لا يتغيّر سلوك أي دور حالي: كل كود جديد يُمنح تلقائيًا لكل دور
--     (نظامي أو دور لجنة) يملك الكود اللي كانت الوظيفة تتبعه، بنفس النطاق.
--     بعدها تقدر لاما تفصلها من الشاشة لكل دور على حدة.
--
--       الكود الجديد               كانت تتبع
--       meetings.extend             meetings.update
--       meetings.guests.manage      meetings.join (مشاركة الرابط وقاعة الانتظار والقبول/الرفض؛
--                                   تجديد الرابط يبقى بـmeetings.update)
--       meetings.attendance.view    meetings.view
--       minutes.review              minutes.approve
--       minutes.return              minutes.approve
--       minutes.send_signature      minutes.approve
--       minutes.export (موجود)      minutes.view  (تنزيل PDF المحضر — كان بلا أثر)
--       tasks.reassign              tasks.update
--       tasks.attachments.manage    tasks.status.update
--       decisions.attachments.add   decisions.create
--       committees.extend           committees.update
--
-- (2) اللجان الدائمة:
--     - صار لها تاريخ بداية ونهاية مثل المؤقتة (قرار لاما — وتُمدَّد من
--       داخل اللجنة). اللجان الدائمة القائمة بلا تواريخ تبقى صالحة كما هي
--       (القيد يقبل الحالتين للدائمة)، والطلبات الجديدة تُلزَم بالتواريخ
--       بطبقة الخدمة.
--     - تعديل الأعضاء بعد الاعتماد (إضافة/حذف/تغيير الرئيس أو الأمين) —
--       للدائمة فقط، بصلاحيات:
--         committees.members.add / committees.members.remove (موجودتان أصلًا
--         بالكتالوج بلا أثر — صار لهما أثر الآن)
--         committees.members.roles (جديد: تغيير رئيس أو أمين اللجنة)
--       الثلاث تُمنح افتراضيًا لمن يملك committees.update (المكتب التنفيذي
--       اللي يدير اللجان أصلًا)، وتنعدّل من شاشة الأدوار.
--     - جدول committee_changes: سجل دائم لكل تغيير على عضوية اللجنة
--       الدائمة أو فترتها (من، متى، وش تغيّر).
-- =====================================================================

BEGIN;

-- ============================ (1) الصلاحيات الجديدة ============================
INSERT INTO permissions (code, category, label_ar, sort_order, kind) VALUES
    ('meetings.extend', 'meetings', 'تمديد الاجتماع', 91, 'system'),
    ('meetings.guests.manage', 'meetings', 'إدارة ضيوف الاجتماع (رابط الدعوة والقبول والرفض)', 92, 'system'),
    ('meetings.attendance.view', 'meetings', 'عرض سجل حضور الاجتماع', 93, 'system'),
    ('minutes.review', 'minutes', 'مراجعة المحضر وإبداء الرأي', 76, 'system'),
    ('minutes.return', 'minutes', 'إرجاع المحضر للتعديل', 77, 'system'),
    ('minutes.send_signature', 'minutes', 'إرسال المحضر للتوقيع', 78, 'system'),
    ('tasks.reassign', 'tasks', 'إعادة إسناد المهمة', 101, 'system'),
    ('tasks.attachments.manage', 'tasks', 'إرفاق وحذف مرفقات المهمة', 102, 'system'),
    ('decisions.attachments.add', 'decisions', 'إرفاق ملفات بالقرار', 103, 'system'),
    ('committees.extend', 'committees', 'تمديد مدة اللجنة', 104, 'system'),
    ('committees.members.roles', 'committees', 'تغيير رئيس أو أمين اللجنة', 105, 'system')
ON CONFLICT (code) DO NOTHING;

UPDATE permissions SET label_ar = 'تنزيل المحضر PDF' WHERE code = 'minutes.export';

-- منح كل كود جديد لكل دور يملك الكود المصدر، بنفس النطاق — يحفظ السلوك الحالي.
INSERT INTO role_permissions (role_id, permission_id, scope)
SELECT rp.role_id, new_p.permission_id, rp.scope
FROM (VALUES
        ('meetings.extend', 'meetings.update'),
        ('meetings.guests.manage', 'meetings.join'),
        ('meetings.attendance.view', 'meetings.view'),
        ('minutes.review', 'minutes.approve'),
        ('minutes.return', 'minutes.approve'),
        ('minutes.send_signature', 'minutes.approve'),
        ('minutes.export', 'minutes.view'),
        ('tasks.reassign', 'tasks.update'),
        ('tasks.attachments.manage', 'tasks.status.update'),
        ('decisions.attachments.add', 'decisions.create'),
        ('committees.extend', 'committees.update'),
        ('committees.members.roles', 'committees.update'),
        ('committees.members.add', 'committees.update'),
        ('committees.members.remove', 'committees.update')
     ) AS m(new_code, source_code)
JOIN permissions src_p ON src_p.code = m.source_code
JOIN permissions new_p ON new_p.code = m.new_code
JOIN role_permissions rp ON rp.permission_id = src_p.permission_id
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ============================ (2) تواريخ اللجان الدائمة ============================
ALTER TABLE committee_formation_requests DROP CONSTRAINT chk_committee_formation_requests_dates;
ALTER TABLE committee_formation_requests
    ADD CONSTRAINT chk_committee_formation_requests_dates CHECK (
        (start_date IS NOT NULL AND end_date IS NOT NULL AND end_date > start_date)
        OR
        (duration_type = 'permanent' AND start_date IS NULL AND end_date IS NULL)
    );

ALTER TABLE committees DROP CONSTRAINT chk_committees_dates;
ALTER TABLE committees
    ADD CONSTRAINT chk_committees_dates CHECK (
        (start_date IS NOT NULL AND end_date IS NOT NULL AND end_date > start_date)
        OR
        (duration_type = 'permanent' AND start_date IS NULL AND end_date IS NULL)
    );

-- ============================ (2) سجل تغييرات اللجنة ============================
CREATE TABLE committee_changes (
    change_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    committee_id     UUID NOT NULL REFERENCES committees(committee_id) ON DELETE CASCADE,
    change_type      VARCHAR(30) NOT NULL,
    -- العضو المعني (المُضاف/المحذوف/الرئيس أو الأمين الجديد). NULL لتغيير الفترة
    -- أو لإلغاء أمين السر.
    subject_user_id  UUID REFERENCES users(user_id),
    -- الرئيس/الأمين السابق عند التبديل.
    previous_user_id UUID REFERENCES users(user_id),
    -- تفاصيل إضافية (مثال: الفترة قبل وبعد التمديد).
    details          JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason           TEXT,
    changed_by       UUID NOT NULL REFERENCES users(user_id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_committee_changes_type CHECK (change_type IN (
        'member_added', 'member_removed', 'chair_changed', 'secretary_changed', 'period_extended'
    ))
);

CREATE INDEX ix_committee_changes_committee_created
    ON committee_changes (committee_id, created_at DESC);

-- نفس نمط الجداول الجديدة (0045/0046/0047): RLS مفعّل بلا سياسات — الوصول
-- عبر الباك-إند فقط (دور قاعدة البيانات المالك يتجاوزه).
ALTER TABLE committee_changes ENABLE ROW LEVEL SECURITY;

COMMIT;
