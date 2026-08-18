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

from app.models.department import Department
from app.services import audit_service


async def create_department(
    db: AsyncSession, *, actor_user_id: uuid.UUID, name: str, description: str | None
) -> Department:
    """إنشاء إدارة جديدة. يرفع ValueError إذا كان الاسم مستخدمًا لإدارة نشطة."""
    existing = await db.execute(
        select(Department).where(
            func.lower(Department.name) == name.lower(), Department.deleted_at.is_(None)
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError("اسم الإدارة مستخدم مسبقًا")

    department = Department(name=name, description=description)
    db.add(department)
    await db.flush()  # للحصول على dep_id قبل تسجيل التدقيق

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="create",
        target_type="department",
        target_id=department.dep_id,
        metadata={"name": name},
    )

    await db.commit()
    await db.refresh(department)
    return department


async def list_departments(db: AsyncSession) -> list[Department]:
    """عرض كل الإدارات النشطة (غير المحذوفة)."""
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


async def update_department(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    dep_id: uuid.UUID,
    name: str | None,
    description: str | None,
) -> Department | None:
    """تعديل بيانات إدارة موجودة. يرجع None إذا لم توجد."""
    department = await get_department(db, dep_id)
    if department is None:
        return None

    before = {"name": department.name, "description": department.description}

    if name is not None:
        department.name = name
    if description is not None:
        department.description = description

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="update",
        target_type="department",
        target_id=department.dep_id,
        metadata={"before": before, "after": {"name": department.name, "description": department.description}},
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
