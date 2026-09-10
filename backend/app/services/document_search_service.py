"""
الهدف:
منطق "البحث الذكي داخل الوثائق" — بحث دلالي (معنى النص لا مطابقة
الكلمات) وشات بوت يجاوب من محتوى الوثائق (RAG)، سواء عن وثيقة واحدة
مفتوحة أو عبر كل الوثائق المسموح للمستخدم رؤيتها. راجعي رأس
db/migrations/0029_documents_semantic_search.sql للقرار الكامل.

المسؤولية:
- semantic_search(): يحوّل سؤال المستخدم لـembedding عبر Gemini، يجيب
  أقرب الوثائق بالتشابه الدلالي من القاعدة (pgvector)، ثم يطبّق فحص
  الرؤية الحالي (document_service.can_view_document — نفس القيد
  المطبَّق على قائمة الوثائق العادية بلا أي استثناء) *قبل* إرجاع أي
  نتيجة — الفلترة تسحب أكثر من العدد المطلوب أولًا (over-fetch) لأن
  فحص الرؤية بايثوني وليس شرط SQL (نفس قيد document_service.list_documents
  الحالي)، فبعض أقرب النتائج دلاليًا قد لا تكون مرئية للمستخدم.
- answer_question(): يبني إجابة الشات بوت — إمّا من وثيقة واحدة محدَّدة
  (document_id، بعد التأكد إنها مرئية للمستخدم عبر document_service.get_document
  أصلًا)، أو من أقرب الوثائق المرئية له (بدون document_id — الشات
  العام، عبر semantic_search أعلاه).

ملاحظة أمنية مهمة: لا نمرّر لـGemini أبدًا محتوى وثيقة لم تجتز فحص
can_view_document للمستخدم الحالي — الفلترة تسبق أي استدعاء لـGemini،
وليس بعده (راجعي docstring app/core/gemini_client.py answer_from_documents
لتفاصيل الصياغة نفسها).

حفظ المحادثات (0030): answer_question تحفظ كل سؤال/جواب تلقائيًا عبر
app/services/document_chat_service.py — إمّا بمحادثة جديدة (conversation_id
غير مُعطى) أو مستمرة بمحادثة قائمة (بعد التحقق من ملكيتها ونطاقها).
آخر رسائل المحادثة تُمرَّر كـhistory لـGemini لفهم أسئلة المتابعة، لكنها
أبدًا مصدر للإجابة نفسها (راجعي answer_from_documents).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gemini_client import GeminiNotConfiguredError, answer_from_documents, embed_text
from app.models.document import Document
from app.models.user import User
from app.services import document_chat_service, document_service

# نسحب أكثر من العدد النهائي المطلوب من قاعدة البيانات (ترتيبًا
# بالتشابه) قبل فحص الرؤية — حتى لو أول عدة نتائج دلاليًا غير مرئية
# للمستخدم، يبقى عندنا احتياطي كافٍ غالبًا نوصل منه للعدد المطلوب فعليًا.
_OVER_FETCH_MULTIPLIER = 6


class DocumentSearchNotConfiguredError(Exception):
    """Gemini غير مهيَّأ (GEMINI_API_KEY فارغ) — البحث الذكي/الشات معطَّلان مؤقتًا."""


async def semantic_search(
    db: AsyncSession, *, current_user: User, query: str, limit: int = 5
) -> list[Document]:
    """أقرب limit وثيقة دلاليًا لسؤال query من الوثائق المرئية فعليًا
    لـcurrent_user فقط — راجعي docstring رأس الملف لترتيب الفلترة."""
    try:
        query_vector = await embed_text(query, task_type="RETRIEVAL_QUERY")
    except GeminiNotConfiguredError as exc:
        raise DocumentSearchNotConfiguredError(str(exc)) from exc

    over_fetch_limit = limit * _OVER_FETCH_MULTIPLIER
    stmt = (
        select(Document)
        .where(Document.deleted_at.is_(None), Document.embedding.is_not(None))
        .order_by(Document.embedding.cosine_distance(query_vector))
        .limit(over_fetch_limit)
    )
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())

    visible: list[Document] = []
    for candidate in candidates:
        if len(visible) >= limit:
            break
        if await document_service.can_view_document(db, current_user=current_user, document=candidate):
            visible.append(candidate)
    return visible


async def answer_question(
    db: AsyncSession,
    *,
    current_user: User,
    question: str,
    document_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> dict:
    """
    document_id مُعطى → شات "وثيقة واحدة مفتوحة" (يتحقق من رؤيتها أولًا
    عبر document_service.get_document — يرجع 404 منطقي عبر document=None
    لو غير موجودة/غير مرئية، بدل تسريب حتى بوجودها، نفس فلسفة get_document
    الحالية بالضبط).
    document_id غير مُعطى → شات "كل الوثائق" عبر semantic_search أعلاه.

    conversation_id مُعطى → يتابع محادثة قائمة (بعد التحقق من ملكيتها
    ونطاقها عبر document_chat_service.get_owned_conversation — ترمي
    document_chat_service.ConversationNotFoundError لو غير صالحة، الطبقة
    المستدعية بـAPI تترجمها لـ404). غير مُعطى → محادثة جديدة تلقائيًا.
    """
    if document_id is not None:
        document = await document_service.get_document(
            db, current_user=current_user, document_id=document_id
        )
        if document is None:
            return {"answer": None, "sources": [], "not_found": True, "conversation_id": None}
        source_documents = [document] if document.content_text else []
    else:
        source_documents = await semantic_search(db, current_user=current_user, query=question, limit=5)

    if conversation_id is not None:
        conversation = await document_chat_service.get_owned_conversation(
            db, user=current_user, conversation_id=conversation_id, document_id=document_id
        )
    else:
        conversation = await document_chat_service.create_conversation(
            db, user=current_user, document_id=document_id
        )

    # سياق المحادثة *قبل* حفظ سؤال المستخدم الحالي — وإلا يرجع كسياق لنفسه.
    history = await document_chat_service.get_recent_history(
        db, conversation_id=conversation.conversation_id
    )
    await document_chat_service.add_message(db, conversation=conversation, role="user", content=question)

    context = [
        {"document_id": str(doc.document_id), "title": doc.title, "content": doc.content_text or ""}
        for doc in source_documents
        if doc.content_text
    ]

    try:
        result = await answer_from_documents(question=question, documents=context, history=history)
    except GeminiNotConfiguredError as exc:
        raise DocumentSearchNotConfiguredError(str(exc)) from exc

    # نحوّل used_document_ids (نصوص أرجعها Gemini) لكائنات {document_id, title}
    # كاملة هنا مباشرة — الطبقة المستدعية (API) ما تحتاج تستعلم القاعدة
    # ثانية لجلب العناوين، عندنا source_documents أصلًا بهذا النطاق.
    used_ids = set(result["used_document_ids"])
    sources = [
        {"document_id": str(doc.document_id), "title": doc.title}
        for doc in source_documents
        if str(doc.document_id) in used_ids
    ]

    await document_chat_service.add_message(
        db, conversation=conversation, role="assistant", content=result["answer"], sources=sources or None
    )
    await db.commit()

    return {
        "answer": result["answer"],
        "sources": sources,
        "not_found": False,
        "conversation_id": conversation.conversation_id,
    }
