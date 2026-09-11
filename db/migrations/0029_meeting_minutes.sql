-- =====================================================================
-- 0029_meeting_minutes.sql
-- الهدف: تنفيذ وحدة "المحاضر" الكاملة (SRS §7 — المحاضر، §7.1 إعداد
-- المحضر، §7.2 إدارة التوقيعات) — مرجع التصميم النهائي هو تصميم Lovable
-- المرفق من لمى (minutes.id.tsx/store.tsx) + توضيحاتها الصريحة:
--   - آلة حالة المحضر (MinutesStage بـLovable): none → preparing →
--     review → approval → signature → completed. ("draft" بنوع
--     Lovable غير مستخدم فعليًا بأي بيانات seed ولا بأي انتقال حالة —
--     أُسقط عمدًا هنا).
--   - ثلاث قوالب ثابتة (Hardcoded بالباك-إند، بدون واجهة إدارة قوالب —
--     لمى أجّلت قرار "من يدير القوالب" صراحة لمرحلة لاحقة): تنفيذي/
--     رسمي/تفصيلي. القالب التفصيلي مختلف Layout فعليًا (لا مجرد اسم) —
--     أقسامه تُبنى ديناميكيًا بند بند من جدول أعمال الاجتماع نفسه
--     (راجعي app/services/meeting_minutes_service.py::_build_sections_
--     from_template)، بخلاف التنفيذي/الرسمي (قائمة أقسام ثابتة). أقسام
--     المحضر (sections) تُنسخ من القالب لحظة الاختيار إلى صف المحضر
--     نفسه (JSONB حر) — إضافة/حذف قسم بعدها لا يمسّ تعريف القالب
--     الأصلي إطلاقًا (طلب لمى الصريح).
--   - صلاحيات المحضر (minutes.templates.view/select, minutes.view,
--     minutes.update, minutes.approve, minutes.sign, minutes.export)
--     كانت مزروعة أصلًا بكتالوج الصلاحيات منذ 0006_roles_permissions.sql
--     (فئة 'minutes') قبل بناء أي شاشة فعلية لها — هذا أول استخدام
--     فعلي لها، ولا حاجة لإضافة أكواد صلاحيات جديدة بالكتالوج.
--   - المراجعون (reviewers) والموقّعون (signatures) جدولان علائقيان
--     حقيقيان (FK لـusers) بنفس نمط Decision.votes/assignees بهذا
--     المشروع — وليسا JSONB، لأنهما يرجعان لمستخدمين حقيقيين بحالة
--     تتغيّر (بخلاف sections اللي هي محتوى نصي حر تؤلفه اللجنة).
--   - التحرير التعاوني اللحظي (FR-MIN-005) يُبث عبر نفس قناة WebSocket
--     الموجودة أصلًا لغرفة الاجتماع (app/core/meeting_realtime.py —
--     connection_manager، حدث جديد "minutes.updated") — بلا حاجة لأي
--     جدول/بنية جديدة لهذا الغرض، وتأكدنا إن صلاحية الدخول لتلك القناة
--     (meetings.join) غير مربوطة بحالة الاجتماع، فتعمل بعد انتهائه.
-- =====================================================================

CREATE TYPE meeting_minutes_stage AS ENUM (
    'none',
    'preparing',
    'review',
    'approval',
    'signature',
    'completed'
);

CREATE TYPE meeting_minutes_review_status AS ENUM (
    'pending',
    'approved',
    'returned'
);

-- محضر واحد فقط لكل اجتماع (UNIQUE على meeting_id) — إعداد المحضر لا
-- يبدأ إلا "بعد انتهاء الاجتماع" (FR-MIN-001)، يُفرض هذا بطبقة الخدمة
-- (meeting.status IN ('finished','recorded'))، وليس بقيد قاعدة بيانات
-- (نفس نمط باقي القيود الشرطية بهذا المشروع).
CREATE TABLE meeting_minutes (
    minutes_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL UNIQUE REFERENCES meetings(meeting_id) ON DELETE CASCADE,
    template_id VARCHAR(20),
    stage meeting_minutes_stage NOT NULL DEFAULT 'none',
    owner_user_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    sections JSONB NOT NULL DEFAULT '[]'::jsonb,
    sent_to_review_at TIMESTAMPTZ,
    approved_at TIMESTAMPTZ,
    sent_for_signature_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_meeting_minutes_meeting_id ON meeting_minutes (meeting_id);

CREATE TABLE meeting_minutes_reviewers (
    reviewer_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    minutes_id UUID NOT NULL REFERENCES meeting_minutes(minutes_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    status meeting_minutes_review_status NOT NULL DEFAULT 'pending',
    comment TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (minutes_id, user_id)
);

CREATE INDEX idx_meeting_minutes_reviewers_minutes_id ON meeting_minutes_reviewers (minutes_id);

CREATE TABLE meeting_minutes_signatures (
    signature_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    minutes_id UUID NOT NULL REFERENCES meeting_minutes(minutes_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    signature_image TEXT,
    signed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (minutes_id, user_id)
);

CREATE INDEX idx_meeting_minutes_signatures_minutes_id ON meeting_minutes_signatures (minutes_id);
