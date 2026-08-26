"""
الهدف:
منطق العمل لوحدة "إدارة الوثائق" — تصنيفات الوثائق ونطاق رؤيتها المركّب
(عام / إدارة محددة / لجنة محددة / مستخدم محدد)، ورفع/عرض/تعديل/حذف/تحميل
الوثيقة نفسها (الملف الفعلي مخزَّن بـ Supabase Storage عبر
app.core.storage_client، هذه الوحدة تخزّن البيانات الوصفية فقط).

المسؤولية:
- فحص صلاحيات الرؤية المركّبة (is_public / إدارة المستخدم / لجانه /
  ارتباطه شخصيًا) لكل قراءة أو تحميل — بمعزل عن فحص صلاحية RBAC العامة
    (documents.view/download) التي تُفرض بطبقة الـ API عبر require_permission.
    - تسجيل كل عملية (رفع/تعديل/حذف/تحميل) في audit_logs عبر audit_service.

    قرارات موثّقة:
    - البحث (q) في هذه المرحلة ILIKE بسيط على العنوان/الوصف (ومحتوى الوثيقة
      إن كانت لدى المستخدم صلاحية documents.search_content) — عمود
        content_tsv (Full-Text Search عبر GIN index) جاهز بالقاعدة لكن غير
          مستخدَم بعد؛ الانتقال له تحسين لاحق عند الحاجة لأداء أفضل مع حجم بيانات
            أكبر. البحث الدلالي (embedding/Gemini، صلاحية documents.search_all_agent)
              مؤجَّل بالكامل لمرحلة الذكاء الاصطناعي القادمة (راجع docstring
                app/models/document.py).
                - documents.export موجودة بكتالوج الصلاحيات لمرحلة تصدير لاحقة (مثال:
                  تصدير قائمة الوثائق CSV) — لا يوجد لها Endpoint في هذه المرحلة، بنفس
                    منطق document_links (جاهز بالقاعدة، غير مُستخدم بعد).
                    - فحص "رؤية" وثيقة بعينها (get/download) يُرجع None (→ 404 بطبقة الـ API)
                      وليس خطأ صلاحية 403، حتى لا نكشف حتى بوجود الوثيقة لمن لا تظهر له.
                      - الحذف Soft Delete (deleted_at) اتساقًا مع بقية الكيانات الجوهرية —
                        الملف بالتخزين يبقى كما هو (لا نحذفه فعليًا)، فقط البيانات الوصفية
                          تُخفى من القوائم والوصول.
                          """

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import storage_client
from app.core.config import settings
from app.models.committee import Committee, committee_members
from app.models.department import Department
from app.models.document import (
    Document,
    DocumentCategory,
    DocumentCategoryScope,
)
from app.models.user import User
from app.services import audit_service


class DocumentValidationError(ValueError):
      """خطأ تحقق منطقي (اسم مكرر، حجم ملف متجاوز الحد، مرجع غير موجود...)."""


# ---------------------------------------------------------------------------
# صلاحيات الرؤية المركّبة (منفصلة عن RBAC العام)
# ---------------------------------------------------------------------------


async def _user_committee_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
      result = await db.execute(
                select(committee_members.c.committee_id).where(committee_members.c.user_id == user_id)
      )
      return {row[0] for row in result.all()}


async def can_view_document(db: AsyncSession, *, current_user: User, document: Document) -> bool:
      if current_user.is_super_admin:
                return True
            if document.is_public:
                      return True
                  if document.uploaded_by == current_user.user_id:
                            return True
                        if current_user.dep_id is not None and any(
                                  d.dep_id == current_user.dep_id for d in document.visible_departments
                        ):
                                  return True
                              if any(u.user_id == current_user.user_id for u in document.visible_users):
                                        return True
                                    if document.visible_committees:
                                              visible_committee_ids = {c.committee_id for c in document.visible_committees}
                                              user_committee_ids = await _user_committee_ids(db, current_user.user_id)
                                              if visible_committee_ids & user_committee_ids:
                                                            return True
                                                    return False


# ---------------------------------------------------------------------------
# تصنيفات الوثائق (Document Categories)
# ---------------------------------------------------------------------------


async def _assert_unique_category_name(
      db: AsyncSession,
      *,
      name: str,
      scope: DocumentCategoryScope,
      department_id: uuid.UUID | None,
      exclude_category_id: uuid.UUID | None = None,
) -> None:
      stmt = select(DocumentCategory).where(
                DocumentCategory.deleted_at.is_(None),
                DocumentCategory.scope == scope,
                DocumentCategory.department_id == department_id,
      )
    result = await db.execute(stmt)
    for existing in result.scalars().all():
              if existing.category_id == exclude_category_id:
                            continue
        if existing.name.strip().lower() == name.strip().lower():
                      raise DocumentValidationError("يوجد تصنيف بنفس الاسم في نفس النطاق مسبقًا")


async def list_categories(db: AsyncSession, *, current_user: User) -> list[DocumentCategory]:
      """
          التصنيفات العامة + تصنيفات إدارة المستخدم فقط (نفس منطق رؤية الوثائق) —
              ما عدا super_admin اللي يشوف كل التصنيفات (لإدارتها من شاشة واحدة).
                  """
    stmt = select(DocumentCategory).where(DocumentCategory.deleted_at.is_(None))
    if not current_user.is_super_admin:
              if current_user.dep_id is not None:
                            stmt = stmt.where(
                                              (DocumentCategory.scope == "global")
                                              | (
                                                                    (DocumentCategory.scope == "department")
                                                                    & (DocumentCategory.department_id == current_user.dep_id)
                                              )
                            )
else:
            stmt = stmt.where(DocumentCategory.scope == "global")
    result = await db.execute(stmt.order_by(DocumentCategory.name))
    return list(result.scalars().all())


async def get_category(db: AsyncSession, category_id: uuid.UUID) -> DocumentCategory | None:
      category = await db.get(DocumentCategory, category_id)
    if category is None or category.is_deleted:
              return None
    return category


async def create_category(
      db: AsyncSession,
      *,
      actor: User,
      name: str,
      scope: DocumentCategoryScope,
      department_id: uuid.UUID | None,
) -> DocumentCategory:
      if scope == "department" and not actor.is_super_admin and department_id != actor.dep_id:
                raise DocumentValidationError("لا يمكن إنشاء تصنيف خاص بإدارة غير إدارتك")

    if department_id is not None:
              department = await db.get(Department, department_id)
        if department is None or department.is_deleted:
                      raise DocumentValidationError("الإدارة المحددة غير موجودة")

    await _assert_unique_category_name(db, name=name, scope=scope, department_id=department_id)

    category = DocumentCategory(
              name=name, scope=scope, department_id=department_id, created_by=actor.user_id
    )
    db.add(category)
    await db.flush()

    await audit_service.log_action(
              db,
              actor_user_id=actor.user_id,
              action_type="create",
              target_type="document_category",
              target_id=category.category_id,
              metadata={"name": name, "scope": scope},
    )
    await db.commit()
    await db.refresh(category)
    return category


async def update_category(
      db: AsyncSession, *, actor: User, category_id: uuid.UUID, name: str
) -> DocumentCategory | None:
      category = await get_category(db, category_id)
    if category is None:
              return None
    if (
              category.scope == "department"
              and not actor.is_super_admin
              and category.department_id != actor.dep_id
    ):
              raise DocumentValidationError("لا يمكن تعديل تصنيف خاص بإدارة غير إدارتك")

    await _assert_unique_category_name(
              db,
              name=name,
              scope=category.scope,
              department_id=category.department_id,
              exclude_category_id=category.category_id,
    )

    before_name = category.name
    category.name = name

    await audit_service.log_action(
              db,
              actor_user_id=actor.user_id,
              action_type="update",
              target_type="document_category",
              target_id=category.category_id,
              metadata={"before": before_name, "after": name},
    )
    await db.commit()
    await db.refresh(category)
    return category


async def delete_category(
      db: AsyncSession, *, actor: User, category_id: uuid.UUID
) -> DocumentCategory | None:
      category = await get_category(db, category_id)
    if category is None:
              return None
    if (
              category.scope == "department"
              and not actor.is_super_admin
              and category.department_id != actor.dep_id
    ):
              raise DocumentValidationError("لا يمكن حذف تصنيف خاص بإدارة غير إدارتك")

    count_result = await db.execute(
              select(Document.document_id).where(
                            Document.category_id == category_id, Document.deleted_at.is_(None)
              )
    )
    if count_result.first() is not None:
              raise DocumentValidationError("لا يمكن حذف هذا التصنيف — لا تزال هناك وثائق مرتبطة به")

    category.deleted_at = datetime.now(timezone.utc)

    await audit_service.log_action(
              db,
              actor_user_id=actor.user_id,
              action_type="delete",
              target_type="document_category",
              target_id=category.category_id,
              metadata={"name": category.name},
    )
    await db.commit()
    await db.refresh(category)
    return category


# ---------------------------------------------------------------------------
# الوثائق (Documents)
# ---------------------------------------------------------------------------

_DOCUMENT_LOAD_OPTIONS = (
      selectinload(Document.category),
      selectinload(Document.uploader),
      selectinload(Document.visible_departments),
      selectinload(Document.visible_committees),
      selectinload(Document.visible_users),
)


async def _resolve_visibility(
      db: AsyncSession,
      *,
      department_ids: list[uuid.UUID],
      committee_ids: list[uuid.UUID],
      user_ids: list[uuid.UUID],
) -> tuple[list[Department], list[Committee], list[User]]:
      departments: list[Department] = []
    if department_ids:
              result = await db.execute(select(Department).where(Department.dep_id.in_(department_ids)))
        departments = list(result.scalars().all())
        if len(departments) != len(set(department_ids)):
                      raise DocumentValidationError("إحدى الإدارات المحددة لرؤية الوثيقة غير موجودة")

    committees: list[Committee] = []
    if committee_ids:
              result = await db.execute(select(Committee).where(Committee.committee_id.in_(committee_ids)))
        committees = list(result.scalars().all())
        if len(committees) != len(set(committee_ids)):
                      raise DocumentValidationError("إحدى اللجان المحددة لرؤية الوثيقة غير موجودة")

    users: list[User] = []
    if user_ids:
              result = await db.execute(select(User).where(User.user_id.in_(user_ids)))
        users = list(result.scalars().all())
        if len(users) != len(set(user_ids)):
                      raise DocumentValidationError("أحد المستخدمين المحددين لرؤية الوثيقة غير موجود")

    return departments, committees, users


async def list_documents(
      db: AsyncSession,
      *,
      current_user: User,
      q: str | None = None,
      category_id: uuid.UUID | None = None,
      can_search_content: bool = False,
) -> list[Document]:
      stmt = select(Document).where(Document.deleted_at.is_(None)).options(*_DOCUMENT_LOAD_OPTIONS)
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
    documents = list(result.scalars().all())

    if current_user.is_super_admin:
              return documents
    return [doc for doc in documents if await can_view_document(db, current_user=current_user, document=doc)]


async def get_document(
      db: AsyncSession, *, current_user: User, document_id: uuid.UUID
) -> Document | None:
      stmt = (
                select(Document)
                .where(Document.document_id == document_id, Document.deleted_at.is_(None))
                .options(*_DOCUMENT_LOAD_OPTIONS)
      )
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()
    if document is None:
              return None
    if not await can_view_document(db, current_user=current_user, document=document):
              return None
    return document


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

    storage_path = f"{document.document_id}/{file_name}"
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
    await db.commit()

    created = await get_document(db, current_user=actor, document_id=document.document_id)
    assert created is not None  # الرافع يرى وثيقته دائمًا (uploaded_by == actor.user_id)
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
      stmt = (
                select(Document)
                .where(Document.document_id == document_id, Document.deleted_at.is_(None))
                .options(*_DOCUMENT_LOAD_OPTIONS)
      )
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()
    if document is None:
              return None

    changes: dict[str, object] = {}

    if title is not None:
              changes["title"] = {"before": document.title, "after": title}
        document.title = title
    if description is not None:
              document.description = description
    if category_explicitly_set:
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
            document.category_id = category.category_id
else:
            document.category_id = None
    if is_public is not None:
              document.is_public = is_public

    if department_ids is not None or committee_ids is not None or user_ids is not None:
              departments, committees, users = await _resolve_visibility(
                            db,
                            department_ids=department_ids if department_ids is not None else [
                                              d.dep_id for d in document.visible_departments
                            ],
                            committee_ids=committee_ids if committee_ids is not None else [
                                              c.committee_id for c in document.visible_committees
                            ],
                            user_ids=user_ids if user_ids is not None else [u.user_id for u in document.visible_users],
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
    await db.commit()
    await db.refresh(document)
    return document


async def delete_document(db: AsyncSession, *, actor: User, document_id: uuid.UUID) -> Document | None:
      document = await db.get(Document, document_id)
    if document is None or document.is_deleted:
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
    await db.refresh(document)
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
