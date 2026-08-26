-- 0013_documents_permissions.sql
-- الهدف: توثيق كتالوج صلاحيات وحدة "إدارة الوثائق" (documents.* و
-- document_categories.*) كملف Migration فعلي.
--
-- خلفية: هذه الصفوف (permissions + role_permissions) كانت أُدرجت يدويًا
-- مباشرة على قاعدة Supabase الحية بتاريخ 2026-08-26 (راجع الملاحظة في
-- 0012_documents_schema.sql)، بدون ملف Migration مطابق — ما سبّب انحرافًا
-- (Drift) بين db/migrations/ والقاعدة الفعلية. هذا الملف يوثّق نفس
-- الصفوف بالضبط بحيث يُعيد أي إعداد جديد (محلي أو بيئة أخرى) نفس الحالة،
-- وباستخدام ON CONFLICT DO NOTHING لضمان أنه Idempotent إذا طُبِّق على
-- قاعدة فيها الصفوف مسبقًا (كحال Supabase الحية الآن).

INSERT INTO permissions (code, category, label_ar, sort_order) VALUES
    ('documents.upload',           'documents', 'رفع وثيقة',                      63),
    ('documents.export',           'documents', 'تصدير وثيقة',                    64),
    ('documents.search',           'documents', 'بحث عن وثيقة',                   65),
    ('documents.view',             'documents', 'عرض الوثيقة',                    66),
    ('documents.search_content',   'documents', 'بحث داخل محتوى الوثيقة',         67),
    ('documents.search_all_agent', 'documents', 'بحث داخل جميع الوثائق (إيجينت)', 68),
    ('documents.update',           'documents', 'تعديل وثيقة',                    69),
    ('documents.delete',           'documents', 'حذف وثيقة',                      70),
    ('documents.download',         'documents', 'تحميل وثيقة',                    71)
ON CONFLICT (code) DO NOTHING;

INSERT INTO permissions (code, category, label_ar, sort_order) VALUES
    ('document_categories.create_global',     'document_categories', 'إضافة تصنيف عام',          80),
    ('document_categories.update_global',     'document_categories', 'تعديل تصنيف عام',          81),
    ('document_categories.delete_global',     'document_categories', 'حذف تصنيف عام',            82),
    ('document_categories.create_department', 'document_categories', 'إضافة تصنيف خاص بالإدارة', 83),
    ('document_categories.update_department', 'document_categories', 'تعديل تصنيف خاص بالإدارة', 84),
    ('document_categories.delete_department', 'document_categories', 'حذف تصنيف خاص بالإدارة',   85)
ON CONFLICT (code) DO NOTHING;

-- منح صلاحيات الاستخدام الأساسية (رفع/عرض/بحث/تصدير) تلقائيًا لنفس
-- الأدوار الأربعة الممنوحة فعليًا على القاعدة الحية وقت كتابة هذا الملف.
-- صلاحيات التعديل/الحذف/التحميل و document_categories.* غير ممنوحة لأي
-- دور هنا عمدًا (قرار موثّق حينها) — ما عدا super_admin الذي يتجاوز كل
-- فحص صلاحية تلقائيًا بغض النظر عن هذا الجدول (راجع
-- app.core.dependencies.require_permission)؛ بقية الأدوار تُمنح لاحقًا
-- يدويًا من شاشة "الأدوار والصلاحيات" حسب ما يقرره الفريق.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id
FROM roles r
CROSS JOIN permissions p
WHERE r.name IN ('super_admin', 'executive_office_manager', 'رئيس لجنة', 'عضو اللجنة')
  AND p.code IN (
        'documents.upload', 'documents.view', 'documents.search',
        'documents.search_content', 'documents.search_all_agent', 'documents.export'
    )
ON CONFLICT DO NOTHING;
