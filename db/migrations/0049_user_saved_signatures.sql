-- =====================================================================
-- 0049_user_saved_signatures.sql
-- الهدف: حفظ توقيع المستخدم في المنصة، عشان يقدر يوقّع المحضر بتوقيعه
-- المحفوظ بدل ما يرسمه كل مرة (قالب المحضر المعتمد — قرار صاحب المشروع
-- 2026-11-15، راجعي docs/minutes-official-template.md).
--
-- قواعد العمل المعتمدة:
-- 1) خانة التوقيع بالمحضر تعطي العضو خيارين: يرسم توقيعه الآن، أو يستخدم
--    توقيعه المحفوظ في المنصة فيُدرج مباشرة.
-- 2) لكل مستخدم توقيع محفوظ واحد كحد أقصى، يقدر يستبدله أو يحذفه.
-- 3) التوقيع المحفوظ يخص صاحبه فقط: لا أحد يقرأه أو يعدّله غيره. عند
--    التوقيع بالمحفوظ يُنسخ من هذا الجدول بطبقة الخدمة (الخادم) — لا تُقبل
--    صورة "محفوظة" مرسلة من الواجهة.
-- 4) حسابات الضيوف (users.is_guest) ما لها توقيع محفوظ، لأن الضيوف لا
--    يوقّعون على المحضر. يُفرض بطبقة الخدمة (نفس نمط القيود الشرطية
--    بهذا المشروع — القيد يحتاج قراءة جدول users).
--
-- لماذا جدول مستقل وليس عمودًا في users؟
--   صورة التوقيع (base64) حجمها عشرات الكيلوبايت، وصفوف users تُحمَّل
--   تلقائيًا في أغلب مسارات النظام (علاقات lazy="selectin"). عمود بهذا الحجم
--   في users يثقل كل استعلام يجلب مستخدمين. الجدول المستقل لا يُقرأ إلا
--   عند الحاجة (صفحة توقيعي، أو لحظة التوقيع).
--
-- الصيغة: نفس صيغة meeting_minutes_signatures.signature_image الحالية —
--   data URL لصورة PNG (ناتج toDataURL('image/png') من react-signature-canvas).
--   الحد الأعلى 300,000 حرف (≈ 220 كيلوبايت) — توقيع مرسوم عادي أقل بكثير.
--
-- أثر على البيانات القائمة: لا شيء — جدول جديد فارغ، ولا يُعدَّل أي جدول
-- موجود. آمن للتطبيق قبل نشر الكود الجديد (النسخة الحالية لا تعرفه أصلًا).
-- =====================================================================

BEGIN;

CREATE TABLE user_saved_signatures (
    user_id UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    signature_image TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT user_saved_signatures_image_format_chk
        CHECK (signature_image LIKE 'data:image/png;base64,%'),
    CONSTRAINT user_saved_signatures_image_size_chk
        CHECK (length(signature_image) BETWEEN 30 AND 300000)
);

COMMENT ON TABLE user_saved_signatures IS
    'التوقيع المحفوظ لكل مستخدم (صف واحد كحد أقصى) — يُستخدم للتوقيع على المحاضر بدل الرسم كل مرة';
COMMENT ON COLUMN user_saved_signatures.signature_image IS
    'صورة التوقيع بصيغة data:image/png;base64 — تُقرأ بطبقة الخدمة فقط لصاحبها';

CREATE TRIGGER trg_user_saved_signatures_set_updated_at
    BEFORE UPDATE ON user_saved_signatures
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- RLS: نفس نمط الجداول الجديدة (0047) — يمنع الوصول المباشر من واجهة
-- Supabase العامة (anon/authenticated)؛ الخادم الخلفي يتصل بصلاحية مالك
-- الجداول فلا يتأثر.
ALTER TABLE user_saved_signatures ENABLE ROW LEVEL SECURITY;

COMMIT;
