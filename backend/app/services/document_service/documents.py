"""
الوثائق نفسها: القائمة/العرض/الرفع/التعديل/الحذف/التحميل.
"""

import uuid
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage_client
from app.core.config import settings
from app.models.committee import Committee
from app.models.department import Department
from app.models.document import Document, DocumentCategory
from app.models.user import User
from app.services import audit_service
from app.services.document_service.categories import get_category
from app.services.document_service.errors import DocumentValidationError
from app.services.document_service.loading import (
    committees_query,
    departments_query,
    documents_query,
    load_document,
    users_query,
)
from app.services.document_service.visibility import DocumentViewer, can_view_document


async def _resolve_visibility(
    db: AsyncSession,
    *,
    department_ids: list[uuid.UUID],
    committee_ids: list[uuid.UUID],
    user_ids: list[uuid.UUID],
) -> tuple[list[Department], list[Committee], list[User]]:
    departments: list[Department] = []
    if department_ids:
        result = await db.execute(departments_query().where(Department.dep_id.in_(department_ids)))
        departments = list(result.scalars().all())
        if len(departments) != len(set(department_ids)):
            raise DocumentValidationError("إحدى الإدارات المحددة لرؤية الوثيقة غير موجودة")

    committees: list[Committee] = []
    if committee_ids:
        result = await db.execute(committees_query().where(Committee.committee_id.in_(committee_ids)))
        committees = list(result.scalars().all())
        if len(committees) != len(set(committee_ids)):
            raise DocumentValidationError("إحدى اللجان المحددة لرؤية الوثيقة غير موجودة")

    users: list[User] = []
    if user_ids:
        result = await db.execute(users_query().where(User.user_id.in_(user_ids)))
        users = list(result.scalars().all())
        if len(users) != len(set(user_ids)):
            raise DocumentValidationError("أحد المستخدمين المحددين لرؤية الوثيقة غير موجود")

    return departments, committees, users


DocumentScopeFilter = Literal["public", "department", "committee", "shared"]


def _matches_scope_filter(document: Document, *, scope: DocumentScopeFilter) -> bool:
    """
    فلترة "قسم" الوثيقة لعنصر التحكم المُقسَّم (segmented filter) بأعلى
    صفحة الوثائق (الكل/عامة/إدارتي/لجاني/شورك معي) — تُطبَّق بعد فحص
    الرؤية (can_view_document) لا بدلًا عنه، فهي مجرد تصنيف عرضي لوثائق
    ظهرت للمستخدم أصلًا، وليست فحص صلاحية إضافي.
    """
    if scope == "public":
        return document.is_public
    if scope == "department":
        return bool(document.visible_departments)
    if scope == "committee":
        return bool(document.visible_committees)
    if scope == "shared":
        return bool(document.visible_users)
    return True


async def list_documents(
    db: AsyncSession,
    *,
    current_user: User,
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    can_search_content: bool = False,
    scope: DocumentScopeFilter | None = None,
    committee_id: uuid.UUID | None = None,
) -> list[Document]:
    stmt = documents_query().where(Document.deleted_at.is_(None))
    if category_id is not None:
        stmt = stmt.where(Document.category_id == category_id)
    if q:
        like = f"%{q.strip()}%"
        if can_search_content:
            stmt = stmt.where(
                Document.title.ilike(like)
                | Document.description.ilike(like)
                | Document.content_text.ilike(like)
            )
        else:
            stmt = stmt.where(Document.title.ilike(like) | Document.description.ilike(like))

    result = await db.execute(stmt.order_by(Document.created_at.desc()))
    documents = list(result.scalars().unique().all())

    viewer = DocumentViewer(db, current_user)
    visible = [
        doc
        for doc in documents
        if await can_view_document(db, current_user=current_user, document=doc, viewer=viewer)
    ]

    if scope is not None:
        visible = [doc for doc in visible if _matches_scope_filter(doc, scope=scope)]
    if committee_id is not None:
        visible = [
            doc
            for doc in visible
            if any(c.committee_id == committee_id for c in doc.visible_committees)
        ]
    return visible


async def get_document(
    db: AsyncSession, *, current_user: User, document_id: uuid.UUID
) -> Document | None:
    # content_text مُحمَّل: شات الوثيقة الواحدة (document_search_service) يقرأه.
    document = await load_document(db, document_id, with_content=True)
    if document is None:
        return None
    if not await can_view_document(db, current_user=current_user, document=document):
        return None
    return document


def _assert_public_category_consistency(
    *, category: DocumentCategory | None, is_public: bool
) -> None:
    """
    قرار منتج (طلب صريح من المستخدمة 2026-08-31، تشديد لا تحذير فقط):
    الوثيقة اللي تصنيفها خاص بإدارة معينة (scope == "department") ما
    يجوز تصير "عامة" (is_public=True) — لأن هذا يكسر منطق العزل نفسه:
    التصنيف محصور بإدارة، لكن الوثيقة نفسها تصير مرئية للجميع، وهذا
    تناقض يفتح ثغرة رؤية غير مقصودة بدل غلطة تشغيلية بسيطة يكفيها تحذير.
    التصنيفات العامة (scope == "global") أو عدم اختيار تصنيف أصلًا
    (category=None) لا قيد عليها.
    """
    if category is not None and category.scope == "department" and is_public:
        raise DocumentValidationError(
            "لا يمكن جعل الوثيقة عامة (متاحة للجميع) وتصنيفها في نفس الوقت "
            "خاص بإدارة معينة — إمّا اختاري تصنيفًا عامًا، أو ألغي خيار "
            '"إتاحة الوثيقة للجميع"'
        )


def _assert_single_visibility_category(
    *,
    is_public: bool,
    department_ids: list[uuid.UUID],
    committee_ids: list[uuid.UUID],
    user_ids: list[uuid.UUID],
) -> None:
    """
    قرار منتج (طلب صريح من المستخدمة 2026-09-02): نطاق رؤية الوثيقة فئة
    واحدة حصرية — إمّا عامة، أو إدارة/إدارات محددة، أو لجنة/لجان محددة، أو
    مستخدم/مستخدمون محددون — لا يجوز الجمع بين أكثر من فئة معًا (مثال:
    عامة + إدارة، أو إدارة + لجنة). الواجهة (DocumentFormModal) تفرض هذا
    عبر اختيار "نطاق الوثيقة" الحصري (تبويب واحد نشط في كل لحظة)، لكن هذا
    الفحص هو الحارس الفعلي على مستوى الباك-إند — أي طلب مباشر للـAPI
    (بدون المرور بالواجهة) قد يحاول إرسال أكثر من فئة معًا.
    """
    active_categories = sum(
        [bool(is_public), bool(department_ids), bool(committee_ids), bool(user_ids)]
    )
    if active_categories > 1:
        raise DocumentValidationError(
            "نطاق رؤية الوثيقة يجب أن يكون فئة واحدة فقط — عامة، أو إدارة، "
            "أو لجنة، أو مستخدمون محددون — وليس أكثر من فئة في نفس الوقت"
        )


async def create_document(
    db: AsyncSession,
    *,
    actor: User,
    title: str,
    description: str | None,
    category_id: uuid.UUID | None,
    is_public: bool,
    department_ids: list[uuid.UUID],
    committee_ids: list[uuid.UUID],
    user_ids: list[uuid.UUID],
    file_name: str,
    mime_type: str,
    content: bytes,
) -> Document:
    max_bytes = settings.MAX_DOCUMENT_UPLOAD_MB * 1024 * 1024
    if len(content) == 0:
        raise DocumentValidationError("الملف فارغ")
    if len(content) > max_bytes:
        raise DocumentValidationError(f"حجم الملف يتجاوز الحد المسموح ({settings.MAX_DOCUMENT_UPLOAD_MB} ميجابايت)")

    category: DocumentCategory | None = None
    if category_id is not None:
        category = await get_category(db, category_id)
        if category is None:
            raise DocumentValidationError("التصنيف المحدد غير موجود")
        if (
            category.scope == "department"
            and not actor.is_super_admin
            and category.department_id != actor.dep_id
        ):
            raise DocumentValidationError("لا يمكن استخدام تصنيف خاص بإدارة غير إدارتك")

    _assert_public_category_consistency(category=category, is_public=is_public)
    _assert_single_visibility_category(
        is_public=is_public,
        department_ids=department_ids,
        committee_ids=committee_ids,
        user_ids=user_ids,
    )

    departments, committees, users = await _resolve_visibility(
        db, department_ids=department_ids, committee_ids=committee_ids, user_ids=user_ids
    )

    document = Document(
        title=title,
        description=description,
        file_name=file_name,
        storage_path="",  # يُحدَّث أدناه بعد توليد document_id
        mime_type=mime_type or "application/octet-stream",
        file_size_bytes=len(content),
        category_id=category.category_id if category else None,
        is_public=is_public,
        uploaded_by=actor.user_id,
        visible_departments=departments,
        visible_committees=committees,
        visible_users=users,
    )
    db.add(document)
    await db.flush()  # لتوليد document_id قبل بناء storage_path

    # قرار موثّق (إصلاح خلل 2026-09-02): مفتاح الكائن بـSupabase Storage
    # هو معرّف الوثيقة (UUID) وحده — وليس الاسم الأصلي للملف كما كان
    # سابقًا (f"{document_id}/{file_name}") — لأن Supabase Storage يرفض
    # مفاتيح تحتوي أحرفًا عربية أو مسافات (خطأ InvalidKey)، والاسم الأصلي
    # لا يزال محفوظًا ببيانات الوثيقة الوصفية (file_name) ويُستخدم فقط
    # للعرض ورأس Content-Disposition عند التحميل، لا كجزء من مسار التخزين.
    storage_path = str(document.document_id)
    document.storage_path = storage_path

    try:
        await storage_client.upload_object(storage_path, content, content_type=document.mime_type)
    except storage_client.StorageError:
        await db.rollback()
        raise

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="upload",
        target_type="document",
        target_id=document.document_id,
        metadata={"title": title, "file_name": file_name, "size_bytes": len(content)},
    )
    # الرافع يرى وثيقته دائمًا (uploaded_by == actor.user_id) — نفس نتيجة
    # get_document، مع إعادة تحميل الكائن الجديد بخيارات التحميل الصريحة.
    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    created = await load_document(db, document.document_id, with_content=True, reload=True)
    await db.commit()
    assert created is not None
    return created


async def update_document(
    db: AsyncSession,
    *,
    actor: User,
    document_id: uuid.UUID,
    title: str | None,
    description: str | None,
    category_id: uuid.UUID | None,
    is_public: bool | None,
    department_ids: list[uuid.UUID] | None,
    committee_ids: list[uuid.UUID] | None,
    user_ids: list[uuid.UUID] | None,
    category_explicitly_set: bool,
) -> Document | None:
    document = await load_document(db, document_id)
    if document is None:
        return None

    changes: dict[str, object] = {}

    # نحسم أولًا "الحالة النهائية الفعلية" للتصنيف والعمومية قبل أي تعديل
    # فعلي على الكائن — لأن التعديل جزئي (PATCH): أي حقل لم يُرسَل يبقى على
    # قيمته الحالية بالوثيقة، فلازم نقارن التصنيف/العمومية الناتجين معًا
    # (وليس فقط الحقل المُرسَل بمفرده) قبل تطبيق فحص التناقض.
    resolved_category: DocumentCategory | None
    if category_explicitly_set:
        if category_id is not None:
            resolved_category = await get_category(db, category_id)
            if resolved_category is None:
                raise DocumentValidationError("التصنيف المحدد غير موجود")
            if (
                resolved_category.scope == "department"
                and not actor.is_super_admin
                and resolved_category.department_id != actor.dep_id
            ):
                raise DocumentValidationError("لا يمكن استخدام تصنيف خاص بإدارة غير إدارتك")
        else:
            resolved_category = None
    else:
        resolved_category = document.category

    resolved_is_public = is_public if is_public is not None else document.is_public
    _assert_public_category_consistency(category=resolved_category, is_public=resolved_is_public)

    # نفس منطق "الحالة النهائية الفعلية" أعلاه، مطبَّق على قوائم الرؤية
    # الثلاث لفحص "فئة واحدة حصرية" (راجعي _assert_single_visibility_category)
    # قبل أي تعديل فعلي — أي قائمة لم تُرسَل بالطلب تبقى على قيمتها الحالية.
    resolved_department_ids = (
        department_ids if department_ids is not None else [d.dep_id for d in document.visible_departments]
    )
    resolved_committee_ids = (
        committee_ids if committee_ids is not None else [c.committee_id for c in document.visible_committees]
    )
    resolved_user_ids = (
        user_ids if user_ids is not None else [u.user_id for u in document.visible_users]
    )
    _assert_single_visibility_category(
        is_public=resolved_is_public,
        department_ids=resolved_department_ids,
        committee_ids=resolved_committee_ids,
        user_ids=resolved_user_ids,
    )

    if title is not None:
        changes["title"] = {"before": document.title, "after": title}
        document.title = title
    if description is not None:
        document.description = description
    if category_explicitly_set:
        document.category_id = resolved_category.category_id if resolved_category else None
    if is_public is not None:
        document.is_public = is_public

    if department_ids is not None or committee_ids is not None or user_ids is not None:
        departments, committees, users = await _resolve_visibility(
            db,
            department_ids=resolved_department_ids,
            committee_ids=resolved_committee_ids,
            user_ids=resolved_user_ids,
        )
        if department_ids is not None:
            document.visible_departments = departments
        if committee_ids is not None:
            document.visible_committees = committees
        if user_ids is not None:
            document.visible_users = users

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="document",
        target_id=document.document_id,
        metadata=changes or {"note": "تعديل بيانات وصفية/رؤية"},
    )
    # إعادة تحميل بخيارات التحميل الصريحة (بدل db.refresh الذي يعيد تحميل
    # كل علاقات الوثيقة الافتراضية بشجرتها الكاملة).
    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    result = await load_document(db, document.document_id, reload=True)
    await db.commit()
    return result


async def delete_document(db: AsyncSession, *, actor: User, document_id: uuid.UUID) -> Document | None:
    document = await load_document(db, document_id)
    if document is None:
        return None

    document.deleted_at = datetime.now(timezone.utc)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="delete",
        target_type="document",
        target_id=document.document_id,
        metadata={"title": document.title, "file_name": document.file_name},
    )
    await db.commit()
    return document


async def download_document(
    db: AsyncSession, *, current_user: User, document_id: uuid.UUID
) -> tuple[Document, bytes] | None:
    document = await get_document(db, current_user=current_user, document_id=document_id)
    if document is None:
        return None

    content = await storage_client.download_object(document.storage_path)

    await audit_service.log_action(
        db,
        actor_user_id=current_user.user_id,
        action_type="download",
        target_type="document",
        target_id=document.document_id,
        metadata={"file_name": document.file_name},
    )
    await db.commit()

    return document, content
