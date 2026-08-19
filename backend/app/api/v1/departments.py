"""
الهدف:
راوتات إدارة الإدارات — FR-UM-007 → FR-UM-010.

قرار موثّق: كل عمليات هذا الراوتر (بما فيها العرض) مقصورة على super_admin
فقط. بقية الأدوار لا يستدعون أي endpoint من هذا الملف إطلاقًا — بياناتهم
عن إدارتهم (الاسم والوصف) تصلهم مضمَّنة مباشرة ضمن بياناتهم الشخصية عبر
GET /users/me (انظر app/schemas/user.py: UserOut.department)، بدل طلب
منفصل لصفحة الإدارات فقط لمعرفة اسم إدارتهم.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_roles
from app.db.session import get_db
from app.models.user import UserRole
from app.schemas.department import DepartmentCreate, DepartmentOut, DepartmentUpdate
from app.services import department_service

router = APIRouter(
    prefix="/departments",
    tags=["Departments"],
    dependencies=[Depends(require_roles(UserRole.super_admin))],
)


@router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
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
async def list_departments(db: AsyncSession = Depends(get_db)) -> list[DepartmentOut]:
    departments = await department_service.list_departments(db)
    return [DepartmentOut.model_validate(d) for d in departments]


@router.get("/{dep_id}", response_model=DepartmentOut)
async def get_department(dep_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> DepartmentOut:
    department = await department_service.get_department(db, dep_id)
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الإدارة غير موجودة")
    return DepartmentOut.model_validate(department)


@router.patch("/{dep_id}", response_model=DepartmentOut)
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


@router.delete("/{dep_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department(
    dep_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    department = await department_service.soft_delete_department(
        db, actor_user_id=current_user.user_id, dep_id=dep_id
    )
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الإدارة غير موجودة")
