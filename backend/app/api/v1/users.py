"""
الهدف:
راوتات إدارة المستخدمين — FR-UM-001 → FR-UM-006, FR-UM-021 → FR-UM-022.
مقصورة بالكامل على super_admin حسب القاعدة الموثّقة في ERD ("السوبر هو
اللي يضيف الأعضاء لإدارته").

المسؤولية:
تحويل طلبات HTTP لاستدعاءات user_service، وفرض RBAC عبر
core.dependencies.require_roles على مستوى كل راوت.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_roles
from app.db.session import get_db
from app.models.user import UserRole, UserStatus
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services import user_service

router = APIRouter(
    prefix="/users",
    tags=["Users"],
    dependencies=[Depends(require_roles(UserRole.super_admin))],
)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UserOut:
    try:
        user = await user_service.create_user(
            db,
            actor_user_id=current_user.user_id,
            first_name=payload.first_name,
            middle_name=payload.middle_name,
            last_name=payload.last_name,
            username=payload.username,
            email=payload.email,
            password=payload.password,
            role=payload.role,
            dep_id=payload.dep_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UserOut.model_validate(user)


@router.get("", response_model=list[UserOut])
async def list_users(
    dep_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)
) -> list[UserOut]:
    users = await user_service.list_users(db, dep_id=dep_id)
    return [UserOut.model_validate(u) for u in users]


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> UserOut:
    user = await user_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    user = await user_service.update_user(
        db,
        actor_user_id=current_user.user_id,
        user_id=user_id,
        first_name=payload.first_name,
        middle_name=payload.middle_name,
        last_name=payload.last_name,
        email=payload.email,
        role=payload.role,
        dep_id=payload.dep_id,
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    user = await user_service.soft_delete_user(
        db, actor_user_id=current_user.user_id, user_id=user_id
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")


@router.post("/{user_id}/suspend", response_model=UserOut)
async def suspend_user(
    user_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UserOut:
    """إيقاف حساب مؤقتًا — FR-UM-004 (يمنع تسجيل الدخول فقط)."""
    user = await user_service.set_user_status(
        db, actor_user_id=current_user.user_id, user_id=user_id, status=UserStatus.suspended
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    return UserOut.model_validate(user)


@router.post("/{user_id}/reactivate", response_model=UserOut)
async def reactivate_user(
    user_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UserOut:
    user = await user_service.set_user_status(
        db, actor_user_id=current_user.user_id, user_id=user_id, status=UserStatus.active
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    return UserOut.model_validate(user)
