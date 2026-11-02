"""
مرفقات المهمة (طلب صاحبة المشروع 2026-11-01): رئيسة اللجنة تقدر ترفق ملفًا
اختياريًا عند إنشاء المهمة، والمسؤول عن المهمة يقدر يرفع أكثر من ملف
لاحقًا ويعدّل/يحذف مرفقاته — بنفس نمط meeting_service.attachments
بالضبط: الملف يُخزَّن كوثيقة حقيقية بوحدة "إدارة الوثائق" (نفس Supabase
Storage)، ثم يُربَط بالمهمة عبر document_links (linked_entity_type=
'task_attachment') — لا جدول جديد.

التفويض: يُعاد استخدام _require_object_scoped_access(..., _STATUS_UPDATE, ...)
— تصحيح 2026-11-02 (كانت _UPDATE، وتلك لا يملكها إلا رئيسة اللجنة فعليًا
بقاعدة البيانات، فكان رفع المرفق يفشل لأي عضو عادي مسؤول عن المهمة).
tasks.status.update يملكها كل من رئيسة اللجنة والعضو المسؤول عن مهمته —
نفس الصلاحية المستخدمة لتحديث حالة المهمة، و_require_object_scoped_access
تقيّد العضو العادي (غير الرئيسة) بمهامه المسندة له هو فقط تلقائيًا. هذا
يحقق المطلوب تمامًا: المسؤول يرفع/يحذف مرفقات مهمته، ورئيسة اللجنة تقدر
ترفق عند الإنشاء (وبعده أيضًا — نفس صلاحيتها الإدارية الموجودة أصلًا على
كل مهام لجنتها).
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage_client
from app.models.document import Document, DocumentLink
from app.models.task import Task
from app.models.user import User
from app.services import document_service
from app.services.committee_access import CommitteeAccess
from app.services.task_service.access import _require_object_scoped_access
from app.services.task_service.codes import _STATUS_UPDATE, _VIEW_DETAILS
from app.services.task_service.errors import TaskNotFoundError
from app.services.task_service.loading import load_task

_LINK_TYPE = "task_attachment"


class AttachmentNotFoundError(TaskNotFoundError):
    """المرفق غير موجود ضمن هذه المهمة — تُترجَم إلى 404 (نفس TaskNotFoundError)."""


async def add_attachment(
    db: AsyncSession,
    *,
    actor: User,
    task_id: uuid.UUID,
    title: str,
    file_name: str,
    mime_type: str,
    content: bytes,
) -> tuple[Document, datetime]:
    """يتطلب tasks.status.update على هذه المهمة تحديدًا (رئيسة اللجنة، أو المسؤول عنها هو)."""
    access = CommitteeAccess(db, actor)
    task = await load_task(db, task_id)
    committee = task.committee  # محمَّلة مع المهمة (loading.task_options)
    await _require_object_scoped_access(
        access, committee, task, _STATUS_UPDATE, "ليست لديك صلاحية إرفاق ملف بهذه المهمة",
        "لا يمكنك إرفاق ملف إلا بمهامك المسندة لك أنت تحديدًا",
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
        linked_entity_id=task_id,
        linked_by=actor.user_id,
    )
    db.add(link)
    await db.flush()
    await db.refresh(link)
    await db.commit()
    return document, link.linked_at


async def list_attachments(
    db: AsyncSession, *, actor: User, task_id: uuid.UUID
) -> list[tuple[Document, datetime]]:
    """يتطلب tasks.view_details على هذه المهمة (نفس فحص عرض تفاصيلها)."""
    access = CommitteeAccess(db, actor)
    task = await load_task(db, task_id)
    committee = task.committee
    await _require_object_scoped_access(
        access, committee, task, _VIEW_DETAILS, "ليست لديك صلاحية عرض مرفقات هذه المهمة",
        "لا يمكنك عرض مرفقات إلا لمهامك المسندة لك أنت تحديدًا",
    )

    stmt = (
        select(DocumentLink, Document)
        .join(Document, Document.document_id == DocumentLink.document_id)
        .where(
            DocumentLink.linked_entity_id == task_id,
            DocumentLink.linked_entity_type == _LINK_TYPE,
            Document.deleted_at.is_(None),
        )
        .order_by(DocumentLink.linked_at.asc())
    )
    result = await db.execute(stmt)
    return [(document, link.linked_at) for link, document in result.all()]


async def get_attachment_download(
    db: AsyncSession, *, actor: User, task_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[Document, bytes]:
    """يتطلب tasks.view_details — يرجع محتوى الملف مباشرة (نفس منطق
    meeting_service.get_attachment_download)."""
    access = CommitteeAccess(db, actor)
    task = await load_task(db, task_id)
    committee = task.committee
    await _require_object_scoped_access(
        access, committee, task, _VIEW_DETAILS, "ليست لديك صلاحية لعرض مرفقات هذه المهمة",
        "لا يمكنك عرض مرفقات إلا لمهامك المسندة لك أنت تحديدًا",
    )

    link_result = await db.execute(
        select(DocumentLink, Document)
        .join(Document, Document.document_id == DocumentLink.document_id)
        .where(
            DocumentLink.linked_entity_id == task_id,
            DocumentLink.document_id == document_id,
            DocumentLink.linked_entity_type == _LINK_TYPE,
            Document.deleted_at.is_(None),
        )
    )
    row = link_result.first()
    if row is None:
        raise AttachmentNotFoundError("المرفق غير موجود ضمن هذه المهمة")
    document = row[1]
    content = await storage_client.download_object(document.storage_path)
    return document, content


async def delete_attachment(
    db: AsyncSession, *, actor: User, task_id: uuid.UUID, document_id: uuid.UUID
) -> None:
    """يتطلب tasks.status.update على هذه المهمة — يحذف الوثيقة نفسها (Soft Delete)."""
    access = CommitteeAccess(db, actor)
    task = await load_task(db, task_id)
    committee = task.committee
    await _require_object_scoped_access(
        access, committee, task, _STATUS_UPDATE, "ليست لديك صلاحية حذف مرفقات هذه المهمة",
        "لا يمكنك حذف مرفقات إلا من مهامك المسندة لك أنت تحديدًا",
    )

    link_result = await db.execute(
        select(DocumentLink).where(
            DocumentLink.linked_entity_id == task_id,
            DocumentLink.document_id == document_id,
            DocumentLink.linked_entity_type == _LINK_TYPE,
        )
    )
    if link_result.scalar_one_or_none() is None:
        raise AttachmentNotFoundError("المرفق غير موجود ضمن هذه المهمة")

    deleted = await document_service.delete_document(db, actor=actor, document_id=document_id)
    if deleted is None:
        raise AttachmentNotFoundError("المرفق غير موجود")
