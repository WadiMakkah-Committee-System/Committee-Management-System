-- =====================================================================
-- 0001_extensions_and_helpers.sql
-- الهدف: تفعيل الإضافات الأساسية اللي تحتاجها كل الجداول، وإنشاء دالة
--        مشتركة لتحديث عمود updated_at تلقائيًا عند أي UPDATE.
-- =====================================================================

-- تفعيل pgcrypto لتوليد UUID عبر gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- دالة مشتركة: تحدّث عمود updated_at تلقائيًا عند أي تعديل على السجل.
-- تُستخدم عبر Trigger على كل جدول فيه عمود updated_at.
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
