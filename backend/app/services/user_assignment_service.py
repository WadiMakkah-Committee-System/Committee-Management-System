"""
الهدف:
كتابة تعيينات المستخدم (إدارة + دور) — جدول user_department_roles
(migration 0052: مستخدم في أكثر من إدارة، بدور مختلف في كل إدارة).

المسؤولية:
- normalize_assignments(): توحيد قائمة التعيينات القادمة من الطلب.
- replace_assignments(): استبدال تعيينات مستخدم بالكامل.
- attach_to_department(): ربط مستخدم بإدارة من صفحة الإدارات مع نقل تعيينات الإدارة
  القديمة للجديدة (يحفظ سلوك "نقل مستخدم لإدارة" لمستخدم الإدارة الواحدة).
- sync_roles_to_primary(): المسار القديم (role_ids + dep_id بلا تعيينات) —
  كل دور على الإدارة الأساسية.

ملاحظات:
- لا commit هنا — الاستدعاء دائمًا ضمن معاملة الخدمة المستدعية.
- لا تحقق صلاحيات هنا (طبقة الـAPI مسؤولة عن النطاق).
- الدور لازم يكون مسندًا للمستخدم بـuser_roles قبل تعيينه على إدارة
  (قيد user_department_roles_role_assigned_fkey)، فالمستدعي يكتب user_roles
  أولًا ثم يستدعي هذه الدوال، بنفس المعاملة وبعد flush.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.user_department_role import UserDepartmentRole
from app.models.user_role import UserRole


@dataclass(frozen=True)
class Assignment:
    """تعيين واحد: دور على إدارة (dep_id = None ⇒ دور بلا إدارة محددة)."""

    role_id: uuid.UUID
    dep_id: uuid.UUID | None


def normalize_assignments(assignments: list[Assignment]) -> list[Assignment]:
    """
    الهدف: إزالة التكرار مع حفظ الترتيب. لو للدور تعيين على إدارة، يُتجاهل
    تعيينه "بلا إدارة" (لأن الدور بلا صفوف يعني الإدارة الأساسية، والدور
    بصفوف يعني إداراته المحددة فقط — لا يجتمعان).
    """
    unique = list(dict.fromkeys(assignments))
    roles_with_dep = {a.role_id for a in unique if a.dep_id is not None}
    return [a for a in unique if a.dep_id is not None or a.role_id not in roles_with_dep]


def role_ids_of(assignments: list[Assignment]) -> list[uuid.UUID]:
    """أدوار التعيينات بلا تكرار وبنفس الترتيب (أول دور = الدور الحالي الافتراضي)."""
    return list(dict.fromkeys(a.role_id for a in assignments))


def department_ids_of(assignments: list[Assignment]) -> list[uuid.UUID]:
    return list(dict.fromkeys(a.dep_id for a in assignments if a.dep_id is not None))


async def validate_departments(db: AsyncSession, dep_ids: list[uuid.UUID]) -> None:
    """ValueError لو إدارة غير موجودة أو محذوفة."""
    if not dep_ids:
        return
    result = await db.execute(
        select(Department.dep_id).where(Department.dep_id.in_(dep_ids), Department.deleted_at.is_(None))
    )
    if len(set(result.scalars().all())) != len(set(dep_ids)):
        raise ValueError("إحدى الإدارات المحددة غير موجودة")


async def load_assignments(db: AsyncSession, user_id: uuid.UUID) -> list[Assignment]:
    """
    تعيينات المستخدم الحالية بالشكل الكامل: صف لكل (دور، إدارة)، وأدواره
    المسندة بلا أي إدارة تظهر بـdep_id = None. استعلامان صغيران.
    """
    rows = (
        await db.execute(
            select(UserDepartmentRole.role_id, UserDepartmentRole.dep_id)
            .where(UserDepartmentRole.user_id == user_id)
            .order_by(UserDepartmentRole.created_at, UserDepartmentRole.dep_id)
        )
    ).all()
    roles = (
        await db.execute(
            select(UserRole.role_id).where(UserRole.user_id == user_id).order_by(UserRole.created_at)
        )
    ).scalars().all()
    result = [Assignment(r.role_id, r.dep_id) for r in rows]
    with_dep = {a.role_id for a in result}
    result += [Assignment(rid, None) for rid in roles if rid not in with_dep]
    return result


async def replace_assignments(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    assignments: list[Assignment],
    actor_user_id: uuid.UUID | None,
) -> None:
    """
    الهدف: استبدال صفوف user_department_roles للمستخدم بالتعيينات المعطاة
    (التعيينات بلا إدارة لا تُكتب صفًا — الدور مسند بـuser_roles فقط).
    المتطلبات: أدوار التعيينات مسندة فعلًا بـuser_roles ضمن نفس المعاملة.
    """
    await db.execute(delete(UserDepartmentRole).where(UserDepartmentRole.user_id == user_id))
    db.add_all(
        [
            UserDepartmentRole(user_id=user_id, role_id=a.role_id, dep_id=a.dep_id, assigned_by=actor_user_id)
            for a in assignments
            if a.dep_id is not None
        ]
    )


async def sync_roles_to_primary(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    role_ids: list[uuid.UUID],
    dep_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
) -> None:
    """
    المسار القديم (بلا تعيينات صريحة): كل دور على الإدارة الأساسية — نفس
    معنى "دور + إدارة واحدة" قبل migration 0052. يستبدل كل التعيينات.
    """
    await replace_assignments(
        db,
        user_id=user_id,
        assignments=[Assignment(rid, dep_id) for rid in role_ids],
        actor_user_id=actor_user_id,
    )


async def attach_to_department(db: AsyncSession, *, user, new_dep_id: uuid.UUID) -> bool:
    """
    الهدف:
    ربط مستخدم بإدارة من صفحة الإدارات (تعيين مدير، إضافة عضو) — السلوك
    القديم "نقل المستخدم للإدارة" يبقى لمستخدم الإدارة الواحدة، بدون كسر
    مستخدم متعدد الإدارات.

    المدخلات: user (كائن User محمَّل بنفس الجلسة)، new_dep_id.

    المخرجات: True لو صار المستخدم عضوًا بالإدارة (أو كان أصلًا)، False لو
    المستخدم متعدد الإدارات وليس عضوًا بها — لا يُنقل تلقائيًا (نقله يمسح
    معنى تعييناته)، وتعديل إداراته يكون من صفحة المستخدم.

    التأثيرات الجانبية (مستخدم الإدارة الواحدة فقط): user.dep_id = new_dep_id،
    وتعييناته على إدارته القديمة تنتقل للجديدة (فنطاق أدواره يتبعه كما كان).
    """
    old_dep_id = user.dep_id
    if old_dep_id == new_dep_id:
        return True
    row_deps = set(
        (
            await db.execute(
                select(UserDepartmentRole.dep_id).where(UserDepartmentRole.user_id == user.user_id)
            )
        ).scalars()
    )
    if row_deps - {old_dep_id}:
        return new_dep_id in row_deps
    if old_dep_id is not None:
        await db.execute(
            update(UserDepartmentRole)
            .where(UserDepartmentRole.user_id == user.user_id, UserDepartmentRole.dep_id == old_dep_id)
            .values(dep_id=new_dep_id)
        )
    else:
        # بلا إدارة سابقًا: أدواره (نطاقها كان على "لا إدارة") تصير على إدارته الجديدة.
        role_ids = (await db.execute(select(UserRole.role_id).where(UserRole.user_id == user.user_id))).scalars().all()
        db.add_all([UserDepartmentRole(user_id=user.user_id, role_id=rid, dep_id=new_dep_id) for rid in role_ids])
    user.dep_id = new_dep_id
    return True
