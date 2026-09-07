-- =====================================================================
-- 0026_meeting_realtime.sql
-- الهدف: البنية التحتية اللحظية لغرفة الاجتماع الجديدة (محادثة داخل
-- الاجتماع + ربط القرارات بالاجتماع اللي انبثقت منه). قرار موثّق مع
-- صاحبة المشروع 2026-09-06: النقل اللحظي (رفع اليد + بث الرسائل) عبر
-- WebSocket حقيقي (app/core/meeting_realtime.py) وليس Polling — أول
-- استخدام WebSocket بهذا المشروع (بقية الوحدات REST + React Query فقط).
--
-- ============================== محادثة الاجتماع ==============================
-- صف واحد لكل رسالة، تُحفَظ فعليًا (بخلاف "رفع اليد" اللي يبقى حدثًا
-- عابرًا يُبث فقط عبر WS بلا تخزين — لا قيمة توثيقية له). التحميل الأول
-- للمحادثة عند فتح لوحة "المحادثة" عبر REST عادي (GET)، والرسائل
-- الجديدة تصل فوريًا عبر WS — راجعي app/services/meeting_chat_service.py.
-- التفويض: نفس صلاحية الانضمام للاجتماع (meetings.join) — من يقدر يدخل
-- الغرفة يقدر يكتب بالمحادثة، بلا صلاحية منفصلة (القرار نفسه المطبَّق
-- على meeting_service.join_meeting/leave_meeting).
CREATE TABLE meeting_chat_messages (
    message_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id  UUID NOT NULL REFERENCES meetings(meeting_id),
    sender_id   UUID NOT NULL REFERENCES users(user_id),
    body        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_meeting_chat_messages_meeting_id_created_at
    ON meeting_chat_messages (meeting_id, created_at);

-- ============================== ربط القرارات بالاجتماع ==============================
-- عمود اختياري (NULLABLE) — القرارات المستقلة (من شاشة "إدارة القرارات"
-- العامة) تبقى بلا meeting_id، وقرارات لوحة "غرفة الاجتماع" الجديدة
-- تُنشأ بـmeeting_id فعلي فيُربط تلقائيًا. ON DELETE SET NULL: حذف
-- الاجتماع لا يحذف القرار (القرار له حياة مستقلة بعد الاجتماع أصلًا —
-- يستمر بالتصويت/الاعتماد)، فقط يفقد ربطه بالاجتماع المصدر.
ALTER TABLE decisions
    ADD COLUMN meeting_id UUID REFERENCES meetings(meeting_id) ON DELETE SET NULL;

CREATE INDEX idx_decisions_meeting_id ON decisions (meeting_id) WHERE meeting_id IS NOT NULL;

-- ============================== Row Level Security ==============================
ALTER TABLE meeting_chat_messages ENABLE ROW LEVEL SECURITY;
