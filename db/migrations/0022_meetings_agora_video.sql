-- =====================================================================
-- 0022_meetings_agora_video.sql
-- الهدف: اجتماعات الفيديو عن بعد الفعلية (Agora RTC) لاجتماعات mode='remote'
-- — Phase امتداد لـ0018/0019/0020 (إدارة الاجتماعات)، بطلب صريح من صاحبة
-- المشروع 2026-09-05 لبدء تكامل فعلي (بدون انتظار مرحلة Teams المؤجَّلة
-- أصلًا — راجعي ملاحظة teams_meeting_id/teams_join_url برأس
-- db/migrations/0018_meetings_schema.sql: تلك محجوزة لتكامل مختلف تمامًا
-- لاحقًا، ولا علاقة لها بهذا الملف).
--
-- ملاحظة مزامنة: طُبِّق هذا الملف مباشرة على قاعدة Supabase الحقيقية قبل أن
-- يُنسخ إلى هذا المستودع، بنفس نمط 0020 (راجعي رأسه لسبب هذا النمط).
--
-- قرار تصميم: القناة (Agora channel) هي meeting_id نصًا مباشرة (UUID فريد
-- أصلًا) — بلا حاجة لعمود إضافي بجدول meetings. Token نفسه لا يُخزَّن (قصير
-- العمر، يُصدَر عند كل /join من app.core.agora_client، ولا يصل AGORA_APP_
-- CERTIFICATE للـFrontend أبدًا — يبقى Backend فقط، نفس مبدأ
-- SUPABASE_SERVICE_ROLE_KEY في storage_client.py).
--
-- meeting_attendance منفصل تمامًا عن meeting_participants (المدعوّون
-- المخطَّط لهم عند الجدولة) — يسجّل من *انضم فعليًا* ومتى (سطر تدقيقي)،
-- بصرف النظر هل كان أصلًا من ضمن participant_ids المخطَّط لهم أو لا (الوصول
-- الفعلي محكوم بـmeetings.join على مستوى اللجنة، تمامًا كبقية meetings.*).
--
-- started_at/ended_at بجدول meetings معلوماتيان بحتان (متى فعليًا كان فيه
-- أول/آخر حضور) — **لا تُعدَّل meetings.status هنا** (upcoming/ongoing/
-- finished): التحويل التلقائي لحالة الاجتماع مؤجَّل صراحة لمرحلة تكامل
-- لاحقة (راجعي docstring meeting_service.py::delete_meeting) وليس جزءًا من
-- هذا التغيير.
-- =====================================================================

ALTER TABLE meetings
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS meeting_attendance (
    attendance_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES meetings(meeting_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    agora_uid INTEGER NOT NULL,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    left_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_meeting_attendance_meeting_id ON meeting_attendance(meeting_id);
CREATE INDEX IF NOT EXISTS idx_meeting_attendance_user_id ON meeting_attendance(user_id);
CREATE INDEX IF NOT EXISTS idx_meeting_attendance_open_sessions
    ON meeting_attendance(meeting_id, user_id) WHERE left_at IS NULL;

-- سطرا تدقيق جديدان (audit_logs.action_type) للانضمام/المغادرة — بجانب
-- create/update/delete/... الموجودة أصلًا (راجعي db/migrations/0004).
ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'join';
ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'leave';

-- صلاحية جديدة بكتالوج permissions (قسم meetings، بعد آخر كود موجود:
-- meetings.summary.view بـsort_order=42 — الترقيم هنا عالمي وليس لكل قسم،
-- راجعي 0011_job_titles.sql، فالقيمة التالية عالميًا وقت هذا الملف = 86).
INSERT INTO permissions (code, category, label_ar, sort_order)
SELECT 'meetings.join', 'meetings', 'الانضمام لاجتماع عن بعد (فيديو)', 86
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'meetings.join');

-- منح تلقائي بنفس نمط 0011 (job_titles.* يرث ممن يملك users.create/update):
-- أي دور يملك meetings.view أصلًا يحصل تلقائيًا على meetings.join أيضًا —
-- قرار عمل: من يقدر يشاهد اجتماع عن بعد يقدر ينضم لغرفته المرئية. لا يشمل
-- هذا أدوار اللجان (رئيس/عضو) تلقائيًا — 0017 أزال صراحة منحها الافتراضي
-- لأي كود meetings.*، فتبقى meetings.join مثل بقيتها: تُمنح يدويًا فقط من
-- شاشة الأدوار والصلاحيات لو رغبت صاحبة المشروع بذلك لاحقًا.
INSERT INTO role_permissions (role_id, permission_id, scope)
SELECT DISTINCT rp.role_id, p.permission_id, rp.scope
FROM role_permissions rp
JOIN permissions existing ON existing.permission_id = rp.permission_id
CROSS JOIN permissions p
WHERE existing.code = 'meetings.view'
  AND p.code = 'meetings.join'
  AND NOT EXISTS (
    SELECT 1 FROM role_permissions rp2
    WHERE rp2.role_id = rp.role_id AND rp2.permission_id = p.permission_id
  );
