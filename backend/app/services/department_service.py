"""
الهدف:
منطق العمل (Business Logic) الخاص بإدارة الإدارات (Departments) —
FR-UM-007 → FR-UM-010. يفصل قواعد العمل عن طبقة الـ API (routes) وعن
الوصول المباشر لقاعدة البيانات في نفس الوقت.

المسؤولية:
- إنشاء/عرض/تعديل/حذف (Soft Delete) الإدارات.
- تسجيل كل عملية تغيير في audit_logs عبر audit_service.
- إرجاع أخطاء عمل واضحة (ValueError) تُترجَم لاحقًا لأكواد HTTP مناسبة في
  طبقة الـ API.

ملاحظات:
- التحقق من الصلاحية (هل المستخدم الحالي super_admin؟) مسؤولية RBAC في
  core/dependencies.py، وليس هنا.
- الحذف Soft Delete فقط (FR-UM-010) — لا يوجد DELETE فعلي أبدًا.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.department import Department
from app.models.user import User
from app.services import audit_service


async def _assert_unique_name(db: AsyncSession, name: str, *, exclude_dep_id: uuid.UUID | None = None) -> None:
    stmt = select(Department).where(
        func.lower(Department.name) == name.lower(), Department.deleted_at.is_(None)
    )
    if exclude_dep_id is not None:
        stmt = stmt.where(Department.dep_id != exclude_dep_id)
    existing = await db.execute(stmt)
    if existing.scalar_one_or_none() is not None:
        raise ValueError("اسم الإدارة مستخدم مسبقًا")


async def _assert_unique_code(db: AsyncSession, code: str, *, exclude_dep_id: uuid.UUID | None = None) -> None:
    stmt = select(Department).where(
        func.lower(Department.code) == code.lower(), Department.deleted_at.is_(None)
    )
    if exclude_dep_id is not None:
        stmt = stmt.where(Department.dep_id != exclude_dep_id)
    existing = await db.execute(stmt)
    if existing.scalar_one_or_none() is not None:
        raise ValueError("الرمز التعريفي مستخدم مسبقًا لإدارة أخرى")


async def _get_active_manager(db: AsyncSession, manager_user_id: uuid.UUID) -> User:
    result = await db.execute(
        select(User).where(User.user_id == manager_user_id, User.deleted_at.is_(None))
    )
    manager = result.scalar_one_or_none()
    if manager is None:
        raise ValueError("المستخدم المحدَّد كمسؤول عن الإدارة غير موجود")
    return manager


async def create_department(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    name: str,
    code: str,
    description: str | None,
    manager_user_id: uuid.UUID,
) -> Department:
    """
    إنشاء إدارة جديدة. يرفع ValueError إذا كان الاسم أو الرمز التعريفي
    مستخدمًا لإدارة نشطة، أو إذا لم يوجد المستخدم المحدَّد كمسؤول.

    قرار عمل موثّق: المسؤول عن الإدارة يُضاف تلقائيًا كعضو في قائمة أعضاء
    هذه الإدارة (dep_id) عند إنشائها — حتى لو كان عضوًا في إدارة أخرى سابقًا
    (يُنقَل إليها).
    """
    await _assert_unique_name(db, name)
    await _assert_unique_code(db, code)
    manager = await _get_active_manager(db, manager_user_id)

    department = Department(name=name, code=code, description=description)
    db.add(department)
    await db.flush()  # للحصول على dep_id قبل تسجيل التدقيق وربط المسؤول

    department.manager_user_id = manager.user_id
    manager.dep_id = department.dep_id

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="create",
        target_type="department",
        target_id=department.dep_id,
        metadata={"name": name, "code": code, "manager_user_id": str(manager_user_id)},
    )

    await db.commit()
    await db.refresh(department)
    return department


async def list_departments(db: AsyncSession) -> list[Department]:
    """
    عرض كل الإدارات النشطة (غير المحذوفة).

    ملاحظة: هذا الـ endpoint بالكامل مقصور على super_admin (قرار موثّق) —
    بقية الأدوار يشوفون إدارتهم عبر بيانات حسابهم مباشرة (GET /users/me)،
    وليس عبر هذه الدالة، فلا حاجة لتصفية حسب dep_id هنا.
    """
    result = await db.execute(
        select(Department).where(Department.deleted_at.is_(None)).order_by(Department.name)
    )
    return list(result.scalars().all())


async def get_department(db: AsyncSession, dep_id: uuid.UUID) -> Department | None:
    """جلب إدارة واحدة (النشطة فقط) عبر معرّفها."""
    result = await db.execute(
        select(Department).where(Department.dep_id == dep_id, Department.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_department_detail(db: AsyncSession, dep_id: uuid.UUID) -> dict | None:
    """
    تفاصيل إدارة واحدة: بياناتها + عدد أعضائها + قائمة الأعضاء الكاملة
    (كل عضو مع دوره وحالته) — تُستخدم في صفحة "تفاصيل الإدارة".
    """
    department = await get_department(db, dep_id)
    if department is None:
        return None

    members_result = await db.execute(
        select(User)
        .options(selectinload(User.department).selectinload(Department.manager))
        .where(User.dep_id == dep_id, User.deleted_at.is_(None))
        .order_by(User.created_at.desc())
    )
    members = list(members_result.scalars().all())

    return {"department": department, "members": members, "member_count": len(members)}


async def update_department(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    dep_id: uuid.UUID,
    name: str | None,
    code: str | None,
    description: str | None,
    manager_user_id: uuid.UUID | None,
) -> Department | None:
    """
    تعديل بيانات إدارة موجودة. يرجع None إذا لم توجد.

    لو تغيّر manager_user_id، يُنقَل المسؤول الجديد تلقائيًا لعضوية هذه
    الإدارة (نفس سلوك الإنشاء) — تناسقًا مع القرار الموثّق في create_department.
    """
    department = await get_department(db, dep_id)
    if department is None:
        return None

    if name is not None:
        await _assert_unique_name(db, name, exclude_dep_id=dep_id)
    if code is not None:
        await _assert_unique_code(db, code, exclude_dep_id=dep_id)

    before = {
        "name": department.name,
        "code": department.code,
        "description": department.description,
        "manager_user_id": str(department.manager_user_id) if department.manager_user_id else None,
    }

    if name is not None:
        department.name = name
    if code is not None:
        department.code = code
    if description is not None:
        department.description = description
    if manager_user_id is not None and manager_user_id != department.manager_user_id:
        manager = await _get_active_manager(db, manager_user_id)
        department.manager_user_id = manager.user_id
        manager.dep_id = department.dep_id

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="update",
        target_type="department",
        target_id=department.dep_id,
        metadata={
            "before": before,
            "after": {
                "name": department.name,
                "code": department.code,
                "description": department.description,
                "manager_user_id": str(department.manager_user_id) if department.manager_user_id else None,
            },
        },
    )

    await db.commit()
    await db.refresh(department)
    return department


async def soft_delete_department(
    db: AsyncSession, *, actor_user_id: uuid.UUID, dep_id: uuid.UUID
) -> Department | None:
    """حذف إدارة (Soft Delete) — FR-UM-010. يرجع None إذا لم توجد أصلًا."""
    department = await get_department(db, dep_id)
    if department is None:
        return None

    department.deleted_at = func.now()

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="delete",
        target_type="department",
        target_id=department.dep_id,
        metadata={"name": department.name},
    )

    await db.commit()
    await db.refresh(department)
    return department
