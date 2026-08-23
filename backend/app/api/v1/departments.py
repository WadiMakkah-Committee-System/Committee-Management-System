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

from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.schemas.department import DepartmentCreate, DepartmentDetailOut, DepartmentOut, DepartmentUpdate
from app.schemas.user import UserOut
from app.services import department_service

router = APIRouter(prefix="/departments", tags=["Departments"])


@router.post(
    "",
    response_model=DepartmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("departments.create"))],
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


@router.get(
    "",
    response_model=list[DepartmentOut],
    dependencies=[Depends(require_permission("departments.view"))],
)
async def list_departments(db: AsyncSession = Depends(get_db)) -> list[DepartmentOut]:
    departments = await department_service.list_departments(db)
    return [DepartmentOut.model_validate(d) for d in departments]


@router.get(
    "/{dep_id}",
    response_model=DepartmentDetailOut,
    dependencies=[Depends(require_permission("departments.view"))],
)
async def get_department(dep_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> DepartmentDetailOut:
    """
    تفاصيل إدارة واحدة — الاسم، الوصف، عدد الأعضاء، وقائمة الأعضاء كاملة
    (كل عضو مع دوره وحالة حسابه)، لصفحة "تفاصيل الإدارة".
    """
    detail = await department_service.get_department_detail(db, dep_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الإدارة غير موجودة")
    department = detail["department"]
    return DepartmentDetailOut(
        dep_id=department.dep_id,
        name=department.name,
        description=department.description,
        created_at=department.created_at,
        updated_at=department.updated_at,
        member_count=detail["member_count"],
        members=[UserOut.model_validate(u) for u in detail["members"]],
    )


@router.patch(
    "/{dep_id}",
    response_model=DepartmentOut,
    dependencies=[Depends(require_permission("departments.update"))],
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
    dependencies=[Depends(require_permission("departments.delete"))],
)
async def delete_department(
    dep_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    department = await department_service.soft_delete_department(
        db, actor_user_id=current_user.user_id, dep_id=dep_id
    )
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الإدارة غير موجودة")
