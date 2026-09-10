-- =====================================================================
-- 0030_document_chat_conversations.sql
-- الهدف: حفظ محادثات "البحث الذكي داخل الوثائق" (0029) بدل ما يكون كل
-- سؤال معزول عن سابقه — قرار موثّق مع لجينـ 2026-09-09: كل مستخدم يشوف
-- سجل محادثاته السابقة (شات وثيقة واحدة مفتوحة، أو الشات العام عبر كل
-- الوثائق) بـSidebar، يقدر يرجع لمحادثة قديمة يكمل فيها، وكل رسالة
-- جديدة بنفس المحادثة تاخذ آخر كام رسالة كسياق قبل ما تروح لـGemini
-- (راجعي app/services/document_search_service.py).
--
-- document_id NULLABLE بالضبط زي answer_question() الحالية: NULL يعني
-- محادثة بالشات العام (عبر كل الوثائق المرئية للمستخدم)، وإلا محادثة
-- بوثيقة واحدة محدَّدة. ON DELETE CASCADE على الوثيقة عمدًا (بخلاف
-- meeting_id بجدول decisions اللي يُفرَّغ لا يُحذف، راجعي 0026) —
-- محادثة عن وثيقة انحذفت فقدت معناها بالكامل، بخلاف قرار له حياة
-- مستقلة بعد اجتماعه.
--
-- تحديث updated_at بالمحادثة عند إضافة رسالة جديدة (عشان ترتيب Sidebar
-- بالأحدث نشاطًا أولًا) يصير من كود بايثون مباشرة (نفس معاملة الإضافة)
-- وليس عبر Trigger — اتساقًا مع بساطة meeting_chat_messages (0026) اللي
-- ما فيها أي Trigger إطلاقًا، بدل تعقيد إضافي بقاعدة البيانات لحالة
-- بسيطة.
-- =====================================================================

CREATE TABLE document_chat_conversations (
    conversation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(user_id),
    document_id     UUID REFERENCES documents(document_id) ON DELETE CASCADE,
    title           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- يخدم "قائمة محادثاتي مرتّبة بالأحدث نشاطًا" — استعلام Sidebar الأساسي.
CREATE INDEX idx_document_chat_conversations_user_id_updated_at
    ON document_chat_conversations (user_id, updated_at DESC);

-- ============================== رسائل المحادثة ==============================
-- sources JSONB (مصفوفة {document_id, title}) — تُملأ فقط لرسائل
-- role='assistant' (نفس شكل DocumentChatSourceOut الحالي)، NULL لرسائل
-- role='user'.
CREATE TABLE document_chat_messages (
    message_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES document_chat_conversations(conversation_id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    sources         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_document_chat_messages_conversation_id_created_at
    ON document_chat_messages (conversation_id, created_at);

-- ============================== Row Level Security ==============================
-- بلا أي Policy عمدًا — نفس نمط meeting_chat_messages (0026) بالضبط:
-- الفرض الفعلي بمسؤولية الـBackend فقط (نفس فلسفة CLAUDE.md)، RLS هنا
-- طبقة حماية إضافية ضد أي وصول مباشر عبر REST API العام لـSupabase.
ALTER TABLE document_chat_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chat_messages ENABLE ROW LEVEL SECURITY;
