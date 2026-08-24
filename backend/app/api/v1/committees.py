"""
الهدف:
راوتات وحدة "طلبات تشكيل اللجان" — RF-COM-100 → RF-COM-700 (SRS)، Phase 2.

قواعد الوصول (كل واحدة محكومة بصلاحية فعلية من كتالوج الصلاحيات، وليس
باسم دور ثابت — راجعي committee_service.py للتفاصيل الكاملة لكل قاعدة):
- POST   /committee-requests               → committees.request.create (الادمن)
- GET    /committee-requests, /{id}        → committees.request.view، أو مقدّم
                                              الطلب نفسه لطلباته فقط (استثناء ملكية)
- PATCH  /committee-requests/{id}          → committees.request.create (draft/ملكية)
                                              أو committees.request.update (بعد الإرسال)
- POST   /{id}/submit                      → committees.request.create + ملكية
- POST   /{id}/escalate                    → committees.request.escalate (المكتب التنفيذي)
- POST   /{id}/approve, /{id}/reject       → committees.request.approve (الرئيس التنفيذي)

قرار موثّق: لا يوجد أي endpoint هنا لتعديل أعضاء/بيانات اللجنة بعد
الاعتماد — مقفلة نهائيًا لكل الأدوار (راجعي committee_service.py).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.schemas.committee import (
    CommitteeFormationRequestCreate,
    CommitteeFormationRequestOut,
    CommitteeFormationRequestUpdate,
    CommitteeOut,
    CommitteeRejectRequest,
)
from app.services import committee_service
from app.services.committee_service import (
    CommitteeNotFoundError,
    CommitteeRequestForbiddenError,
    CommitteeRequestInvalidTransitionError,
    CommitteeRequestNotFoundError,
)

router = APIRouter(prefix="/committee-requests", tags=["Committee Formation Requests"])

#: راوتر مستقل للجان المعتمدة نفسها (بعد التشكيل) — سطح قراءة بسيط فقط،
#: وليس وحدة "إدارة اللجان" الكاملة (نطاق مختلف لاحق حسب BRS بند 6).
committees_router = APIRouter(prefix="/committees", tags=["Committees"])


def _handle_errors(exc: Exception) -> HTTPException:
    """يترجم استثناءات طبقة الخدمة إلى استجابات HTTP مناسبة، مركزيًا."""
    if isinstance(exc, (CommitteeRequestNotFoundError, CommitteeNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, CommitteeRequestForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, CommitteeRequestInvalidTransitionError):
        # 409 Conflict أدق من 400 هنا: الطلب صحيح شكليًا، لكنه يتعارض مع
        # حالة الطلب الحالية (State Conflict)، وليس خطأ بالبيانات نفسها.
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


@router.post(
    "",
    response_model=CommitteeFormationRequestOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("committees.request.create"))],
)
async def create_committee_request(
    payload: CommitteeFormationRequestCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CommitteeFormationRequestOut:
    try:
        request = await committee_service.create_request(
            db,
            actor_user_id=current_user.user_id,
            committee_name=payload.committee_name,
            statement=payload.statement,
            start_date=payload.start_date,
            end_date=payload.end_date,
            proposed_member_ids=payload.proposed_member_ids,
        )
    except ValueError as exc:
        raise _handle_errors(exc) from exc
    return CommitteeFormationRequestOut.model_validate(request)


@router.get("", response_model=list[CommitteeFormationRequestOut])
async def list_committee_requests(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[CommitteeFormationRequestOut]:
    can_view_all = (
        current_user.role.is_super_admin
        or "committees.request.view" in current_user.role.permission_codes
    )
    requests = await committee_service.list_requests(
        db, actor=current_user, can_view_all=can_view_all
    )
    return [CommitteeFormationRequestOut.model_validate(r) for r in requests]


@router.get("/{request_id}", response_model=CommitteeFormationRequestOut)
async def get_committee_request(
    request_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> CommitteeFormationRequestOut:
    can_view_all = (
        current_user.role.is_super_admin
        or "committees.request.view" in current_user.role.permission_codes
    )
    try:
        request = await committee_service.get_request(
            db, request_id=request_id, actor=current_user, can_view_all=can_view_all
        )
    except (CommitteeRequestNotFoundError, CommitteeRequestForbiddenError) as exc:
        raise _handle_errors(exc) from exc
    return CommitteeFormationRequestOut.model_validate(request)


@router.patch(
    "/{request_id}",
    response_model=CommitteeFormationRequestOut,
    dependencies=[
        Depends(require_permission("committees.request.create", "committees.request.update"))
    ],
)
async def update_committee_request(
    request_id: uuid.UUID,
    payload: CommitteeFormationRequestUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CommitteeFormationRequestOut:
    can_edit_any_pending = "committees.request.update" in current_user.role.permission_codes
    try:
        request = await committee_service.update_request(
            db,
            actor=current_user,
            request_id=request_id,
            committee_name=payload.committee_name,
            statement=payload.statement,
            start_date=payload.start_date,
            end_date=payload.end_date,
            proposed_member_ids=payload.proposed_member_ids,
            can_edit_any_pending=can_edit_any_pending,
        )
    except (
        CommitteeRequestNotFoundError,
        CommitteeRequestForbiddenError,
        CommitteeRequestInvalidTransitionError,
        ValueError,
    ) as exc:
        raise _handle_errors(exc) from exc
    return CommitteeFormationRequestOut.model_validate(request)


@router.post(
    "/{request_id}/submit",
    response_model=CommitteeFormationRequestOut,
    dependencies=[Depends(require_permission("committees.request.create"))],
)
async def submit_committee_request(
    request_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> CommitteeFormationRequestOut:
    """RF-COM-300: إرسال الطلب من الادمن للمكتب التنفيذي (draft → submitted)."""
    try:
        request = await committee_service.submit_request(
            db, actor=current_user, request_id=request_id
        )
    except (
        CommitteeRequestNotFoundError,
        CommitteeRequestForbiddenError,
        CommitteeRequestInvalidTransitionError,
    ) as exc:
        raise _handle_errors(exc) from exc
    return CommitteeFormationRequestOut.model_validate(request)


@router.post(
    "/{request_id}/escalate",
    response_model=CommitteeFormationRequestOut,
    dependencies=[Depends(require_permission("committees.request.escalate"))],
)
async def escalate_committee_request(
    request_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> CommitteeFormationRequestOut:
    """RF-COM-400 / Use Case #4: رفع الطلب للرئيس التنفيذي (→ pending_approval)."""
    try:
        request = await committee_service.escalate_request(
            db, actor=current_user, request_id=request_id
        )
    except (CommitteeRequestNotFoundError, CommitteeRequestInvalidTransitionError) as exc:
        raise _handle_errors(exc) from exc
    return CommitteeFormationRequestOut.model_validate(request)


@router.post(
    "/{request_id}/approve",
    response_model=CommitteeFormationRequestOut,
    dependencies=[Depends(require_permission("committees.request.approve"))],
)
async def approve_committee_request(
    request_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> CommitteeFormationRequestOut:
    """RF-COM-500 / Use Case #6: اعتماد الطلب — يُنشئ اللجنة رسميًا."""
    try:
        request = await committee_service.approve_request(
            db, actor=current_user, request_id=request_id
        )
    except (CommitteeRequestNotFoundError, CommitteeRequestInvalidTransitionError) as exc:
        raise _handle_errors(exc) from exc
    return CommitteeFormationRequestOut.model_validate(request)


@committees_router.get(
    "",
    response_model=list[CommitteeOut],
    dependencies=[Depends(require_permission("committees.view_authorized"))],
)
async def list_committees(db: AsyncSession = Depends(get_db)) -> list[CommitteeOut]:
    committees = await committee_service.list_committees(db)
    return [CommitteeOut.model_validate(c) for c in committees]


@committees_router.get(
    "/{committee_id}",
    response_model=CommitteeOut,
    dependencies=[Depends(require_permission("committees.view_authorized"))],
)
async def get_committee(committee_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> CommitteeOut:
    try:
        committee = await committee_service.get_committee(db, committee_id)
    except CommitteeNotFoundError as exc:
        raise _handle_errors(exc) from exc
    return CommitteeOut.model_validate(committee)


@router.post(
    "/{request_id}/reject",
    response_model=CommitteeFormationRequestOut,
    dependencies=[Depends(require_permission("committees.request.approve"))],
)
async def reject_committee_request(
    request_id: uuid.UUID,
    payload: CommitteeRejectRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CommitteeFormationRequestOut:
    """RF-COM-600 / Use Case #7: رفض الطلب، مع توثيق السبب إلزاميًا."""
    try:
        request = await committee_service.reject_request(
            db,
            actor=current_user,
            request_id=request_id,
            rejection_reason=payload.rejection_reason,
        )
    except (CommitteeRequestNotFoundError, CommitteeRequestInvalidTransitionError) as exc:
        raise _handle_errors(exc) from exc
    return CommitteeFormationRequestOut.model_validate(request)
