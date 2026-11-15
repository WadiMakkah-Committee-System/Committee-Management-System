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
- هيكل المستويين (migration 0048 — قرار لاما 2026-11-15): إدارة أم وتحتها
  إدارات تابعة. القواعد مفروضة بـtrigger في القاعدة، وتُفحص هنا مسبقًا
  برسائل عمل واضحة (راجعي _resolve_parent و_has_active_children).
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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


#: قيمة افتراضية تميّز "لم يُرسَل parent_dep_id" عن "أُرسل None" (فكّ الربط)
#: بـupdate_department.
UNSET: object = object()


async def _resolve_parent(
    db: AsyncSession, parent_dep_id: uuid.UUID, *, dep_id: uuid.UUID | None = None
) -> Department:
    """
    الهدف:
    التحقق من أن إدارة يمكن أن تكون "إدارة أم" قبل ربط إدارة تابعة بها.

    المدخلات:
    - parent_dep_id: معرّف الإدارة الأم المطلوبة.
    - dep_id: معرّف الإدارة اللي تُربط (عند التعديل) — لمنع ربطها بنفسها.

    المخرجات: الإدارة الأم (Department).

    قواعد العمل (migration 0048):
    - الإدارة الأم موجودة وغير محذوفة.
    - الإدارة الأم نفسها بلا أم (الهيكل مستويان فقط).
    - الإدارة لا تكون أمًّا لنفسها.

    الأخطاء: ValueError برسالة عربية لأي مخالفة. بلا تأثيرات جانبية.
    """
    if dep_id is not None and parent_dep_id == dep_id:
        raise ValueError("لا يمكن أن تكون الإدارة تابعة لنفسها")
    parent = await get_department(db, parent_dep_id)
    if parent is None:
        raise ValueError("الإدارة الأم غير موجودة")
    if parent.parent_dep_id is not None:
        raise ValueError("لا يمكن إضافة إدارة تحت إدارة تابعة — الهيكل مستويان فقط")
    return parent


async def _has_active_children(db: AsyncSession, dep_id: uuid.UUID) -> bool:
    """هل تحت هذه الإدارة إدارات تابعة نشطة (غير محذوفة)؟ — قراءة فقط."""
    result = await db.execute(
        select(Department.dep_id)
        .where(Department.parent_dep_id == dep_id, Department.deleted_at.is_(None))
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _flush_hierarchy(db: AsyncSession) -> None:
    """
    flush مع ترجمة رفض trigger الهيكل (enforce_department_hierarchy) لخطأ عمل.
    يحصل فقط بسباق نادر (تعديلان متزامنان على نفس الهيكل) لأن الخدمة تفحص
    القواعد مسبقًا. الأخطاء: ValueError بعد rollback.
    """
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError("تعذّر حفظ هيكل الإدارات بسبب تعديل متزامن — حدّثي الصفحة وحاولي مرة أخرى") from exc


async def _get_active_manager(db: AsyncSession, manager_user_id: uuid.UUID) -> User:
    result = await db.execute(
        select(User).where(User.user_id == manager_user_id, User.deleted_at.is_(None))
    )
    manager = result.scalar_one_or_none()
    if manager is None:
        raise ValueError("المستخدم المحدَّد كمسؤول عن الإدارة غير موجود")
    return manager


async def _get_active_members(db: AsyncSession, member_user_ids: list[uuid.UUID]) -> list[User]:
    """
    الهدف: جلب أعضاء الإدارة المحدَّدين بنموذج الإنشاء والتحقق من وجودهم.

    المدخلات: قائمة معرّفات (قد تكون فارغة).
    المخرجات: المستخدمون النشطون (غير المحذوفين) بنفس ترتيب الإدخال.
    الأخطاء: ValueError لو أي معرّف غير موجود أو محذوف.
    بلا تأثيرات جانبية (قراءة فقط).
    """
    if not member_user_ids:
        return []
    result = await db.execute(
        select(User).where(User.user_id.in_(member_user_ids), User.deleted_at.is_(None))
    )
    found = {u.user_id: u for u in result.scalars().all()}
    if len(found) != len(set(member_user_ids)):
        raise ValueError("بعض الأعضاء المحدَّدين غير موجودين أو محذوفين")
    return [found[uid] for uid in member_user_ids]


async def create_department(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    name: str,
    code: str,
    description: str | None,
    manager_user_id: uuid.UUID,
    member_user_ids: list[uuid.UUID] | None = None,
    parent_dep_id: uuid.UUID | None = None,
) -> Department:
    """
    إنشاء إدارة جديدة. يرفع ValueError إذا كان الاسم أو الرمز التعريفي
    مستخدمًا لإدارة نشطة، أو إذا لم يوجد المستخدم المحدَّد كمسؤول.

    قرار عمل موثّق: المسؤول عن الإدارة يُضاف تلقائيًا كعضو في قائمة أعضاء
    هذه الإدارة (dep_id) عند إنشائها — حتى لو كان عضوًا في إدارة أخرى سابقًا
    (يُنقَل إليها).

    member_user_ids (طلب صاحبة المشروع 2026-10-29): أعضاء إضافيون يُضافون
    للإدارة بنفس المعاملة وبنفس قاعدة المسؤول — من كان بإدارة أخرى يُنقَل.
    كل شيء بمعاملة واحدة: لو فشل أي عضو، لا تُنشأ الإدارة أصلًا. التحقق من
    صلاحية نقل المستخدمين على مستوى الـAPI (create_department بـdepartments.py).

    parent_dep_id (migration 0048): اختياري — يجعل الإدارة الجديدة تابعة
    لإدارة أم (راجعي _resolve_parent لقواعدها). None = إدارة بالمستوى الأعلى.
    """
    if parent_dep_id is not None:
        await _resolve_parent(db, parent_dep_id)
    await _assert_unique_name(db, name)
    await _assert_unique_code(db, code)
    manager = await _get_active_manager(db, manager_user_id)
    # المسؤول عضو تلقائيًا — يُستبعد من القائمة لو أُرسل ضمنها أيضًا.
    members = [
        m
        for m in await _get_active_members(db, list(member_user_ids or []))
        if m.user_id != manager.user_id
    ]

    department = Department(
        name=name, code=code, description=description, parent_dep_id=parent_dep_id
    )
    db.add(department)
    await _flush_hierarchy(db)  # للحصول على dep_id قبل تسجيل التدقيق وربط المسؤول

    department.manager_user_id = manager.user_id
    manager.dep_id = department.dep_id
    moved_from = {str(m.user_id): (str(m.dep_id) if m.dep_id else None) for m in members}
    for member in members:
        member.dep_id = department.dep_id

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="create",
        target_type="department",
        target_id=department.dep_id,
        metadata={
            "name": name,
            "code": code,
            "manager_user_id": str(manager_user_id),
            "parent_dep_id": str(parent_dep_id) if parent_dep_id else None,
            # العضو → إدارته السابقة (None لمن كان بلا إدارة) — لتتبّع النقل.
            "members_moved_from": moved_from,
        },
    )

    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    await db.refresh(department)
    await db.commit()
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

    # هيكل المستويين (migration 0048): الإدارة الأم (لو كانت تابعة) والإدارات
    # التابعة لها (لو كانت أمًّا) مع عدد أعضاء كل وحدة — استعلامان صغيران.
    parent = (
        await get_department(db, department.parent_dep_id)
        if department.parent_dep_id is not None
        else None
    )
    member_count = (
        select(func.count(User.user_id))
        .where(User.dep_id == Department.dep_id, User.deleted_at.is_(None))
        .correlate(Department)
        .scalar_subquery()
    )
    children_result = await db.execute(
        select(Department, member_count)
        .where(Department.parent_dep_id == dep_id, Department.deleted_at.is_(None))
        .order_by(Department.name)
    )
    children = [
        {"department": child, "member_count": count} for child, count in children_result.all()
    ]

    return {
        "department": department,
        "members": members,
        "member_count": len(members),
        "parent": parent,
        "children": children,
    }


async def update_department(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    dep_id: uuid.UUID,
    name: str | None,
    code: str | None,
    description: str | None,
    manager_user_id: uuid.UUID | None,
    parent_dep_id: uuid.UUID | None | object = UNSET,
) -> Department | None:
    """
    تعديل بيانات إدارة موجودة. يرجع None إذا لم توجد.

    parent_dep_id (migration 0048): UNSET = بلا تغيير، None = فكّها من إدارتها
    الأم (تصير بالمستوى الأعلى)، معرّف = نقلها تحت تلك الإدارة الأم. إدارة
    تحتها إدارات تابعة لا يمكن جعلها تابعة (الهيكل مستويان فقط).

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
    parent_changed = parent_dep_id is not UNSET and parent_dep_id != department.parent_dep_id
    if parent_changed and parent_dep_id is not None:
        await _resolve_parent(db, parent_dep_id, dep_id=dep_id)  # type: ignore[arg-type]
        if await _has_active_children(db, dep_id):
            raise ValueError("لا يمكن جعل هذه الإدارة تابعة لأن تحتها إدارات تابعة")

    before = {
        "name": department.name,
        "code": department.code,
        "description": department.description,
        "manager_user_id": str(department.manager_user_id) if department.manager_user_id else None,
        "parent_dep_id": str(department.parent_dep_id) if department.parent_dep_id else None,
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
    if parent_changed:
        department.parent_dep_id = parent_dep_id  # type: ignore[assignment]
    await _flush_hierarchy(db)

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
                "parent_dep_id": str(department.parent_dep_id) if department.parent_dep_id else None,
            },
        },
    )

    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    await db.refresh(department)
    await db.commit()
    return department


async def soft_delete_department(
    db: AsyncSession, *, actor_user_id: uuid.UUID, dep_id: uuid.UUID
) -> Department | None:
    """
    حذف إدارة (Soft Delete) — FR-UM-010. يرجع None إذا لم توجد أصلًا.

    migration 0048: إدارة تحتها إدارات تابعة نشطة لا تُحذف (ValueError) —
    تُحذف أو تُنقل الإدارات التابعة أولًا، حتى لا تبقى إدارات معلّقة بأم محذوفة.
    """
    department = await get_department(db, dep_id)
    if department is None:
        return None
    if await _has_active_children(db, dep_id):
        raise ValueError("لا يمكن حذف إدارة تحتها إدارات تابعة — احذفي أو انقلي الإدارات التابعة أولًا")

    department.deleted_at = func.now()
    await _flush_hierarchy(db)

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="delete",
        target_type="department",
        target_id=department.dep_id,
        metadata={"name": department.name},
    )

    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    await db.refresh(department)
    await db.commit()
    return department
