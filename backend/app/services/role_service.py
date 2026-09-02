"""
الهدف:
منطق العمل الخاص بإدارة الأدوار والصلاحيات (Roles & Permissions) — يسمح
لـ super_admin بإنشاء دور جديد وتحديد صلاحياته بالكامل من الواجهة، دون أي
حاجة للمس الكود أو قاعدة البيانات.

المسؤولية:
- إنشاء/عرض/تعديل/حذف الأدوار.
- ربط دور بمجموعة صلاحيات (عبر أكوادها code) من كتالوج permissions، مع
  نطاق وصول (scope) مستقل لكل صلاحية ممنوحة (own/department/all).
- منع حذف أي دور (نظاميًا كان أم لا) لا يزال مستخدَمًا من قِبل مستخدم
  واحد على الأقل — هذه هي الحماية الوحيدة المتبقية على الحذف؛ لا يوجد
  أي استثناء أو حماية أخرى مرتبطة بـ is_system بعد الآن (قرار عمل موثّق).

مراجعة لاما 2026-08-30: role_permissions صار Association Object
(RolePermission) بدل جدول ربط بسيط — Role.permissions لم تعد قابلة
للإسناد المباشر (role.permissions = [...]) لأنها Property للقراءة
فقط الآن. _sync_role_permissions أدناه هي الطريقة الوحيدة الصحيحة
لتعديل صلاحيات دور (تدير role_permission_links صفًا بصف مع نطاقه).
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.role import VALID_SCOPES, Permission, Role, RolePermission
from app.models.user import User
from app.services import audit_service


async def list_permissions(db: AsyncSession) -> list[Permission]:
    """كتالوج الصلاحيات الكامل (كل الأقسام التسعة) — لعرضه كـ Checkboxes."""
    result = await db.execute(select(Permission).order_by(Permission.sort_order))
    return list(result.scalars().all())


async def _permissions_by_codes(db: AsyncSession, codes: list[str]) -> list[Permission]:
    if not codes:
        return []
    result = await db.execute(select(Permission).where(Permission.code.in_(codes)))
    found = list(result.scalars().all())
    found_codes = {p.code for p in found}
    unknown = set(codes) - found_codes
    if unknown:
        raise ValueError(f"صلاحيات غير معروفة: {', '.join(sorted(unknown))}")
    return found


async def _sync_role_permissions(
    db: AsyncSession,
    role: Role,
    permission_codes: list[str],
    permission_scopes: dict[str, str] | None = None,
) -> None:
    """
    تزامن صلاحيات دور مع قائمة أكواد جديدة — بديل عن role.permissions =
    [...] (لم يعد ممكنًا؛ راجعي docstring أعلى الملف وmodels/role.py).

    - يضيف RolePermission جديدة لأي كود لم يكن ممنوحًا سابقًا.
    - يحذف الروابط لأي كود لم يعد ضمن permission_codes.
    - يحدّث scope لأي كود باقٍ إذا مُرِّر له نطاق جديد في permission_scopes.
    - أي كود لم يُذكر له نطاق في permission_scopes يأخذ 'all' افتراضيًا
      (نفس فلسفة "الافتراضي = السلوك الحالي غير المقيَّد" المتّبعة بـ
      migration 0014).

    يرفع ValueError إذا كان أحد الأكواد غير موجود بالكتالوج، أو إذا مُرِّر
    نطاق غير معروف (خارج VALID_SCOPES).
    """
    scopes = permission_scopes or {}
    permissions = await _permissions_by_codes(db, permission_codes)
    permissions_by_code = {p.code: p for p in permissions}

    existing_links = {link.permission.code: link for link in role.role_permission_links}

    for code, link in list(existing_links.items()):
        if code not in permissions_by_code:
            role.role_permission_links.remove(link)

    for code, permission in permissions_by_code.items():
        scope = scopes.get(code, "all")
        if scope not in VALID_SCOPES:
            raise ValueError(f"نطاق وصول غير معروف: {scope}")
        if code in existing_links:
            existing_links[code].scope = scope
        else:
            role.role_permission_links.append(
                RolePermission(permission_id=permission.permission_id, scope=scope)
            )


async def list_roles(db: AsyncSession) -> list[dict]:
    """
    قائمة الأدوار مع عدد الصلاحيات وعدد المستخدمين المرتبطين بكل دور —
    تُستخدم في تبويب "الأدوار والصلاحيات".
    """
    result = await db.execute(
        select(Role).options(
            selectinload(Role.role_permission_links).selectinload(RolePermission.permission)
        )
    )
    roles = list(result.scalars().all())

    counts_result = await db.execute(
        select(User.role_id, func.count())
        .where(User.deleted_at.is_(None))
        .group_by(User.role_id)
    )
    user_counts = dict(counts_result.all())

    return [
        {
            "role": role,
            "permission_count": len(role.permissions),
            "user_count": user_counts.get(role.role_id, 0),
        }
        for role in roles
    ]


async def get_role(db: AsyncSession, role_id: uuid.UUID) -> Role | None:
    result = await db.execute(
        select(Role)
        .options(selectinload(Role.role_permission_links).selectinload(RolePermission.permission))
        .where(Role.role_id == role_id)
    )
    return result.scalar_one_or_none()


async def get_role_detail(db: AsyncSession, role_id: uuid.UUID) -> dict | None:
    role = await get_role(db, role_id)
    if role is None:
        return None
    count_result = await db.execute(
        select(func.count())
        .select_from(User)
        .where(User.role_id == role_id, User.deleted_at.is_(None))
    )
    return {
        "role": role,
        "permission_count": len(role.permissions),
        "user_count": count_result.scalar_one(),
    }


async def create_role(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    name: str,
    description: str | None,
    permission_codes: list[str],
    permission_scopes: dict[str, str] | None = None,
) -> Role:
    """
    إنشاء دور جديد. يرفع ValueError إذا الاسم مستخدم أو أحد الصلاحيات غير
    موجود أو نطاق وصول غير معروف.

    permission_scopes اختياري ({كود_الصلاحية: نطاقها}) — أي كود لم يُذكر
    فيه يأخذ 'all' افتراضيًا (راجعي _sync_role_permissions).
    """
    existing = await db.execute(select(Role).where(func.lower(Role.name) == name.lower()))
    if existing.scalar_one_or_none() is not None:
        raise ValueError("اسم الدور مستخدم مسبقًا")

    if not permission_codes:
        raise ValueError("يجب تحديد صلاحية واحدة على الأقل عند إنشاء الدور")

    role = Role(name=name, description=description, is_system=False, is_super_admin=False)
    db.add(role)
    await _sync_role_permissions(db, role, permission_codes, permission_scopes)
    await db.flush()

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="create",
        target_type="role",
        target_id=role.role_id,
        metadata={"name": name, "permission_count": len(permission_codes)},
    )

    await db.commit()
    return await get_role(db, role.role_id)  # type: ignore[return-value]


async def update_role(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    role_id: uuid.UUID,
    name: str | None,
    description: str | None,
    permission_codes: list[str] | None,
    permission_scopes: dict[str, str] | None = None,
) -> Role | None:
    """
    تعديل دور موجود. قرار عمل موثّق: فُكّت الحماية بالكامل عن الأدوار
    النظامية الخمسة (is_system) — يمكن تعديل اسمها ووصفها وصلاحياتها
    بحرية، تمامًا مثل أي دور آخر. الحماية الوحيدة المتبقية هي حارس
    user_count > 0 عند الحذف (أسفل)، وغير مرتبطة بـ is_system إطلاقًا.
    """
    role = await get_role(db, role_id)
    if role is None:
        return None

    if name is not None and name.strip().lower() != role.name.lower():
        duplicate = await db.execute(
            select(Role).where(func.lower(Role.name) == name.lower(), Role.role_id != role_id)
        )
        if duplicate.scalar_one_or_none() is not None:
            raise ValueError("اسم الدور مستخدم مسبقًا")
        role.name = name

    if description is not None:
        role.description = description

    if permission_codes is not None:
        if not permission_codes:
            raise ValueError("يجب أن يحتفظ الدور بصلاحية واحدة على الأقل")
        await _sync_role_permissions(db, role, permission_codes, permission_scopes)

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="update",
        target_type="role",
        target_id=role.role_id,
        metadata={"name": role.name},
    )

    await db.commit()
    return await get_role(db, role.role_id)


async def delete_role(db: AsyncSession, *, actor_user_id: uuid.UUID, role_id: uuid.UUID) -> Role | None:
    """
    حذف دور. قرار عمل موثّق: لا يوجد أي استثناء للأدوار النظامية بعد
    الآن — الحماية الوحيدة هي عدم وجود مستخدمين مرتبطين بالدور (سواء كان
    is_system أم لا). يرفع ValueError إذا كان لا يزال هناك مستخدم واحد
    على الأقل مرتبط به.
    """
    role = await get_role(db, role_id)
    if role is None:
        return None

    # حماية جديدة (مراجعة لاما 2026-08-31): "رئيس اللجنة"/"عضو اللجنة"
    # دوران ثابتان بنيويًا — عضوية أي لجنة (committee_members.committee_role_id)
    # تشير إليهما مباشرة (NOT NULL)، فحذفهما يكسر كل عضويات اللجان القائمة.
    # is_system لا يمنع الحذف (قرار سابق موثّق)، لذا الحماية هنا صريحة على
    # kind='committee' تحديدًا، وليس على is_system.
    if role.kind == "committee":
        raise ValueError("لا يمكن حذف أدوار اللجان الثابتة (رئيس اللجنة/عضو اللجنة)")

    count_result = await db.execute(
        select(func.count())
        .select_from(User)
        .where(User.role_id == role_id, User.deleted_at.is_(None))
    )
    if count_result.scalar_one() > 0:
        raise ValueError("لا يمكن حذف هذا الدور — لا يزال هناك مستخدمون مرتبطون به")

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="delete",
        target_type="role",
        target_id=role.role_id,
        metadata={"name": role.name},
    )

    await db.delete(role)
    await db.commit()
    return role
