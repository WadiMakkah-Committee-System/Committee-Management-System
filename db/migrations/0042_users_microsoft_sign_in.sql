-- =====================================================================
-- 0042_users_microsoft_sign_in.sql
-- الهدف: تجهيز قاعدة البيانات للدخول بحساب Microsoft 365 حق الشركة
-- (قرار لاما 2026-11-02) — إضافة على الدخول بكلمة المرور، لا بديل عنه.
--
-- قواعد العمل المعتمدة (لاما 2026-11-02):
-- 1) لا تسجيل ذاتي: السوبر أدمن ينشئ المستخدم كالمعتاد (FR-UM-001)، والدخول
--    بـMicrosoft يربط حساب Microsoft بمستخدم موجود مسبقًا عبر البريد.
-- 2) أول دخول ناجح بـMicrosoft يحفظ معرّف Entra الثابت (Object ID) للمستخدم،
--    وكل دخول بعده لازم يطابقه — فلو تغيّر بريد مستخدم بالمنصة لاحقًا
--    (بالغلط أو عمدًا) ليطابق بريد موظف آخر، لا يقدر يدخل بهويته.
-- 3) الحساب الموقوف/المحذوف لا يدخل حتى لو حساب Microsoft صحيح.
-- 4) من ليس له حساب Microsoft بالشركة (أعضاء من خارجها) يبقى دخوله بكلمة
--    المرور بكل متطلبات FR-UM-015..019 كما هي.
--
-- التغييرات:
-- أ) users.microsoft_object_id (جديد، اختياري): Object ID لحساب Microsoft
--    المرتبط. NULL = لم يدخل بـMicrosoft بعد (أو ليس له حساب).
-- ب) فهرس UNIQUE جزئي عليه (للحسابات غير المحذوفة): حساب Microsoft واحد
--    لا يرتبط بأكثر من مستخدم بالمنصة.
-- ج) فهرس على lower(email) (للحسابات غير المحذوفة): البحث عن المستخدم ببريد
--    Microsoft بدون حساسية لحالة الأحرف (L.Alzhrani = l.alzhrani). ليس UNIQUE
--    حتى لا يتغير سلوك إنشاء المستخدمين الحالي — والباك-إند يرفض الدخول لو
--    طابق البريد أكثر من مستخدم.
--
-- أثر على البيانات القائمة: لا شيء — العمود الجديد NULL لكل المستخدمين.
-- =====================================================================

BEGIN;

ALTER TABLE users ADD COLUMN microsoft_object_id UUID;

COMMENT ON COLUMN users.microsoft_object_id IS
    'Object ID لحساب Microsoft 365 المرتبط (يُحفظ عند أول دخول بـMicrosoft) — NULL إن لم يُربط';

CREATE UNIQUE INDEX uq_users_microsoft_object_id_active
    ON users (microsoft_object_id)
    WHERE microsoft_object_id IS NOT NULL AND deleted_at IS NULL;

CREATE INDEX idx_users_email_lower_active
    ON users (lower(email))
    WHERE deleted_at IS NULL;

COMMIT;
