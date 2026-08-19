"""
الهدف:
راوتات إدارة الإدارات — FR-UM-007 → FR-UM-010.

قواعد العرض (قرار موثّق):
- super_admin: يشوف كل الإدارات (قائمة كاملة + أي إدارة عبر معرّفها).
- بقية الأدوار: يشوفون إدارتهم فقط (حسب dep_id الخاص بهم) — سواء في القائمة
  أو عند طلب إدارة بعينها؛ محاولة عرض إدارة أخرى تُرفض بـ 403.
- الإنشاء/التعديل/الحذف مقصورة على super_admin فقط، بلا استثناء.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_roles
from app.db.session import get_db
from app.models.user import UserRole
from app.schemas.department import DepartmentCreate, DepartmentOut, DepartmentUpdate
from app.services import department_service

router = APIRouter(prefix="/departments", tags=["Departments"])


@router.post(
    "",
    response_model=DepartmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(UserRole.super_admin))],
)
async def create_department(
    payload: DepartmentCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> DepartmentOut:
    try:
        department = await department_service.create_department(
            db,
            actor_user_id=current_user.user_id,
            name=payload.name,
            description=payload.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DepartmentOut.model_validate(department)


@router.get("", response_model=list[DepartmentOut])
async def list_departments(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[DepartmentOut]:
    """
    super_admin يشوف كل الإدارات. بقية الأدوار يشوفون إدارتهم فقط — إذا لم
    يكن لدى المستخدم إدارة (dep_id فارغ)، تُرجع قائمة فارغة بدل خطأ.
    """
    if current_user.role == UserRole.super_admin:
        departments = await department_service.list_departments(db)
    elif current_user.dep_id is not None:
        departments = await department_service.list_departments(db, dep_id=current_user.dep_id)
    else:
        departments = []
    return [DepartmentOut.model_validate(d) for d in departments]


@router.get("/{dep_id}", response_model=DepartmentOut)
async def get_department(
    dep_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> DepartmentOut:
    """super_admin يقدر يعرض أي إدارة. بقية الأدوار يقدرون يعرضون إدارتهم فقط."""
    if current_user.role != UserRole.super_admin and current_user.dep_id != dep_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="لا تملك صلاحية عرض هذه الإدارة"
        )

    department = await department_service.get_department(db, dep_id)
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الإدارة غير موجودة")
    return DepartmentOut.model_validate(department)


@router.patch(
    "/{dep_id}",
    response_model=DepartmentOut,
    dependencies=[Depends(require_roles(UserRole.super_admin))],
)
async def update_department(
    dep_id: uuid.UUID,
    payload: DepartmentUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DepartmentOut:
    department = await department_service.update_department(
        db,
        actor_user_id=current_user.user_id,
        dep_id=dep_id,
        name=payload.name,
        description=payload.description,
    )
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الإدارة غير موجودة")
    return DepartmentOut.model_validate(department)


@router.delete(
    "/{dep_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_roles(UserRole.super_admin))],
)
async def delete_department(
    dep_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    department = await department_service.soft_delete_department(
        db, actor_user_id=current_user.user_id, dep_id=dep_id
    )
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الإدارة غير موجودة")
