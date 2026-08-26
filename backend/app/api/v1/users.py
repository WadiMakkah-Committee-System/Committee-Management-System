"""
الهدف:
راوتات إدارة المستخدمين — FR-UM-001 → FR-UM-006, FR-UM-021 → FR-UM-022.

قواعد الوصول:
- كل عمليات الإدارة (إنشاء/عرض الكل/تعديل/حذف/إيقاف/تفعيل) مقصورة على
  super_admin فقط، حسب القاعدة الموثّقة في ERD ("السوبر هو اللي يضيف
  الأعضاء لإدارته").
- استثناء واحد: GET /users/me — متاح لأي مستخدم مسجّل دخول (بلا قيد دور)
  عشان يشوف بياناته الشخصية + إدارته (اسمها ووصفها) في طلب واحد، بدل
  الحاجة يستدعي endpoint الإدارات (المقصور على super_admin أصلًا).

المسؤولية:
تحويل طلبات HTTP لاستدعاءات user_service، وفرض RBAC عبر
core.dependencies.require_roles على مستوى كل راوت يحتاجها.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.models.user import UserStatus
from app.schemas.user import UserCreate, UserDetailOut, UserOut, UserUpdate
from app.services import user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserDetailOut)
async def get_my_profile(current_user: CurrentUser) -> UserDetailOut:
    """
    بيانات المستخدم الحالي، بما فيها إدارته كاملة (مضمَّنة عبر
    UserOut.department) وقائمة صلاحياته الفعلية (permissions) — متاح لأي
    دور، بدون قيد RBAC، لأنه يعرض بيانات المستخدم نفسه فقط.

    صلاحيات المستخدم هنا مطلوبة للواجهة الأمامية لتقرير أي شاشات/تبويبات
    تظهر له (مثال: تبويب "الأدوار والصلاحيات" يظهر فقط لمن يملك
    is_super_admin)، دون الاعتماد على أي قائمة أدوار ثابتة في كود الفرونت.

    ملاحظة تقنية: current_user يصل هنا محمَّلًا مسبقًا بعلاقة department
    (selectinload) من داخل core.dependencies.get_current_user →
    user_service.get_user، فلا حاجة لاستعلام إضافي هنا.
    """
    data = UserOut.model_validate(current_user).model_dump()
    data["permissions"] = sorted(current_user.role.permission_codes)
    return UserDetailOut.model_validate(data)


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("users.create"))],
)
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
            role_id=payload.role_id,
            dep_id=payload.dep_id,
            job_title_id=payload.job_title_id,
            status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UserOut.model_validate(user)


@router.get(
    "",
    response_model=list[UserOut],
    dependencies=[Depends(require_permission("users.view"))],
)
async def list_users(
    dep_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)
) -> list[UserOut]:
    users = await user_service.list_users(db, dep_id=dep_id)
    return [UserOut.model_validate(u) for u in users]


@router.get(
    "/{user_id}",
    response_model=UserDetailOut,
    dependencies=[Depends(require_permission("users.view"))],
)
async def get_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> UserDetailOut:
    user = await user_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    data = UserOut.model_validate(user).model_dump()
    data["permissions"] = sorted(user.role.permission_codes)
    return UserDetailOut.model_validate(data)


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_permission("users.update"))],
)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    try:
        user = await user_service.update_user(
            db,
            actor_user_id=current_user.user_id,
            user_id=user_id,
            first_name=payload.first_name,
            middle_name=payload.middle_name,
            last_name=payload.last_name,
            email=payload.email,
            role_id=payload.role_id,
            dep_id=payload.dep_id,
            job_title_id=payload.job_title_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    return UserOut.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("users.delete"))],
)
async def delete_user(
    user_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    try:
        user = await user_service.soft_delete_user(
            db, actor_user_id=current_user.user_id, user_id=user_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")


@router.post(
    "/{user_id}/suspend",
    response_model=UserOut,
    dependencies=[Depends(require_permission("users.suspend"))],
)
async def suspend_user(
    user_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UserOut:
    """إيقاف حساب مؤقتًا — FR-UM-004 (يمنع تسجيل الدخول فقط)."""
    try:
        user = await user_service.set_user_status(
            db, actor_user_id=current_user.user_id, user_id=user_id, status=UserStatus.suspended
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    return UserOut.model_validate(user)


@router.post(
    "/{user_id}/reactivate",
    response_model=UserOut,
    dependencies=[Depends(require_permission("users.reactivate"))],
)
async def reactivate_user(
    user_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UserOut:
    user = await user_service.set_user_status(
        db, actor_user_id=current_user.user_id, user_id=user_id, status=UserStatus.active
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    return UserOut.model_validate(user)
