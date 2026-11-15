-- =====================================================================
-- 0048_department_hierarchy.sql
-- الهدف: هيكلة الإدارات على مستويين (إدارة أم ← إدارات تابعة) حسب الهيكل
-- التنظيمي الجديد لشركة وادي مكة (WM-HCM/25-1-0003)، ونطاق صلاحية جديد
-- "إدارته وما تحتها".
--
-- قواعد العمل المعتمدة (لاما 2026-11-15):
-- 1) الهيكل مستويان فقط: إدارة أم (parent_dep_id = NULL) وتحتها إدارات
--    تابعة. لا يوجد مستوى ثالث (إدارة تابعة لا يكون تحتها إدارات).
-- 2) المستخدم يبقى مربوطًا بإدارة واحدة عبر users.dep_id كما هو — قد تكون
--    إدارة تابعة، أو الإدارة الأم مباشرة (مثل مديرها العام).
-- 3) نطاقات الصلاحية تصير أربعة: own / department (إدارته فقط — بلا تغيير
--    في معناه) / department_tree (جديد: إدارته وكل الإدارات التابعة لها) /
--    all. صلاحيات مدير الإدارة الأم تُحدَّد من الدور الذي تنشئه لاما.
-- 4) الإدارات نفسها تُنشأ وتُربط يدويًا من المنصة (لاما) — هذا الملف لا
--    ينشئ ولا ينقل أي إدارة.
--
-- التغييرات:
-- أ) departments.parent_dep_id (NULLABLE) → departments.dep_id.
-- ب) قيد CHECK يمنع أن تكون الإدارة أمًّا لنفسها.
-- ج) Trigger يفرض قواعد الهيكل على مستوى القاعدة (وليس الكود فقط):
--    - الإدارة الأم يجب أن تكون موجودة وغير محذوفة.
--    - الإدارة الأم يجب أن تكون نفسها بلا أم (يمنع المستوى الثالث).
--    - إدارة لها إدارات تابعة نشطة لا يمكن جعلها تابعة لغيرها.
--    - إدارة لها إدارات تابعة نشطة لا يمكن حذفها (Soft Delete).
--    التزامن: قفل FOR SHARE على صف الإدارة الأم يمنع سباقًا بين ربط إدارة
--    تابعة جديدة وبين تحويل الأم لتابعة أو حذفها في نفس اللحظة.
-- د) فهرس على parent_dep_id للإدارات النشطة (عرض الإدارات التابعة + حساب
--    نطاق department_tree).
-- هـ) توسيع قيد role_permissions_scope_chk ليقبل 'department_tree'.
--
-- أثر على البيانات القائمة: لا شيء — كل الإدارات الحالية تصبح إدارات بلا أم
-- (parent_dep_id = NULL)، وكل الأدوار تبقى بنفس نطاقاتها بالضبط.
-- =====================================================================

BEGIN;

-- ============================ أ + ب) العمود والقيد ============================
ALTER TABLE departments
    ADD COLUMN parent_dep_id UUID REFERENCES departments(dep_id) ON DELETE RESTRICT;

ALTER TABLE departments
    ADD CONSTRAINT departments_parent_not_self_chk
    CHECK (parent_dep_id IS NULL OR parent_dep_id <> dep_id);

-- ============================ ج) فرض قواعد الهيكل ============================
/*
 * الهدف:
 *   فرض هيكل المستويين على جدول departments داخل قاعدة البيانات نفسها.
 * المسؤولية:
 *   يُستدعى قبل INSERT أو UPDATE على departments، ويرفض العملية برسالة
 *   عربية واضحة لو خالفت قواعد الهيكل.
 * المدخلات: NEW / OLD (صف الإدارة قبل وبعد التعديل).
 * المخرجات: NEW عند النجاح، أو استثناء (ERRCODE check_violation) عند المخالفة.
 * التأثيرات الجانبية: قفل FOR SHARE على صف الإدارة الأم حتى نهاية المعاملة.
 * الأخطاء المحتملة:
 *   - الإدارة الأم غير موجودة أو محذوفة.
 *   - الإدارة الأم تابعة لإدارة أخرى (مستوى ثالث).
 *   - محاولة جعل إدارة لها إدارات تابعة نشطة تابعةً لغيرها.
 *   - محاولة حذف إدارة لها إدارات تابعة نشطة.
 */
CREATE OR REPLACE FUNCTION enforce_department_hierarchy()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_parent_parent UUID;
    v_parent_deleted TIMESTAMPTZ;
    v_found BOOLEAN;
BEGIN
    -- 1) التحقق من الإدارة الأم (عند ربطها أو تغييرها فقط)
    IF NEW.parent_dep_id IS NOT NULL
       AND (TG_OP = 'INSERT' OR NEW.parent_dep_id IS DISTINCT FROM OLD.parent_dep_id) THEN

        SELECT parent_dep_id, deleted_at, true
          INTO v_parent_parent, v_parent_deleted, v_found
          FROM departments
         WHERE dep_id = NEW.parent_dep_id
         FOR SHARE;

        IF NOT COALESCE(v_found, false) OR v_parent_deleted IS NOT NULL THEN
            RAISE EXCEPTION 'الإدارة الأم غير موجودة أو محذوفة'
                USING ERRCODE = 'check_violation';
        END IF;

        IF v_parent_parent IS NOT NULL THEN
            RAISE EXCEPTION 'لا يمكن إضافة إدارة تحت إدارة تابعة — الهيكل مستويان فقط'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;

    -- 2) إدارة لها إدارات تابعة نشطة لا تصير تابعة لغيرها
    IF TG_OP = 'UPDATE'
       AND NEW.parent_dep_id IS NOT NULL
       AND OLD.parent_dep_id IS NULL
       AND EXISTS (
            SELECT 1 FROM departments c
             WHERE c.parent_dep_id = NEW.dep_id AND c.deleted_at IS NULL
       ) THEN
        RAISE EXCEPTION 'لا يمكن جعل هذه الإدارة تابعة لأن تحتها إدارات تابعة'
            USING ERRCODE = 'check_violation';
    END IF;

    -- 3) لا حذف (Soft Delete) لإدارة تحتها إدارات تابعة نشطة
    IF TG_OP = 'UPDATE'
       AND NEW.deleted_at IS NOT NULL
       AND OLD.deleted_at IS NULL
       AND EXISTS (
            SELECT 1 FROM departments c
             WHERE c.parent_dep_id = NEW.dep_id AND c.deleted_at IS NULL
       ) THEN
        RAISE EXCEPTION 'لا يمكن حذف إدارة تحتها إدارات تابعة — احذفي أو انقلي الإدارات التابعة أولًا'
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_departments_enforce_hierarchy
    BEFORE INSERT OR UPDATE OF parent_dep_id, deleted_at ON departments
    FOR EACH ROW
    EXECUTE FUNCTION enforce_department_hierarchy();

-- ============================ د) الفهرس ============================
CREATE INDEX ix_departments_parent_active
    ON departments (parent_dep_id)
    WHERE deleted_at IS NULL AND parent_dep_id IS NOT NULL;

-- ============================ هـ) نطاق الصلاحية الجديد ============================
ALTER TABLE role_permissions DROP CONSTRAINT role_permissions_scope_chk;
ALTER TABLE role_permissions
    ADD CONSTRAINT role_permissions_scope_chk
    CHECK (scope IN ('own', 'department', 'department_tree', 'all'));

COMMIT;
