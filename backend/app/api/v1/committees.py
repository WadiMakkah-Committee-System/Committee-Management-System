"""
الهدف:
راوتات وحدة "طلبات تشكيل اللجان" — RF-COM-100 → RF-COM-700 (SRS)، Phase 2.

قواعد الوصول (كل واحدة محكومة بصلاحية فعلية من كتالوج الصلاحيات + نطاق
وصول (own/department/all)، وليس باسم دور ثابت — راجعي committee_service.py
للتفاصيل الكاملة لكل قاعدة. مراجعة لاما 2026-08-30 وحّدت كل تعديل الطلب
تحت صلاحية واحدة committees.request.update بدل الخلط السابق بين .create
و.update حسب الحالة):
- POST   /committee-requests               → committees.request.create (الادمن)
- GET    /committee-requests, /{id}        → committees.request.view (نطاق own = طلباته
                                              فقط، نطاق أوسع = كل الطلبات)
- PATCH  /committee-requests/{id}          → committees.request.update (نطاق own +
                                              draft/returned، أو نطاق أوسع + submitted/under_review)
- POST   /{id}/submit                      → committees.request.update + ملكية فعلية (draft أو returned)
- POST   /{id}/return-to-admin             → committees.request.update (المكتب التنفيذي → الادمن)
- POST   /{id}/escalate                    → committees.request.escalate (المكتب التنفيذي)
- POST   /{id}/approve, /{id}/reject       → committees.request.approve (الرئيس التنفيذي، نهائي)
- POST   /{id}/return-to-office            → committees.request.approve (الرئيس التنفيذي → المكتب، غير نهائي)
- GET    /committees, /{id}                → committees.view (نطاق own = اللجان التي أنا
                                              رئيسها/عضو فيها فقط، نطاق أوسع = كل اللجان)

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
    CommitteeReturnRequest,
    DepartmentMemberElsewhereOut,
)
from app.schemas.user import UserOut
from app.services import committee_service, user_service
from app.services.committee_service import (
    CommitteeForbiddenError,
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
    if isinstance(exc, (CommitteeRequestForbiddenError, CommitteeForbiddenError)):
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
            chair_user_id=payload.chair_user_id,
        )
    except ValueError as exc:
        raise _handle_errors(exc) from exc
    return CommitteeFormationRequestOut.model_validate(request)


def _can_view_all_requests(current_user: CurrentUser) -> bool:
    """نطاق department/all يعني رؤية كل الطلبات؛ own يعني طلبات actor نفسه فقط."""
    return current_user.scope_for("committees.request.view") in ("department", "all")


@router.get("", response_model=list[CommitteeFormationRequestOut])
async def list_committee_requests(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[CommitteeFormationRequestOut]:
    can_view_all = _can_view_all_requests(current_user)
    requests = await committee_service.list_requests(
        db, actor=current_user, can_view_all=can_view_all
    )
    return [CommitteeFormationRequestOut.model_validate(r) for r in requests]


@router.get(
    "/eligible-members",
    response_model=list[UserOut],
    dependencies=[
        Depends(require_permission("committees.request.create", "committees.request.update"))
    ],
)
async def list_committee_eligible_members(db: AsyncSession = Depends(get_db)) -> list[UserOut]:
    """
    مراجعة لاما 2026-08-31: قائمة المستخدمين المؤهلين ليكونوا أعضاء/رئيسًا
    مقترحًا بطلب تشكيل لجنة — عمدًا **بدون** أي تصفية بنطاق users.view
    (own/department/all)، لأن هذا الـendpoint مستقل تمامًا عن صلاحية عرض
    المستخدمين: من يقدر ينشئ/يعدّل طلب تشكيل لجنة (committees.request.create
    أو .update) يحتاج يشوف مرشحين من كل الإدارات (اللجنة نفسها غالبًا
    متعددة الإدارات)، بغض النظر عن نطاقه الشخصي على users.view — وقد لا
    يملك هذه الصلاحية إطلاقًا (مثال: الادمن). قبل /{request_id} بترتيب
    التسجيل عمدًا (تفادي تضارب المسارات).
    """
    users = await user_service.list_users(db)
    return [UserOut.model_validate(u) for u in users]


@router.get("/{request_id}", response_model=CommitteeFormationRequestOut)
async def get_committee_request(
    request_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> CommitteeFormationRequestOut:
    can_view_all = _can_view_all_requests(current_user)
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
    dependencies=[Depends(require_permission("committees.request.update"))],
)
async def update_committee_request(
    request_id: uuid.UUID,
    payload: CommitteeFormationRequestUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CommitteeFormationRequestOut:
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
            chair_user_id=payload.chair_user_id,
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
    dependencies=[Depends(require_permission("committees.request.update"))],
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
    "/{request_id}/return-to-admin",
    response_model=CommitteeFormationRequestOut,
    dependencies=[Depends(require_permission("committees.request.update"))],
)
async def return_committee_request_to_admin(
    request_id: uuid.UUID,
    payload: CommitteeReturnRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CommitteeFormationRequestOut:
    """
    المكتب التنفيذي يرجع الطلب لمقدّمه (الادمن) مع سبب — بدل التعديل
    المباشر أو الرفع للاعتماد (submitted/under_review → returned).
    """
    try:
        request = await committee_service.return_to_admin_request(
            db, actor=current_user, request_id=request_id, return_reason=payload.return_reason
        )
    except (
        CommitteeRequestNotFoundError,
        CommitteeRequestForbiddenError,
        CommitteeRequestInvalidTransitionError,
    ) as exc:
        raise _handle_errors(exc) from exc
    return CommitteeFormationRequestOut.model_validate(request)


@router.post(
    "/{request_id}/return-to-office",
    response_model=CommitteeFormationRequestOut,
    dependencies=[Depends(require_permission("committees.request.approve"))],
)
async def return_committee_request_to_office(
    request_id: uuid.UUID,
    payload: CommitteeReturnRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CommitteeFormationRequestOut:
    """
    الرئيس التنفيذي يرجع الطلب للمكتب التنفيذي مع سبب — بدل الاعتماد أو
    الرفض النهائي (pending_approval → under_review، غير نهائي).
    """
    try:
        request = await committee_service.return_to_office_request(
            db, actor=current_user, request_id=request_id, return_reason=payload.return_reason
        )
    except (CommitteeRequestNotFoundError, CommitteeRequestInvalidTransitionError) as exc:
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
)
async def list_committees(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[CommitteeOut]:
    """
    بلاغ لاما 2026-09-01: قيد require_permission("committees.view") الثابت
    هنا كان يمنع تمامًا أي عضو لجنة (رئيس/عضو) لا يملك committees.view على
    مستوى System Role من رؤية قسم "اللجان" بالواجهة كليًا — رغم أنه عضو
    فعلي بلجنة معتمدة، ورغم أن get_committee (لجنة واحدة، أدناه) مسموح له
    عبرها فعليًا منذ مراجعة 2026-08-31. نفس مسار الوصول المزدوج (OR) هناك
    يُطبَّق هنا الآن: System Role scope (own/department/all) **أو** عضوية
    لجنة واحدة على الأقل يمنحها دور اللجنة صلاحية committees.view — وفي
    الحالة الثانية نطاق "own" أصلًا يكفي ويطابق تمامًا المطلوب (يُرجع فقط
    اللجان التي هو رئيسها/عضو فيها، راجعي committee_service.list_committees).
    """
    system_scope = current_user.scope_for("committees.view")
    has_committee_role_access = system_scope is not None
    if not has_committee_role_access:
        has_committee_role_access = await committee_service.user_has_committee_role_view_access(
            db, user_id=current_user.user_id
        )
    if not has_committee_role_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ليست لديك صلاحية للقيام بهذا الإجراء",
        )
    scope = system_scope or "own"
    committees = await committee_service.list_committees(db, actor=current_user, scope=scope)
    return [CommitteeOut.model_validate(c) for c in committees]


@committees_router.get(
    "/department-members-elsewhere",
    response_model=list[DepartmentMemberElsewhereOut],
    dependencies=[Depends(require_permission("committees.view"))],
)
async def list_department_members_elsewhere(
    current_user: CurrentUser,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[DepartmentMemberElsewhereOut]:
    """
    مسار مستقل عمدًا قبل /{committee_id} بترتيب التسجيل (وإلا FastAPI
    يحاول يفسّر "department-members-elsewhere" كـcommittee_id ويفشل).
    موظفو إدارة current_user المشاركون بلجان لا تتبع إدارته — راجعي
    committee_service.list_department_members_elsewhere للتفصيل الكامل.
    """
    rows = await committee_service.list_department_members_elsewhere(
        db, actor=current_user, search=search
    )
    return [DepartmentMemberElsewhereOut.model_validate(r) for r in rows]


@committees_router.get(
    "/{committee_id}",
    response_model=CommitteeOut,
)
async def get_committee(
    committee_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> CommitteeOut:
    """
    مراجعة لاما 2026-08-31 ("أدوار اللجان"): أُزيل قيد require_permission
    الثابت على مستوى الراوت عمدًا (كان يمنع تمامًا أي مستخدم لا يملك
    صلاحية committees.view النظامية من الوصول، حتى لو كان رئيسًا/عضوًا
    فعليًا باللجنة نفسها — وأغلب مستخدمي النظام العاديين لا يملكون
    committees.view أصلًا). الوصول الآن مسار مزدوج (OR وليس AND)، تطبيقًا
    حرفيًا لصيغة "حساب الصلاحيات" المطلوبة: System Role scope (own/
    department/all على committees.view) **أو** Committee Role permission
    ضمن عضوية هذه اللجنة تحديدًا فقط — وليس أي لجنة أخرى.
    كلا المسارين يُفحصان فعليًا هنا بالباك-إند (وليس فقط بالفرونت)، فلا
    يقدر أي مستخدم تجاوز نطاق اللجنة عبر استدعاء الـ API مباشرة.

    مراجعة لاما 2026-09-01: حُذفت فئة الصلاحيات المصطنعة "committee_roles"
    (كانت تحوي كود "committee.view" المنفصل) — أدوار اللجان (رئيس/عضو)
    تختار الآن صلاحياتها من نفس الأقسام الحقيقية الموجودة أصلًا بالكتالوج
    (راجعي db/migrations/0017_remove_committee_roles_category.sql). لذلك
    مسار "Committee Role permission" هنا يتحقق من الكود الحقيقي
    "committees.view" (نفس الكود المستخدم بالمسار النظامي أعلاه، لكن هنا
    يُفحص ضمن صلاحيات دور اللجنة الخاصة بهذه العضوية تحديدًا وليس نطاق
    المستخدم النظامي العام).
    """
    system_scope = current_user.scope_for("committees.view")
    committee_role_codes = await committee_service.get_committee_role_permission_codes(
        db, user_id=current_user.user_id, committee_id=committee_id
    )
    has_committee_role_access = "committees.view" in committee_role_codes

    if system_scope is None and not has_committee_role_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ليست لديك صلاحية للقيام بهذا الإجراء",
        )

    try:
        committee = await committee_service.get_committee(
            db, committee_id, actor=current_user, scope=system_scope or "own"
        )
    except CommitteeForbiddenError as exc:
        # نطاق الصلاحية النظامية (إن وُجد) لا يغطي هذه اللجنة تحديدًا —
        # لكن قد يملك وصولًا مستقلًا عبر دور اللجنة (المسار الثاني بالـOR
        # أعلاه)، فنجرّبه هنا بدل الرفض الفوري.
        if not has_committee_role_access:
            raise _handle_errors(exc) from exc
        try:
            committee = await committee_service.get_committee(
                db, committee_id, actor=current_user, scope="own"
            )
        except (CommitteeNotFoundError, CommitteeForbiddenError) as exc2:
            raise _handle_errors(exc2) from exc2
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
