-- =====================================================================
-- 0029_documents_semantic_search.sql
-- الهدف: تفعيل مرحلة "البحث الذكي داخل الوثائق" المؤجَّلة عمدًا منذ
-- 0012_documents_schema.sql — استخراج نص الوثيقة (content_text، عمود
-- موجود من البداية) وتوليد embedding فعلي له (عمود VECTOR(768) موجود
-- من البداية أيضًا) عبر Google Gemini Embedding API، لخدمة ميزتين:
-- (أ) بحث دلالي بمعنى النص لا بمطابقة الكلمات، (ب) شات بوت يجاوب من
-- محتوى الوثائق (RAG) — سواء عن وثيقة واحدة مفتوحة أو عبر كل الوثائق
-- المسموح للمستخدم رؤيتها. تطبيق فعلي لصلاحية documents.search_all_agent
-- المزروعة أصلًا بكتالوج الصلاحيات (0006/0014) ولم تُستخدَم بعد.
--
-- قرار مزود الذكاء الاصطناعي: نفس Gemini المستخدم أصلًا لمسودة اجتماعات
-- (app/core/gemini_client.py) — إعادة استخدام GEMINI_API_KEY نفسه، دالة
-- embedding جديدة منفصلة (نموذج text-embedding-004، 768 بُعد — يطابق
-- حجم العمود المحجوز أصلًا بالضبط دون أي تعديل عليه).
--
-- نمط تتبّع الحالة (pending/processing/completed/failed) نفس نمط
-- meeting_drafts (0025) بالضبط — التوليد هنا خلفي (BackgroundTask) عند
-- كل رفع/تعديل محتوى وثيقة، وليس بضغطة زر يدوية من المستخدم (بخلاف
-- مسودة الاجتماع)، لأن البحث يحتاج كل الوثائق مُفهرَسة تلقائيًا، لا
-- بالاختيار.
-- =====================================================================

CREATE TYPE document_embedding_status AS ENUM ('pending', 'processing', 'completed', 'failed');

ALTER TABLE public.documents
    ADD COLUMN embedding_status document_embedding_status NOT NULL DEFAULT 'pending',
    ADD COLUMN embedding_error  TEXT,
    ADD COLUMN embedded_at      TIMESTAMPTZ;

-- الوثائق المرفوعة قبل هذه الميجريشن ما لها embedding بعد — نعلّمها
-- pending صراحةً (رغم إنها القيمة الافتراضية أصلًا) حتى تلتقطها أي
-- مهمة Backfill لاحقة تبحث عن status='pending' تحديدًا دون لبس.
UPDATE public.documents SET embedding_status = 'pending' WHERE deleted_at IS NULL;

-- فهرس ANN (HNSW) للمقارنة السريعة بالتشابه الدلالي (cosine) — الصفوف
-- اللي embedding فيها NULL (لسا ما اتولّد لها) تُستثنى من الفهرس تلقائيًا
-- بدون أي شرط WHERE إضافي (pgvector يتجاهل NULL بفهارس ANN).
CREATE INDEX idx_documents_embedding_hnsw
    ON public.documents USING hnsw (embedding vector_cosine_ops);

-- فهرس بسيط لمهمة Backfill/إعادة محاولة مستقبلية تلقط الوثائق
-- pending/failed دون فحص الجدول كاملًا.
CREATE INDEX idx_documents_embedding_status
    ON public.documents (embedding_status)
    WHERE deleted_at IS NULL;
