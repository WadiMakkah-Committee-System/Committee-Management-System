-- =====================================================================
-- 0002_create_departments.sql
-- الهدف: جدول الإدارات — FR-UM-007 → FR-UM-010
-- =====================================================================

CREATE TABLE departments (
    dep_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(150) NOT NULL,
    description TEXT,
    deleted_at  TIMESTAMPTZ,                          -- Soft Delete — FR-UM-010
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- تفرد اسم الإدارة، باستثناء السجلات المحذوفة (Soft Delete) — يسمح بإعادة
-- استخدام نفس الاسم لإدارة جديدة بعد حذف القديمة.
CREATE UNIQUE INDEX uq_departments_name_active
    ON departments (name)
    WHERE deleted_at IS NULL;

-- تحديث updated_at تلقائيًا عند أي تعديل
CREATE TRIGGER trg_departments_set_updated_at
    BEFORE UPDATE ON departments
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();
