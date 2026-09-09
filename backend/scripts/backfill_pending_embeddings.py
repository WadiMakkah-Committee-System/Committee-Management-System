r"""
الهدف:
سكربت لمرة واحدة (one-off) لتوليد embedding لكل وثيقة "عالقة" على
embedding_status='pending' — أي وثيقة رُفعت قبل دمج ميزة البحث الذكي
بـmain (PR #43)، فما انجدول لها BackgroundTask أصلاً وقت الرفع، وبالتالي
بتضل pending للأبد بدون تدخل يدوي. هذا سكربت تشغّليه مرة وحدة بعد الدمج
عشان "تُلحق" كل الوثائق القديمة، مو جزء دائم من التطبيق.

طريقة التشغيل (من مجلد backend، مع تفعيل venv عشان يوصل GEMINI_API_KEY
والنت الحقيقي — ما يشتغل من بيئة بدون نت):
    venv\Scripts\activate      (PowerShell: venv\Scripts\Activate.ps1)
    python scripts/backfill_pending_embeddings.py
"""

import asyncio
import logging

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.document import Document, DocumentEmbeddingStatus
from app.services.document_embedding_service import generate_embedding_for_document

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("backfill_pending_embeddings")


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Document.document_id, Document.title).where(
                Document.embedding_status == DocumentEmbeddingStatus.pending,
                Document.deleted_at.is_(None),
            )
        )
        rows = result.all()

    if not rows:
        logger.info("ما فيه أي وثيقة بحالة pending — كله محدَّث.")
        return

    logger.info("لقيت %d وثيقة بحالة pending — بدأ التوليد...", len(rows))

    for i, (document_id, title) in enumerate(rows, start=1):
        logger.info("(%d/%d) %s — %s", i, len(rows), document_id, title)
        try:
            await generate_embedding_for_document(document_id)
        except Exception:  # noqa: BLE001 — سكربت one-off، أي خطأ بوثيقة وحدة ما يوقف الباقي
            logger.exception("فشل غير متوقع بالوثيقة %s — أكمل للي بعدها", document_id)

    logger.info("خلص. راجعي embedding_status بجدول documents للتأكد.")


if __name__ == "__main__":
    asyncio.run(main())
