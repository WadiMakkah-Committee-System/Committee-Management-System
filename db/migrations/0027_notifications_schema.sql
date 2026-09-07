-- =====================================================================
-- 0027_notifications_schema.sql
-- الهدف: وحدة "الإشعارات" — إشعارات داخل النظام (In-app) لكل الوحدات
-- (مهام/لجان/قرارات/اجتماعات)، بالإضافة لإشعارات البريد القائمة أصلًا
-- (notification_service.py — كانت مقصورة على الاجتماعات فقط). هذا
-- الجدول مستقل تمامًا عن إرسال البريد؛ إرسال بريد لحدث معيّن لا يعني
-- بالضرورة كتابة صف هنا، والعكس صحيح — كل نقطة إطلاق تقرر بنفسها أيّهما
-- (أو كلاهما) تحتاج (راجعي notification_service.py).
--
-- ملاحظات تصميم (بالاتفاق مع صاحبة المشروع 2026-09-07):
-- 1) نوعان من المستلمين حسب الحدث — كلاهما يُمثَّل بنفس الجدول، صف واحد
--    لكل (حدث، مستلم): إشعار لمستخدم واحد محدد (مثال: صاحب طلب لجنة عند
--    اعتماده)، أو إشعار جماعي يُكتب صفًا مستقلًا لكل مستخدم يملك صلاحية
--    معيّنة وقت وقوع الحدث (مثال: تقديم طلب لجنة → صف لكل من يملك
--    committees.request.update حاليًا). القائمة الجماعية تُحسب وقت
--    الإطلاق فقط (Snapshot) — لا ترتبط ديناميكيًا بالصلاحية لاحقًا، بنفس
--    مبدأ decision_assignees (اشتقاق تلقائي وقت الحدث، لا استعلام حي).
-- 2) event_type نصي حر (لا Enum بقاعدة البيانات) — القيم الممكنة تكبر
--    باستمرار مع كل وحدة جديدة، ونفس منطق kind بجدول permissions
--    (migration 0016: "Enum يحتاج migration لكل قيمة جديدة، عمود نصي لا
--    يحتاج"). القيم الفعلية موثقة بـnotification_service.py (مصدر
--    الحقيقة الوحيد لقائمة الأحداث المدعومة).
-- 3) related_entity_type/related_entity_id بدل FK مباشر لكل نوع كيان —
--    الإشعار قد يشير لمهمة أو طلب لجنة أو قرار أو اجتماع (Polymorphic)،
--    ولا يوجد جدول واحد يجمعهم. الواجهة تبني رابط التنقّل من النوع+المعرّف
--    مباشرة (مثال: task → /tasks/{id}). بدون FK فعلي (لا يمكن التعبير
--    عنه بقيد قاعدة بيانات واحد لعدّة جداول) — حذف الكيان الأصلي لاحقًا
--    (نادر، لا يوجد حذف فعلي لمعظم الكيانات بهذا المشروع) يترك الإشعار
--    كسجل تاريخي فقط، بدون رابط فعّال؛ الواجهة تتعامل مع هذا بعرض نص
--    الإشعار دائمًا حتى لو فشل التنقّل.
-- 4) is_read + read_at بدل جدول قراءة منفصل — كل إشعار مملوك لمستخدم
--    واحد فقط (بخلاف مثلًا رسائل جماعية بصندوق وارد مشترك)، فلا حاجة
--    لتتبّع "من قرأ" لعدة أشخاص لنفس الصف.
-- =====================================================================

CREATE TABLE notifications (
    notification_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_user_id   UUID NOT NULL REFERENCES users(user_id),

    event_type           VARCHAR(50)  NOT NULL,   -- راجعي notification_service.py لقائمة القيم المدعومة
    title                 VARCHAR(255) NOT NULL,   -- نص قصير جاهز للعرض بالجرس/القائمة
    body                  TEXT,                    -- تفاصيل إضافية اختيارية (مثال: سبب الإرجاع/الرفض)

    related_entity_type  VARCHAR(30),             -- 'task' | 'committee_request' | 'committee' | 'decision' | 'meeting'
    related_entity_id    UUID,                    -- معرّف الكيان — بدون FK فعلي (ملاحظة 3)

    is_read               BOOLEAN NOT NULL DEFAULT false,
    read_at               TIMESTAMPTZ,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_notifications_recipient_user_id ON notifications (recipient_user_id);
-- فهرس مركّب لاستعلام "غير المقروءة لمستخدم معيّن" (الأكثر تكرارًا — الجرس وعداده)
CREATE INDEX idx_notifications_recipient_unread   ON notifications (recipient_user_id, is_read);

-- ============================== Row Level Security ==============================
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
