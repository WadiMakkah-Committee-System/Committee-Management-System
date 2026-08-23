-- =====================================================================
-- 0007_department_code_manager.sql
-- الهدف: إضافة "الرمز التعريفي" (code) و"المسؤول عن الإدارة"
--        (manager_user_id) لجدول departments — حسب طلب العمل: عند إنشاء
--        إدارة جديدة، يُطلب اسمها ورمزها التعريفي (اختصار يدخله السوبر
--        أدمن يدويًا، مثال: "IT" لإدارة تقنية المعلومات) ووصفها والمسؤول
--        عنها (أي مستخدم في النظام)، ويُضاف المسؤول تلقائيًا كعضو في
--        قائمة أعضاء تلك الإدارة.
--
-- ملاحظة: العمودان NULLABLE على مستوى القاعدة حتى لا تنكسر الصفوف
-- الموجودة مسبقًا (إدارات أُنشئت قبل هذا الإصدار) — الإلزامية (NOT NULL)
-- مفروضة على مستوى الـ API فقط عند إنشاء إدارة جديدة (DepartmentCreate).
-- =====================================================================

ALTER TABLE departments ADD COLUMN code VARCHAR(20);
ALTER TABLE departments ADD COLUMN manager_user_id UUID REFERENCES users(user_id);

-- تفرد الرمز التعريفي بين الإدارات النشطة فقط (نفس منطق uq_departments_name_active)
CREATE UNIQUE INDEX uq_departments_code_active
    ON departments (lower(code))
    WHERE deleted_at IS NULL AND code IS NOT NULL;
