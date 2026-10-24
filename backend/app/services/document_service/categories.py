"""
تصنيفات الوثائق (Document Categories).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentCategory, DocumentCategoryScope
from app.models.user import User
from app.services import audit_service
from app.services.document_service.errors import DocumentValidationError
from app.services.document_service.loading import load_category, load_department, only_columns


async def _assert_unique_category_name(
    db: AsyncSession,
    *,
    name: str,
    scope: DocumentCategoryScope,
    department_id: uuid.UUID | None,
    exclude_category_id: uuid.UUID | None = None,
) -> None:
    stmt = select(DocumentCategory).options(*only_columns()).where(
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
    stmt = select(DocumentCategory).options(*only_columns()).where(DocumentCategory.deleted_at.is_(None))
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
    category = await load_category(db, category_id)
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
        department = await load_department(db, department_id)
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
    # إعادة تحميل الأعمدة فقط (بدل db.refresh الذي يعيد تحميل علاقات
    # التصنيف الافتراضية: الإدارة/المنشئ وشجرتيهما).
    return await load_category(db, category.category_id, reload=True)


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
    # إعادة تحميل الأعمدة فقط (بدل db.refresh الذي يعيد تحميل علاقات
    # التصنيف الافتراضية: الإدارة/المنشئ وشجرتيهما).
    return await load_category(db, category.category_id, reload=True)


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
    # إعادة تحميل الأعمدة فقط (بدل db.refresh الذي يعيد تحميل علاقات
    # التصنيف الافتراضية: الإدارة/المنشئ وشجرتيهما).
    return await load_category(db, category.category_id, reload=True)
