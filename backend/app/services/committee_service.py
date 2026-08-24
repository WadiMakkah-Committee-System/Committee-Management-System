"""
الهدف:
منطق العمل (Business Logic) لوحدة "طلبات تشكيل اللجان" — RF-COM-100 →
RF-COM-700 (SRS)، يطبّق دورة الحياة الكاملة للطلب حسب التدفق الموثّق في
BRS (ص12) وSRS (Use Cases 1-8، ص19)، بعد تصحيحه بقرارات موثّقة مع
المستخدمة (Lama) بتاريخ 2026-08-24 — راجعي project_memory:
phase1-committee-formation.md لتفاصيل القرارات.

آلة الحالات المعتمدة (Requirements & Business Rules — موثّقة، وليست
اختراعًا):
    draft → submitted → (under_review) → pending_approval → approved
                                                            → rejected

من يقدر يفعل ماذا (RBAC مفروض هنا + على مستوى الراوت):
- draft: يُنشئه ويعدّله فقط مقدّم الطلب نفسه (requested_by) — صلاحية
  committees.request.create تكفي طالما الطلب لسا بحالة draft وهو صاحبه.
- draft → submitted: مقدّم الطلب فقط (زر "إرسال للمكتب التنفيذي" —
  RF-COM-300). بعدها **لا يقدر مقدّم الطلب يعدّله إطلاقًا** (قرار موثّق
  صراحة من المستخدمة، يخالف الأصل الافتراضي بلا "إرجاع للادمن").
- submitted/under_review/pending_approval: يعدّله فقط من يملك صلاحية
  committees.request.update (المكتب التنفيذي حصرًا) — بلا قيد ملكية،
  وبدون أي مسار "إرجاع لمقدّم الطلب" (SRS Use Case #2: التعديل مباشر من
  المكتب التنفيذي نفسه).
- submitted/under_review → pending_approval: committees.request.escalate
  (المكتب التنفيذي — RF-COM-400 / Use Case #4).
- pending_approval → approved/rejected: committees.request.approve
  (الرئيس التنفيذي حصرًا — RF-COM-500/600). الموافقة تُنشئ تلقائيًا سجل
  committees + committee_members من proposed_members اللحظية (Use Case #6،
  BRS ص12).

قرار موثّق مهم (يخالف SRS Use Case #5 وpermissions.xlsx عمدًا، بموافقة
المستخدمة — راجعي المذكرة أعلاه): عضوية اللجنة وبياناتها بعد الاعتماد
**مقفلة نهائيًا لكل الأدوار بدون استثناء** — لا يوجد هنا ولا في طبقة الـ
API أي دالة تعدّل committees/committee_members بعد approved.

الإشعارات (RF-COM-700: إشعار الأعضاء فور الاعتماد) خارج نطاق هذه الخدمة
— لا يوجد جدول notifications عام بالمشروع بعد (قرار موثّق مسبقًا في Phase
1)، تُحل عند بناء تلك الوحدة.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.committee import Committee
from app.models.committee_request import CommitteeFormationRequest, CommitteeRequestStatus
from app.models.user import User
from app.services import audit_service


class CommitteeRequestNotFoundError(Exception):
    """الطلب غير موجود — تُترجَم إلى 404 في طبقة الـ API."""


class CommitteeRequestForbiddenError(Exception):
    """
    محاولة إجراء غير مسموح بها لهذا المستخدم تحديدًا رغم امتلاكه صلاحية
    عامة ذات صلة (مثال: تعديل ادمن لطلب ادمن آخر وهو لسا draft) — تُترجَم
    إلى 403 في طبقة الـ API. مختلفة عمدًا عن ValueError (أخطاء تحقق/عمل
    عامة، تُترجَم إلى 400).
    """


class CommitteeRequestInvalidTransitionError(Exception):
    """محاولة انتقال حالة غير صالح من الحالة الحالية — تُترجَم إلى 400."""


async def _load_request(db: AsyncSession, request_id: uuid.UUID) -> CommitteeFormationRequest | None:
    result = await db.execute(
        select(CommitteeFormationRequest)
        .options(
            selectinload(CommitteeFormationRequest.requester),
            selectinload(CommitteeFormationRequest.proposed_members),
        )
        .where(CommitteeFormationRequest.request_id == request_id)
    )
    return result.scalar_one_or_none()


async def _get_request_or_raise(db: AsyncSession, request_id: uuid.UUID) -> CommitteeFormationRequest:
    request = await _load_request(db, request_id)
    if request is None:
        raise CommitteeRequestNotFoundError("طلب تشكيل اللجنة غير موجود")
    return request


async def _resolve_members(db: AsyncSession, member_ids: list[uuid.UUID]) -> list[User]:
    """
    يتحقق من أن كل الأعضاء المقترحين مستخدمون فعليون وغير محذوفين، ويرجعهم
    ككائنات User جاهزة للربط بعلاقة proposed_members. يرفع ValueError لو
    أي معرّف غير موجود (RF-COM-200: بيانات اللجنة يجب أن تكون صحيحة).
    """
    result = await db.execute(
        select(User).where(User.user_id.in_(member_ids), User.deleted_at.is_(None))
    )
    found = {u.user_id: u for u in result.scalars().all()}
    missing = [str(mid) for mid in member_ids if mid not in found]
    if missing:
        raise ValueError(f"أعضاء غير موجودين أو محذوفين: {', '.join(missing)}")
    # نحافظ على نفس ترتيب الإدخال
    return [found[mid] for mid in member_ids]


def _assert_dates_valid(start_date: date, end_date: date) -> None:
    if end_date <= start_date:
        raise ValueError("تاريخ نهاية عمل اللجنة يجب أن يكون بعد تاريخ البداية")


async def create_request(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    committee_name: str,
    statement: str | None,
    start_date: date,
    end_date: date,
    proposed_member_ids: list[uuid.UUID],
) -> CommitteeFormationRequest:
    """
    إنشاء طلب تشكيل لجنة جديد بحالة draft (RF-COM-100/200) — لا يُرسل
    تلقائيًا للمكتب التنفيذي؛ الإرسال خطوة منفصلة صريحة (submit_request).
    """
    _assert_dates_valid(start_date, end_date)
    members = await _resolve_members(db, proposed_member_ids)

    request = CommitteeFormationRequest(
        committee_name=committee_name,
        statement=statement,
        start_date=start_date,
        end_date=end_date,
        status=CommitteeRequestStatus.draft,
        requested_by=actor_user_id,
        proposed_members=members,
    )
    db.add(request)
    await db.flush()

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="create",
        target_type="committee_formation_request",
        target_id=request.request_id,
        metadata={"committee_name": committee_name, "member_count": len(members)},
    )

    await db.commit()
    return await _get_request_or_raise(db, request.request_id)


async def list_requests(
    db: AsyncSession, *, actor: User, can_view_all: bool
) -> list[CommitteeFormationRequest]:
    """
    عرض قائمة الطلبات. من يملك committees.request.view (المكتب التنفيذي/
    الرئيس التنفيذي/super_admin) يشوف كل الطلبات. غير ذلك (الادمن، الذي
    لا يملك هذه الصلاحية حسب permissions.xlsx) يشوف طلباته هو فقط —
    استثناء ملكية شبيه بنمط GET /users/me الموثّق مسبقًا بالمشروع، وإلا
    ما راح يقدر يتابع حالة طلبه بعد إرساله. قرار غير موثّق صراحة بالوثائق،
    مذكور صراحة هنا لسهولة المراجعة.
    """
    stmt = (
        select(CommitteeFormationRequest)
        .options(
            selectinload(CommitteeFormationRequest.requester),
            selectinload(CommitteeFormationRequest.proposed_members),
        )
        .order_by(CommitteeFormationRequest.created_at.desc())
    )
    if not can_view_all:
        stmt = stmt.where(CommitteeFormationRequest.requested_by == actor.user_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_request(
    db: AsyncSession, *, request_id: uuid.UUID, actor: User, can_view_all: bool
) -> CommitteeFormationRequest:
    """تفاصيل طلب واحد — نفس قاعدة الوصول في list_requests (ملكية أو صلاحية عامة)."""
    request = await _get_request_or_raise(db, request_id)
    if not can_view_all and request.requested_by != actor.user_id:
        raise CommitteeRequestForbiddenError("ليست لديك صلاحية لعرض هذا الطلب")
    return request


async def update_request(
    db: AsyncSession,
    *,
    actor: User,
    request_id: uuid.UUID,
    committee_name: str | None,
    statement: str | None,
    start_date: date | None,
    end_date: date | None,
    proposed_member_ids: list[uuid.UUID] | None,
    can_edit_any_pending: bool,
) -> CommitteeFormationRequest:
    """
    تعديل طلب قائم. القاعدة (موثّقة صراحة من المستخدمة):
    - draft: مقدّم الطلب نفسه فقط (وليس أي حامل لصلاحية request.create).
    - submitted/under_review/pending_approval: من يملك committees.request.update
      فقط (can_edit_any_pending) — بلا قيد ملكية.
    - approved/rejected/returned: نهائية، لا تعديل إطلاقًا.
    """
    request = await _get_request_or_raise(db, request_id)

    if request.status == CommitteeRequestStatus.draft:
        if request.requested_by != actor.user_id and not actor.role.is_super_admin:
            raise CommitteeRequestForbiddenError(
                "لا يقدر إلا مقدّم الطلب على تعديله وهو ما زال مسودة"
            )
    elif request.status in (
        CommitteeRequestStatus.submitted,
        CommitteeRequestStatus.under_review,
        CommitteeRequestStatus.pending_approval,
    ):
        if not can_edit_any_pending and not actor.role.is_super_admin:
            raise CommitteeRequestForbiddenError(
                "تعديل الطلب بعد إرساله متاح فقط للمكتب التنفيذي"
            )
    else:
        raise CommitteeRequestInvalidTransitionError(
            "الطلب في حالة نهائية (معتمد أو مرفوض) ولا يمكن تعديله"
        )

    new_start = start_date if start_date is not None else request.start_date
    new_end = end_date if end_date is not None else request.end_date
    _assert_dates_valid(new_start, new_end)

    before = {
        "committee_name": request.committee_name,
        "statement": request.statement,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "member_ids": sorted(str(u.user_id) for u in request.proposed_members),
    }

    if committee_name is not None:
        request.committee_name = committee_name
    if statement is not None:
        request.statement = statement
    request.start_date = new_start
    request.end_date = new_end
    if proposed_member_ids is not None:
        request.proposed_members = await _resolve_members(db, proposed_member_ids)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="committee_formation_request",
        target_id=request.request_id,
        metadata={"before": before},
    )

    await db.commit()
    return await _get_request_or_raise(db, request.request_id)


async def submit_request(
    db: AsyncSession, *, actor: User, request_id: uuid.UUID
) -> CommitteeFormationRequest:
    """draft → submitted (RF-COM-300). مقدّم الطلب نفسه فقط."""
    request = await _get_request_or_raise(db, request_id)

    if request.status != CommitteeRequestStatus.draft:
        raise CommitteeRequestInvalidTransitionError("لا يمكن إرسال طلب ليس بحالة مسودة")
    if request.requested_by != actor.user_id and not actor.role.is_super_admin:
        raise CommitteeRequestForbiddenError("لا يقدر إلا مقدّم الطلب على إرساله")

    request.status = CommitteeRequestStatus.submitted

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="submit",
        target_type="committee_formation_request",
        target_id=request.request_id,
        metadata={"to_status": request.status.value},
    )

    await db.commit()
    return await _get_request_or_raise(db, request.request_id)


async def escalate_request(
    db: AsyncSession, *, actor: User, request_id: uuid.UUID
) -> CommitteeFormationRequest:
    """
    submitted/under_review → pending_approval (RF-COM-400 / Use Case #4).
    المكتب التنفيذي فقط — الصلاحية مفروضة أصلًا على مستوى الراوت
    (committees.request.escalate)، هنا فقط نتحقق من صحة الحالة الحالية.
    """
    request = await _get_request_or_raise(db, request_id)

    if request.status not in (
        CommitteeRequestStatus.submitted,
        CommitteeRequestStatus.under_review,
    ):
        raise CommitteeRequestInvalidTransitionError(
            "لا يمكن رفع الطلب للاعتماد إلا بعد إرساله وقبل رفعه سابقًا"
        )

    request.status = CommitteeRequestStatus.pending_approval

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="escalate",
        target_type="committee_formation_request",
        target_id=request.request_id,
        metadata={"to_status": request.status.value},
    )

    await db.commit()
    return await _get_request_or_raise(db, request.request_id)


async def approve_request(
    db: AsyncSession, *, actor: User, request_id: uuid.UUID
) -> CommitteeFormationRequest:
    """
    pending_approval → approved (RF-COM-500 / Use Case #6). ينشئ سجل
    committees وcommittee_members تلقائيًا من الأعضاء المقترحين اللحظيين
    (BRS ص12: "فتتشكل اللجنة بشكل رسمي"). الرئيس التنفيذي فقط.
    """
    request = await _get_request_or_raise(db, request_id)

    if request.status != CommitteeRequestStatus.pending_approval:
        raise CommitteeRequestInvalidTransitionError(
            "لا يمكن اعتماد طلب ليس بانتظار الاعتماد"
        )

    request.status = CommitteeRequestStatus.approved

    committee = Committee(
        name=request.committee_name,
        statement=request.statement,
        start_date=request.start_date,
        end_date=request.end_date,
        source_request_id=request.request_id,
        members=list(request.proposed_members),
    )
    db.add(committee)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="approve",
        target_type="committee_formation_request",
        target_id=request.request_id,
        metadata={"to_status": request.status.value},
    )

    await db.commit()
    return await _get_request_or_raise(db, request.request_id)


class CommitteeNotFoundError(Exception):
    """اللجنة المعتمدة غير موجودة — تُترجَم إلى 404 في طبقة الـ API."""


async def list_committees(db: AsyncSession) -> list[Committee]:
    """
    عرض اللجان المعتمدة (committees.view_authorized). سطح قراءة بسيط فقط
    ليثبت أن الاعتماد أنشأ اللجنة فعليًا — إدارة اللجان الكاملة (مناصب،
    صلاحيات الأعضاء...) خارج نطاق Phase 2 (نطاق مختلف موثّق في BRS بند 6:
    "إدارة أعضاء اللجان والمناصب والصلاحيات").
    """
    result = await db.execute(
        select(Committee).options(selectinload(Committee.members)).order_by(Committee.created_at.desc())
    )
    return list(result.scalars().all())


async def get_committee(db: AsyncSession, committee_id: uuid.UUID) -> Committee:
    result = await db.execute(
        select(Committee)
        .options(selectinload(Committee.members))
        .where(Committee.committee_id == committee_id)
    )
    committee = result.scalar_one_or_none()
    if committee is None:
        raise CommitteeNotFoundError("اللجنة غير موجودة")
    return committee


async def reject_request(
    db: AsyncSession, *, actor: User, request_id: uuid.UUID, rejection_reason: str
) -> CommitteeFormationRequest:
    """pending_approval → rejected (RF-COM-600 / Use Case #7). الرئيس التنفيذي فقط، مع سبب إلزامي."""
    request = await _get_request_or_raise(db, request_id)

    if request.status != CommitteeRequestStatus.pending_approval:
        raise CommitteeRequestInvalidTransitionError(
            "لا يمكن رفض طلب ليس بانتظار الاعتماد"
        )

    request.status = CommitteeRequestStatus.rejected
    request.rejection_reason = rejection_reason

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="reject",
        target_type="committee_formation_request",
        target_id=request.request_id,
        metadata={"to_status": request.status.value, "rejection_reason": rejection_reason},
    )

    await db.commit()
    return await _get_request_or_raise(db, request.request_id)
