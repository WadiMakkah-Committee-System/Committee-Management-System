"""
الهدف:
توليد embedding البحث الدلالي لوثيقة واحدة خلفيًا (BackgroundTask) بعد
رفعها — استخراج نص + استدعاء Gemini Embedding API + حفظ النتيجة، بمعزل
تام عن document_service.py (نفس فصل meeting_draft_service.py عن
meeting_service.py: طبقة "توليد بالذكاء الاصطناعي" منفصلة عن طبقة CRUD
الأساسية). راجعي رأس db/migrations/0029_documents_semantic_search.sql
للقرار الكامل.

المسؤولية:
- generate_embedding_for_document(): الدالة العامة الوحيدة — تُستدعى من
  BackgroundTasks بعد db.commit() برفع الوثيقة (نفس نمط notification_service
  بالضبط: تفتح جلسة AsyncSessionLocal مستقلة، لأن جلسة الطلب الأصلية
  مُغلَقة وقت تنفيذ الخلفية).
- لا ترمي أي استثناء للخارج أبدًا — أي فشل (استخراج نص فشل، Gemini فشل،
  الوثيقة نوعها غير مدعوم...) يُسجَّل بـembedding_status='failed' +
  embedding_error بدل تعطيل الطلب الأصلي (رفع الوثيقة نجح مسبقًا
  ورجع للمستخدم، هذا كله يجري بعده).
- وثيقة بدون نص قابل للاستخراج (نوع ملف غير مدعوم مثل صورة، أو PDF
  ممسوح ضوئيًا بلا طبقة نص) تُعلَّم completed بـcontent_text=None
  وembedding=None عمدًا — وليست 'failed' — لأنها ليست حالة خطأ، فقط
  وثيقة لن تظهر بنتائج البحث الدلالي/الشات (المستخدم لم يفعل شيء خطأ).
"""

import logging
import uuid
from datetime import datetime, timezone

from app.core import storage_client, text_extraction
from app.core.gemini_client import GeminiError, GeminiNotConfiguredError, embed_text
from app.db.session import AsyncSessionLocal
from app.models.document import Document, DocumentEmbeddingStatus

logger = logging.getLogger(__name__)


async def generate_embedding_for_document(document_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        document = await db.get(Document, document_id)
        if document is None or document.is_deleted:
            return  # حُذفت الوثيقة قبل ما توصل مهمة الخلفية لدورها — لا شيء نسويه

        document.embedding_status = DocumentEmbeddingStatus.processing
        await db.commit()

        try:
            content = await storage_client.download_object(document.storage_path)
            extracted_text = text_extraction.extract_text(content, document.mime_type)

            if extracted_text is None:
                # نوع ملف غير مدعوم للاستخراج حاليًا (صورة، PDF ممسوح ضوئيًا...) —
                # ليست حالة فشل، فقط لا يوجد نص نولّد منه embedding.
                document.content_text = None
                document.embedding = None
                document.embedding_status = DocumentEmbeddingStatus.completed
                document.embedded_at = datetime.now(timezone.utc)
                await db.commit()
                return

            vector = await embed_text(extracted_text, task_type="RETRIEVAL_DOCUMENT")

            document.content_text = extracted_text
            document.embedding = vector
            document.embedding_status = DocumentEmbeddingStatus.completed
            document.embedding_error = None
            document.embedded_at = datetime.now(timezone.utc)
            await db.commit()

        except (GeminiError, GeminiNotConfiguredError, storage_client.StorageError) as exc:
            await db.rollback()
            document = await db.get(Document, document_id)
            if document is not None:
                document.embedding_status = DocumentEmbeddingStatus.failed
                document.embedding_error = str(exc)[:500]
                await db.commit()
            logger.warning("فشل توليد embedding للوثيقة %s: %s", document_id, exc)
        except Exception as exc:  # noqa: BLE001 — أي خطأ غير متوقع، لا يجوز يسقط الـBackgroundTask بصمت بلا تسجيل
            await db.rollback()
            document = await db.get(Document, document_id)
            if document is not None:
                document.embedding_status = DocumentEmbeddingStatus.failed
                document.embedding_error = "خطأ غير متوقع أثناء توليد embedding"
                await db.commit()
            logger.exception("خطأ غير متوقع أثناء توليد embedding للوثيقة %s", document_id)
