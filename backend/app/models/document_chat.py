"""
الهدف:
نماذج SQLAlchemy ORM لـ"محادثات البحث الذكي داخل الوثائق" — راجعي رأس
db/migrations/0030_document_chat_conversations.sql للتصميم الكامل.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DocumentChatConversation(Base):
    __tablename__ = "document_chat_conversations"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    # NULL = محادثة الشات العام (كل الوثائق المرئية) — راجعي رأس الميجريشن.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    messages: Mapped[list["DocumentChatMessage"]] = relationship(
        back_populates="conversation",
        order_by="DocumentChatMessage.created_at",
        cascade="all, delete-orphan",
    )


class DocumentChatMessage(Base):
    __tablename__ = "document_chat_messages"

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_chat_conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
    )
    # 'user' أو 'assistant' — راجعي CHECK constraint بالميجريشن.
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # مصفوفة {document_id, title} — تُملأ فقط لرسائل role='assistant'.
    sources: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    conversation: Mapped["DocumentChatConversation"] = relationship(back_populates="messages")
