"""
مرفقات القرار (طلب صاحبة المشروع 2026-11-01: رئيسة اللجنة تقدر ترفق ملفًا
اختياريًا — عادةً عند إنشاء القرار). نفس نمط meeting_service.attachments
بالضبط: الملف يُخزَّن كوثيقة حقيقية بوحدة "إدارة الوثائق" (نفس Supabase
Storage)، ثم يُربَط بالقرار عبر document_links (linked_entity_type=
'decision_attachment') — لا جدول جديد.

التفويض: الإضافة بصلاحية decisions.create نفسها (نفس صلاحية إنشاء
القرار — رئيسة اللجنة عادةً)؛ العرض/التحميل بصلاحية decisions.view
العادية (نفس من يرى القرار أصلًا). بلا حذف بهذه المرحلة — لم تُطلَب.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage_client
from app.models.document import Document, DocumentLink
from app.models.user import User
from app.services import document_service
from app.services.committee_access import CommitteeAccess
from app.services.decision_service.access import _require_access
from app.services.decision_service.errors import DecisionNotFoundError
from app.services.decision_service.loading import load_decision

_LINK_TYPE = "decision_attachment"


class AttachmentNotFoundError(DecisionNotFoundError):
    """المرفق غير موجود ضمن هذا القرار — تُترجَم إلى 404 (نفس DecisionNotFoundError)."""


async def add_attachment(
    db: AsyncSession,
    *,
    actor: User,
    decision_id: uuid.UUID,
    title: str,
    file_name: str,
    mime_type: str,
    content: bytes,
) -> tuple[Document, datetime]:
    """يتطلب decisions.create — يخزّن الملف كوثيقة ثم يربطها بالقرار."""
    access = CommitteeAccess(db, actor)
    decision = await load_decision(db, decision_id)
    committee = decision.committee  # محمَّلة مع القرار (loading.decision_options)
    await _require_access(
        access, committee, "decisions.create", "ليست لديك صلاحية إرفاق ملف بهذا القرار"
    )

    # الوثيقة تُرى افتراضيًا من أعضاء اللجنة نفسها (visible_committees) —
    # نفس منطق رؤية مرفقات الاجتماع تمامًا، وليست عامة (is_public=False).
    document = await document_service.create_document(
        db,
        actor=actor,
        title=title,
        description=None,
        category_id=None,
        is_public=False,
        department_ids=[],
        committee_ids=[committee.committee_id],
        user_ids=[],
        file_name=file_name,
        mime_type=mime_type,
        content=content,
    )

    link = DocumentLink(
        document_id=document.document_id,
        linked_entity_type=_LINK_TYPE,
        linked_entity_id=decision_id,
        linked_by=actor.user_id,
    )
    db.add(link)
    await db.flush()
    await db.refresh(link)
    await db.commit()
    return document, link.linked_at


async def list_attachments(
    db: AsyncSession, *, actor: User, decision_id: uuid.UUID
) -> list[tuple[Document, datetime]]:
    """يتطلب decisions.view. يرجع (الوثيقة، تاريخ الربط) لكل مرفق."""
    access = CommitteeAccess(db, actor)
    decision = await load_decision(db, decision_id)
    committee = decision.committee  # محمَّلة مع القرار (loading.decision_options)
    await _require_access(
        access, committee, "decisions.view", "ليست لديك صلاحية عرض مرفقات هذا القرار"
    )

    stmt = (
        select(DocumentLink, Document)
        .join(Document, Document.document_id == DocumentLink.document_id)
        .where(
            DocumentLink.linked_entity_id == decision_id,
            DocumentLink.linked_entity_type == _LINK_TYPE,
            Document.deleted_at.is_(None),
        )
        .order_by(DocumentLink.linked_at.asc())
    )
    result = await db.execute(stmt)
    return [(document, link.linked_at) for link, document in result.all()]


async def get_attachment_download(
    db: AsyncSession, *, actor: User, decision_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[Document, bytes]:
    """يتطلب decisions.view — يرجع محتوى الملف مباشرة (نفس منطق
    meeting_service.get_attachment_download: لا يمر عبر GET /documents
    العام، لأن ذلك يتطلب صلاحية documents.download المنفصلة)."""
    access = CommitteeAccess(db, actor)
    decision = await load_decision(db, decision_id)
    committee = decision.committee
    await _require_access(
        access, committee, "decisions.view", "ليست لديك صلاحية لعرض مرفقات هذا القرار"
    )

    link_result = await db.execute(
        select(DocumentLink, Document)
        .join(Document, Document.document_id == DocumentLink.document_id)
        .where(
            DocumentLink.linked_entity_id == decision_id,
            DocumentLink.document_id == document_id,
            DocumentLink.linked_entity_type == _LINK_TYPE,
            Document.deleted_at.is_(None),
        )
    )
    row = link_result.first()
    if row is None:
        raise AttachmentNotFoundError("المرفق غير موجود ضمن هذا القرار")
    document = row[1]
    content = await storage_client.download_object(document.storage_path)
    return document, content
