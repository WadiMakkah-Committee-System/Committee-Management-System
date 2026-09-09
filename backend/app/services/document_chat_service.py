"""
الهدف:
منطق العمل لحفظ ومتابعة محادثات "البحث الذكي داخل الوثائق" — راجعي رأس
db/migrations/0030_document_chat_conversations.sql للتصميم الكامل.
تُستدعى من document_search_service.answer_question (حفظ الأسئلة
والأجوبة تلقائيًا مع كل سؤال) ومن app/api/v1/documents.py مباشرة
(راوترات قوائم/تفاصيل المحادثات لعرض Sidebar بالواجهة).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_chat import DocumentChatConversation, DocumentChatMessage
from app.models.user import User

# عدد آخر الرسائل اللي تُرسَل لـGemini كسياق محادثة — راجعي
# app/core/gemini_client.py::answer_from_documents(history=...). عدد
# صغير عمدًا (5 أسئلة + 5 أجوبة) — كافٍ لفهم أسئلة المتابعة بلا تضخيم
# حجم الطلب لـGemini بلا داعٍ.
_HISTORY_MESSAGES_LIMIT = 10

# طول عنوان المحادثة المولَّد تلقائيًا من أول سؤال فيها (اقتطاع، نفس
# فكرة عناوين محادثات ChatGPT التلقائية) — يصير مرة وحدة بس لكل محادثة.
_AUTO_TITLE_MAX_LENGTH = 60


class ConversationNotFoundError(Exception):
    """المحادثة غير موجودة، أو لا تخص current_user، أو نطاقها (شات وثيقة
    محددة/شات عام) لا يطابق الطلب الحالي — تُترجَم إلى 404. عدم التفريق
    بين "غير موجودة" و"موجودة لكن لغيرك" مقصود (نفس فلسفة عدم تسريب
    وجود مورد لا يملكه الطالب، راجعي document_service.get_document)."""


async def get_owned_conversation(
    db: AsyncSession, *, user: User, conversation_id: uuid.UUID, document_id: uuid.UUID | None
) -> DocumentChatConversation:
    """يتأكد إن المحادثة موجودة، تخص user فعلاً، ونطاقها (document_id)
    يطابق الطلب الحالي بالضبط — محادثة شات عام (document_id=None) ما
    تصلح لمتابعة شات وثيقة محددة والعكس، حتى لو لنفس المستخدم."""
    result = await db.execute(
        select(DocumentChatConversation).where(
            DocumentChatConversation.conversation_id == conversation_id
        )
    )
    conversation = result.scalar_one_or_none()
    if (
        conversation is None
        or conversation.user_id != user.user_id
        or conversation.document_id != document_id
    ):
        raise ConversationNotFoundError("المحادثة غير موجودة")
    return conversation


async def create_conversation(
    db: AsyncSession, *, user: User, document_id: uuid.UUID | None
) -> DocumentChatConversation:
    conversation = DocumentChatConversation(user_id=user.user_id, document_id=document_id)
    db.add(conversation)
    await db.flush()  # نحتاج conversation_id مولَّد قبل ربط أول رسالة فيها
    return conversation


async def get_recent_history(
    db: AsyncSession, *, conversation_id: uuid.UUID, limit: int = _HISTORY_MESSAGES_LIMIT
) -> list[dict[str, str]]:
    """آخر limit رسالة بالمحادثة (بترتيب زمني تصاعدي) بشكل
    [{"role", "content"}] جاهز لتمريره مباشرة لـ
    gemini_client.answer_from_documents(history=...) — لازم تُستدعى
    *قبل* حفظ سؤال المستخدم الحالي بنفس المحادثة (وإلا السؤال الحالي
    يرجع كجزء من "سياقه" هو نفسه)."""
    result = await db.execute(
        select(DocumentChatMessage)
        .where(DocumentChatMessage.conversation_id == conversation_id)
        .order_by(DocumentChatMessage.created_at.desc())
        .limit(limit)
    )
    recent = list(reversed(result.scalars().all()))
    return [{"role": m.role, "content": m.content} for m in recent]


async def add_message(
    db: AsyncSession,
    *,
    conversation: DocumentChatConversation,
    role: str,
    content: str,
    sources: list[dict] | None = None,
) -> DocumentChatMessage:
    """يحفظ رسالة، ويحدّث عنوان المحادثة (أول سؤال فقط) وupdated_at (كل
    رسالة) — الأخير عشان ترتيب Sidebar بالأحدث نشاطًا أولًا يصير صحيح
    بدون Trigger إضافي بقاعدة البيانات (راجعي رأس الميجريشن)."""
    message = DocumentChatMessage(
        conversation_id=conversation.conversation_id, role=role, content=content, sources=sources
    )
    db.add(message)

    if role == "user" and conversation.title is None:
        conversation.title = (
            content
            if len(content) <= _AUTO_TITLE_MAX_LENGTH
            else content[:_AUTO_TITLE_MAX_LENGTH].rstrip() + "…"
        )

    conversation.updated_at = datetime.now(timezone.utc)
    return message


async def list_conversations(
    db: AsyncSession, *, user: User, document_id: uuid.UUID | None
) -> list[DocumentChatConversation]:
    """قائمة محادثات user بنفس النطاق بالضبط (شات عام لو document_id=None،
    أو محادثات وثيقة محددة)، الأحدث نشاطًا أولًا — تغذّي Sidebar."""
    result = await db.execute(
        select(DocumentChatConversation)
        .where(
            DocumentChatConversation.user_id == user.user_id,
            DocumentChatConversation.document_id == document_id,
        )
        .order_by(DocumentChatConversation.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_conversation_with_messages(
    db: AsyncSession, *, user: User, conversation_id: uuid.UUID, document_id: uuid.UUID | None
) -> DocumentChatConversation:
    """نفس get_owned_conversation + تحميل رسائلها كاملة — لفتح محادثة
    محدَّدة من الـSidebar."""
    conversation = await get_owned_conversation(
        db, user=user, conversation_id=conversation_id, document_id=document_id
    )
    await db.refresh(conversation, attribute_names=["messages"])
    return conversation
