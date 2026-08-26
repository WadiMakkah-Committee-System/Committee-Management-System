-- =====================================================================
-- 0011_job_titles.sql
-- الهدف: وحدة "المسميات الوظيفية" (Job Titles) — مستقلة تمامًا عن أسماء
--        الأدوار (Roles). تُستخدم لعرض منصب المستخدم الفعلي (مثال:
--        "مديرة تقنية المعلومات") بجانب اسمه بمنتقي أعضاء طلب تشكيل
--        اللجنة، وكحقل اختياري بنموذج المستخدم.
--
-- قرار عمل موثّق (Lama): المسمى الوظيفي حقل مستقل تمامًا، وليس إعادة
-- استخدام لأسماء الأدوار — دور المستخدم (Role، مستوى الحساب) يبقى منفصلًا
-- تمامًا عن أي "دور لجنة" مستقبلي.
--
-- الحذف: فعلي (DELETE)، وليس Soft Delete كالإدارات — مع حارس بمستوى
-- التطبيق يمنع حذف مسمى قيد الاستخدام (نفس نمط role_service.delete_role).
-- =====================================================================

CREATE TABLE job_titles (
    job_title_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(150) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- تفرد الاسم (case-insensitive) — لا يوجد Soft Delete هنا فلا حاجة لشرط جزئي
CREATE UNIQUE INDEX uq_job_titles_name ON job_titles (lower(name));

-- نفس trigger تحديث updated_at المستخدَم بباقي جداول النظام
CREATE TRIGGER trg_job_titles_set_updated_at
    BEFORE UPDATE ON job_titles
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ربط اختياري بالمستخدم — ON DELETE SET NULL: حذف مسمى وظيفي (لو انحذف من
-- مسار آخر لاحقًا) لا يحذف المستخدم، فقط يفرغ حقله
ALTER TABLE users ADD COLUMN job_title_id UUID REFERENCES job_titles(job_title_id) ON DELETE SET NULL;

-- 4 صلاحيات جديدة لكتالوج permissions (قسم job_titles، بعد آخر قسم موجود)
INSERT INTO permissions (code, category, label_ar, sort_order) VALUES
    ('job_titles.view',   'job_titles', 'عرض المسميات الوظيفية',   76),
    ('job_titles.create', 'job_titles', 'إضافة مسمى وظيفي',        77),
    ('job_titles.update', 'job_titles', 'تعديل مسمى وظيفي',        78),
    ('job_titles.delete', 'job_titles', 'حذف مسمى وظيفي',          79);

-- منح صلاحيات job_titles تلقائيًا لأي دور يملك بالفعل users.create أو
-- users.update (قرار عمل: من يقدر يدير المستخدمين يقدر يدير مسمياتهم
-- الوظيفية). super_admin يحصل عليها ضمنيًا عبر تجاوز is_super_admin
-- بالباك-إند بغض النظر عن جدول role_permissions.
INSERT INTO role_permissions (role_id, permission_id)
SELECT DISTINCT rp.role_id, p.permission_id
FROM role_permissions rp
JOIN permissions existing ON existing.permission_id = rp.permission_id
CROSS JOIN permissions p
WHERE existing.code IN ('users.create', 'users.update')
  AND p.category = 'job_titles';
