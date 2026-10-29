"""
مرفقات الاجتماع (عرض تقديمي + مرفقات عامة) عبر document_links.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage_client
from app.models.document import Document, DocumentLink
from app.models.user import User
from app.services import document_service
from app.services.meeting_service.access import _require_access
from app.services.meeting_service.errors import AttachmentNotFoundError
from app.services.meeting_service.loading import load_meeting


_ATTACHMENT_LINK_TYPE = {
    "presentation": "meeting_presentation",
    "attachment": "meeting_attachment",
}



# ============================== مرفقات الاجتماع ==============================
# قسمان مستقلان (kind): 'presentation' (العرض التقديمي — عادةً ملف واحد،
# لا قيد بالكود يفرض ذلك) و'attachment' (مرفقات عامة، متعددة). كلاهما
# يُخزَّن كوثيقة حقيقية بوحدة "إدارة الوثائق" (نفس Supabase Storage)، ثم
# يُربَط بالاجتماع عبر document_links — أول استخدام فعلي لهذا الجدول
# (كان جاهزًا بالقاعدة منذ 0012، غير مستخدَم من أي API قبل الآن). التحميل
# (download) لا يمر عبر GET /documents/{document_id}/download العام، لأنه
# محمي بصلاحية Role نظامية ثابتة (documents.download) غالبًا لا يملكها
# عضو اللجنة العادي — بينما هو أصلًا يملك صلاحية meetings.attachments.view
# على مستوى دور اللجنة. لذلك get_attachment_download بالأسفل يعيد محتوى
# الملف مباشرة بعد التحقق من نفس صلاحية العرض، بمسار مخصص بوحدة الاجتماعات.


async def add_attachment(
    db: AsyncSession,
    *,
    actor: User,
    meeting_id: uuid.UUID,
    kind: str,
    title: str,
    file_name: str,
    mime_type: str,
    content: bytes,
) -> tuple[Document, datetime]:
    """يتطلب meetings.attachments.add — يخزّن الملف كوثيقة ثم يربطها بالاجتماع."""
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_access(
        db,
        actor,
        committee,
        "meetings.attachments.add",
        "ليست لديك صلاحية إضافة مرفقات لهذا الاجتماع",
    )

    # الوثيقة تُرى افتراضيًا من أعضاء اللجنة نفسها (visible_committees) —
    # نفس منطق رؤية وثائق اللجنة في وحدة الوثائق، وليست عامة (is_public=False).
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
        linked_entity_type=_ATTACHMENT_LINK_TYPE[kind],
        linked_entity_id=meeting_id,
        linked_by=actor.user_id,
    )
    db.add(link)
    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    await db.refresh(link)
    await db.commit()
    return document, link.linked_at


async def list_attachments(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, kind: str | None
) -> list[tuple[Document, str, datetime]]:
    """يتطلب meetings.attachments.view. يرجع (الوثيقة، kind، تاريخ الربط) لكل مرفق."""
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_access(
        db,
        actor,
        committee,
        "meetings.attachments.view",
        "ليست لديك صلاحية عرض مرفقات هذا الاجتماع",
    )

    link_types = (
        [_ATTACHMENT_LINK_TYPE[kind]] if kind else list(_ATTACHMENT_LINK_TYPE.values())
    )
    stmt = (
        select(DocumentLink, Document)
        .join(Document, Document.document_id == DocumentLink.document_id)
        .where(
            DocumentLink.linked_entity_id == meeting_id,
            DocumentLink.linked_entity_type.in_(link_types),
            Document.deleted_at.is_(None),
        )
        .order_by(DocumentLink.linked_at.asc())
    )
    result = await db.execute(stmt)
    reverse_kind = {v: k for k, v in _ATTACHMENT_LINK_TYPE.items()}
    return [
        (document, reverse_kind[link.linked_entity_type], link.linked_at)
        for link, document in result.all()
    ]


async def delete_attachment(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, document_id: uuid.UUID
) -> None:
    """يتطلب meetings.attachments.delete — يحذف الوثيقة نفسها (Soft Delete)، وليس الربط فقط."""
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_access(
        db,
        actor,
        committee,
        "meetings.attachments.delete",
        "ليست لديك صلاحية حذف مرفقات هذا الاجتماع",
    )

    link_result = await db.execute(
        select(DocumentLink).where(
            DocumentLink.linked_entity_id == meeting_id,
            DocumentLink.document_id == document_id,
            DocumentLink.linked_entity_type.in_(_ATTACHMENT_LINK_TYPE.values()),
        )
    )
    if link_result.scalar_one_or_none() is None:
        raise AttachmentNotFoundError("المرفق غير موجود ضمن هذا الاجتماع")

    deleted = await document_service.delete_document(db, actor=actor, document_id=document_id)
    if deleted is None:
        raise AttachmentNotFoundError("المرفق غير موجود")


async def get_attachment_download(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[Document, bytes]:
    """يتطلب meetings.attachments.view — يرجع محتوى الملف الفعلي مباشرة (وليس
    عبر GET /documents، لأن ذلك يتطلب صلاحية documents.download المنفصلة
    التي لا يملكها أعضاء اللجنة غالبًا)."""
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_access(
        db,
        actor,
        committee,
        "meetings.attachments.view",
        "ليست لديك صلاحية لعرض مرفقات هذا الاجتماع",
    )

    link_result = await db.execute(
        select(DocumentLink, Document)
        .join(Document, Document.document_id == DocumentLink.document_id)
        .where(
            DocumentLink.linked_entity_id == meeting_id,
            DocumentLink.document_id == document_id,
            DocumentLink.linked_entity_type.in_(_ATTACHMENT_LINK_TYPE.values()),
            Document.deleted_at.is_(None),
        )
    )
    row = link_result.first()
    if row is None:
        raise AttachmentNotFoundError("المرفق غير موجود ضمن هذا الاجتماع")
    document = row[1]
    content = await storage_client.download_object(document.storage_path)
    return document, content



