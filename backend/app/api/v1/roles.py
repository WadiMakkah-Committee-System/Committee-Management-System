"""
الهدف:
راوتات "الأدوار والصلاحيات" — تسمح لـ super_admin بإنشاء دور جديد وتحديد
صلاحياته من الواجهة مباشرة (بدون أي تعديل على الكود أو قاعدة البيانات)،
واستعراض كتالوج الصلاحيات الكامل (9 أقسام) لعرضه كـ Checkboxes قابلة
للطي/الفتح.

قواعد الوصول:
كل عمليات هذا الراوتر مقصورة على super_admin حصرًا (require_super_admin)
— منح دور آخر صلاحية "إدارة الأدوار" يفتح ثغرة تصعيد صلاحيات، فتبقى هذه
الشاشة تحديدًا محصورة بالدور الجذري بغض النظر عن كتالوج الصلاحيات.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_super_admin
from app.db.session import get_db
from app.schemas.role import PermissionOut, RoleCreate, RoleDetailOut, RolePermissionOut, RoleUpdate
from app.services import role_service

router = APIRouter(
    prefix="/roles",
    tags=["Roles & Permissions"],
    dependencies=[Depends(require_super_admin)],
)

permissions_router = APIRouter(
    prefix="/permissions",
    tags=["Roles & Permissions"],
    dependencies=[Depends(require_super_admin)],
)


@permissions_router.get("", response_model=list[PermissionOut])
async def list_permissions(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[PermissionOut]:
    """
    كتالوج الصلاحيات الكامل مجمَّعًا حسب الأقسام التسعة الموثّقة — متاح لأي
    مستخدم لديه صلاحية roles.manage (super_admin حاليًا) لبناء واجهة
    Checkboxes عند إنشاء/تعديل دور.
    """
    permissions = await role_service.list_permissions(db)
    return [PermissionOut.model_validate(p) for p in permissions]


def _to_detail_out(entry: dict) -> RoleDetailOut:
    role = entry["role"]
    permissions = [
        RolePermissionOut(
            **PermissionOut.model_validate(link.permission).model_dump(),
            scope=link.scope,
        )
        for link in role.role_permission_links
    ]
    return RoleDetailOut(
        role_id=role.role_id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        is_super_admin=role.is_super_admin,
        created_at=role.created_at,
        updated_at=role.updated_at,
        permissions=permissions,
        permission_count=entry["permission_count"],
        user_count=entry["user_count"],
    )


@router.get("", response_model=list[RoleDetailOut])
async def list_roles(db: AsyncSession = Depends(get_db)) -> list[RoleDetailOut]:
    entries = await role_service.list_roles(db)
    return [_to_detail_out(e) for e in entries]


@router.post("", response_model=RoleDetailOut, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: RoleCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> RoleDetailOut:
    try:
        role = await role_service.create_role(
            db,
            actor_user_id=current_user.user_id,
            name=payload.name,
            description=payload.description,
            permission_codes=payload.permission_codes,
            permission_scopes=payload.permission_scopes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    entry = await role_service.get_role_detail(db, role.role_id)
    return _to_detail_out(entry)  # type: ignore[arg-type]


@router.get("/{role_id}", response_model=RoleDetailOut)
async def get_role(role_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> RoleDetailOut:
    entry = await role_service.get_role_detail(db, role_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الدور غير موجود")
    return _to_detail_out(entry)


@router.patch("/{role_id}", response_model=RoleDetailOut)
async def update_role(
    role_id: uuid.UUID,
    payload: RoleUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> RoleDetailOut:
    try:
        role = await role_service.update_role(
            db,
            actor_user_id=current_user.user_id,
            role_id=role_id,
            name=payload.name,
            description=payload.description,
            permission_codes=payload.permission_codes,
            permission_scopes=payload.permission_scopes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الدور غير موجود")
    entry = await role_service.get_role_detail(db, role.role_id)
    return _to_detail_out(entry)  # type: ignore[arg-type]


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    try:
        role = await role_service.delete_role(db, actor_user_id=current_user.user_id, role_id=role_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الدور غير موجود")
