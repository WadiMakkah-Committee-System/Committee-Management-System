-- =====================================================================
-- 0040_document_links_entity_index.sql
-- الهدف: فهرس للبحث عن الوثائق المرتبطة بكيان (اجتماع/بند/...) — طلب لاما
-- 2026-11-01: مرفقات بنود جدول الأعمال + تصنيف "مرفقات اللجنة" بالوثائق.
--
-- المفتاح الأساسي لـdocument_links هو (document_id, linked_entity_type,
-- linked_entity_id) — يبدأ بـdocument_id، فلا يفيد استعلامات "كل مرفقات هذا
-- الاجتماع" (WHERE linked_entity_id = ? AND linked_entity_type IN (...)) التي
-- كانت تمسح الجدول كاملًا. لا تغيير بالبيانات.
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_document_links_entity
    ON document_links (linked_entity_id, linked_entity_type);
