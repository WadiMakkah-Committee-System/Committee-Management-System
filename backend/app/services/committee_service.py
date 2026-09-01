"""
الهدف:
منطق العمل (Business Logic) لوحدة "طلبات تشكيل اللجان" — RF-COM-100 →
RF-COM-700 (SRS)، يطبّق دورة الحياة الكاملة للطلب حسب التدفق الموثّق في
BRS (ص12) وSRS (Use Cases 1-8، ص19)، بعد تصحيحه بقرارات موثّقة مع
المستخدمة (Lama) — آخرها بتاريخ 2026-08-24 (تصحيح مسار الإرجاع). راجعي
project_memory: phase2-committee-formation-requests.md لتفاصيل القرارات
كاملة.

آلة الحالات المعتمدة (Requirements & Business Rules — موثّقة، وليست
اختراعًا، وصفتها المستخدمة حرفيًا):

    draft ──submit──> submitted ──edit(مباشر)──> submitted (نفس الحالة)
      ^                  │  │
      │        return_to_admin  escalate
      │                  │       │
      └──returned<───────┘       v
              (الادمن يعدّل    under_review ──edit/escalate──> under_review/pending_approval
               ويعيد الإرسال)                                    │        │
                                                          return_to_office   approve/reject
                                                                   │             │
                                                                   v             v
                                                            under_review   approved (نهائية)
                                                                          rejected (نهائية)

من يقدر يفعل ماذا (RBAC مفروض هنا + على مستوى الراوت):
- draft/returned: يعدّله فقط مقدّم الطلب نفسه (requested_by) — صلاحية
  committees.request.create تكفي. submit_request يرسله من أي من الحالتين
  إلى submitted.
- submitted/under_review: يعدّله (تعديل مباشر)، أو يرجعه لمقدّم الطلب مع
  سبب (return_to_admin_request → returned)، أو يرفعه للرئيس التنفيذي
  (escalate_request → pending_approval) — كلها حصرًا لمن يملك الصلاحية
  المناسبة (المكتب التنفيذي). **لا يقدر مقدّم الطلب يعدّله إطلاقًا بعد
  الإرسال** — التعديل حصرًا للمكتب التنفيذي، أو الإرجاع الصريح له بسبب.
- pending_approval: **مقفول تمامًا على الجميع** — ولا حتى المكتب التنفيذي
  يعدّل بهذه الحالة (قرار موثّق صراحة 2026-08-24، يصحّح افتراضًا سابقًا).
  الرئيس التنفيذي حصرًا (committees.request.approve) يقرر: يعتمد (approved
  — تُنشئ تلقائيًا سجل committees + committee_members، Use Case #6)، يرفض
  نهائيًا (rejected، مع rejection_reason إلزامي)، أو يرجعه للمكتب التنفيذي
  مع سبب (return_to_office_request → under_review، ليعدّل المكتب ويرفعه
  مرة ثانية).

قرار موثّق مهم (يخالف SRS Use Case #5 وpermissions.xlsx عمدًا، بموافقة
المستخدمة): عضوية اللجنة وبياناتها بعد الاعتماد **مقفلة نهائيًا لكل
الأدوار بدون استثناء** — لا يوجد هنا ولا في طبقة الـAPI أي دالة تعدّل
committees/committee_members بعد approved.

الإشعارات (RF-COM-700: إشعار الأعضاء فور الاعتماد) خارج نطاق هذه الخدمة
— لا يوجد جدول notifications عام بالمشروع بعد (قرار موثّق مسبقًا في Phase
1)، تُحل عند بناء تلك الوحدة.
"""

import uuid
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.models.committee import Committee, CommitteeMember, committee_members
from app.models.committee_request import CommitteeFormationRequest, CommitteeRequestStatus
from app.models.department import Department
from app.models.role import Permission, Role, RolePermission
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


class CommitteeForbiddenError(Exception):
    """
    محاولة عرض لجنة معتمدة خارج نطاق وصول المستخدم (نطاق own و ليس رئيسًا
    أو عضوًا فيها) — تُترجَم إلى 403. راجعي مراجعة لاما 2026-08-30 حول
    committees.view وتصحيح نطاقها لدور "ادمن".
    """


class CommitteeRequestInvalidTransitionError(Exception):
    """محاولة انتقال حالة غير صالح من الحالة الحالية — تُترجَم إلى 400."""


async def _load_request(db: AsyncSession, request_id: uuid.UUID) -> CommitteeFormationRequest | None:
    result = await db.execute(
        select(CommitteeFormationRequest)
        .options(
            selectinload(CommitteeFormationRequest.requester),
            selectinload(CommitteeFormationRequest.proposed_members),
            # صراحةً رغم lazy="selectin" على مستوى الـ Model (نفس نمط
            # requester/proposed_members أعلاه) — لازم هنا تحديدًا لأن
            # approve_request يستدعي _get_request_or_raise مرتين: قبل
            # إنشاء اللجنة (حيث committee لا تزال None) وبعد commit()
            # لإنشائها.
            selectinload(CommitteeFormationRequest.committee),
        )
        # AsyncSessionLocal مُعرَّف بـexpire_on_commit=False (app/db/session.py)
        # — أي أن الكائن الذي حُمِّل بأول استدعاء لـ_get_request_or_raise
        # (حيث committee = None، قبل إنشاء اللجنة) يبقى في الـ Identity Map
        # لنفس الجلسة، ولن يُعاد تحميله تلقائيًا بعد commit() لأنه غير
        # "منتهي الصلاحية" (Expired). بدون populate_existing=True هنا،
        # الاستدعاء الثاني لـ_get_request_or_raise (بعد إنشاء اللجنة) كان
        # يعيد نفس القيمة القديمة (None) رغم وجود اللجنة فعليًا بقاعدة
        # البيانات — راجع اختبار test_chair_propagates_to_approved_committee.
        .execution_options(populate_existing=True)
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
    chair_user_id: uuid.UUID,
) -> CommitteeFormationRequest:
    """
    إنشاء طلب تشكيل لجنة جديد بحالة draft (RF-COM-100/200) — لا يُرسل
    تلقائيًا للمكتب التنفيذي؛ الإرسال خطوة منفصلة صريحة (submit_request).

    chair_user_id يجب أن يكون أحد proposed_member_ids — Schema (Pydantic)
    يتحقق من هذا أصلًا عند وجود الحقلين معًا بنفس الطلب، لكن نعيد التحقق
    هنا أيضًا (طبقة الخدمة هي مصدر الحقيقة الفعلي، والـSchema مجرد تحقق
    مبكر لتجربة مستخدم أفضل).
    """
    _assert_dates_valid(start_date, end_date)
    members = await _resolve_members(db, proposed_member_ids)
    if chair_user_id not in {m.user_id for m in members}:
        raise ValueError("رئيس اللجنة يجب أن يكون أحد الأعضاء المقترحين بالطلب")

    request = CommitteeFormationRequest(
        committee_name=committee_name,
        statement=statement,
        start_date=start_date,
        end_date=end_date,
        status=CommitteeRequestStatus.draft,
        requested_by=actor_user_id,
        proposed_members=members,
        chair_user_id=chair_user_id,
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
    chair_user_id: uuid.UUID | None,
) -> CommitteeFormationRequest:
    """
    تعديل طلب قائم. توحيد صلاحية التعديل (مراجعة لاما 2026-08-30 — "لا
    تنشئ صلاحية منفصلة لكل حالة/دور"): كل التعديل الآن تحت صلاحية واحدة
    committees.request.update (كانت مقسَّمة سابقًا بين .create للمسودة
    و.update للمُرسَل، وهو الخلط اللي رفضته المراجعة صراحة). النطاق
    (own/department/all) المسجَّل لدور actor على هذه الصلاحية + حالة
    الطلب الحالية هما ما يحددان "من يقدر يعدّل ومتى"، وليس صلاحية منفصلة:

    - draft/returned: **مقدّم الطلب فعليًا فقط** (ملكية حقيقية، بغض النظر
      عن اتساع نطاق actor على الصلاحية) — حتى صاحب نطاق 'all' (مثال:
      المكتب التنفيذي) لا يعدّل طلب غيره وهو draft/returned؛ هذه المرحلة
      حصرًا لصاحب الطلب (قرار عمل موثّق مسبقًا، لم يتغيّر بالتوحيد). returned
      تحديدًا تعني أن المكتب التنفيذي أرجع الطلب لصاحبه مع سبب — يعدّله
      صاحبه ويعيد إرساله (submit_request).
    - submitted/under_review: نطاق department/all فقط (المكتب التنفيذي
      وما فوقه) — نطاق own وحده لا يكفي هنا، حتى لو كان actor هو نفسه
      مقدّم الطلب (لا يقدر يعدّله بعد إرساله، هذا القرار موثّق مسبقًا).
    - pending_approval: **مقفول على الجميع** — لا حتى المكتب التنفيذي.
      الرئيس التنفيذي يقدر يرجعه (return_to_office_request) لو احتاج تعديل،
      لا يعدّله مباشرة.
    - approved/rejected: نهائية، لا تعديل إطلاقًا.

    super_admin مستثنى دائمًا من فحص النطاق (نمط isOwner || isSuperAdmin
    الموثّق بالمشروع) — لا يُقفَل بسبب نطاق ضيق مسجَّل لدوره بالخطأ.
    """
    request = await _get_request_or_raise(db, request_id)
    scope = actor.scope_for("committees.request.update")

    if request.status in (CommitteeRequestStatus.draft, CommitteeRequestStatus.returned):
        is_owner = request.requested_by == actor.user_id
        if not actor.is_super_admin and not is_owner:
            raise CommitteeRequestForbiddenError(
                "لا يقدر إلا مقدّم الطلب على تعديله بهذه الحالة"
            )
    elif request.status in (
        CommitteeRequestStatus.submitted,
        CommitteeRequestStatus.under_review,
    ):
        if scope not in ("department", "all") and not actor.is_super_admin:
            raise CommitteeRequestForbiddenError(
                "تعديل الطلب بعد إرساله متاح فقط للمكتب التنفيذي"
            )
    elif request.status == CommitteeRequestStatus.pending_approval:
        raise CommitteeRequestInvalidTransitionError(
            "الطلب بانتظار اعتماد الرئيس التنفيذي، ولا يمكن تعديله إلا بعد إرجاعه"
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
        "chair_user_id": str(request.chair_user_id) if request.chair_user_id else None,
    }

    if committee_name is not None:
        request.committee_name = committee_name
    if statement is not None:
        request.statement = statement
    request.start_date = new_start
    request.end_date = new_end
    if proposed_member_ids is not None:
        request.proposed_members = await _resolve_members(db, proposed_member_ids)

    if chair_user_id is not None:
        request.chair_user_id = chair_user_id

    # التحقق النهائي: الرئيس (سواء الجديد أو المحفوظ سابقًا) يجب أن يبقى
    # أحد الأعضاء الحاليين — يُعاد فحصه هنا لأن أيًّا من proposed_member_ids
    # أو chair_user_id قد يتغيّر بمعزل عن الآخر بنفس طلب التعديل.
    current_member_ids = {u.user_id for u in request.proposed_members}
    if request.chair_user_id is not None and request.chair_user_id not in current_member_ids:
        raise ValueError("رئيس اللجنة يجب أن يكون أحد الأعضاء المقترحين بالطلب")

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
    """
    draft/returned → submitted (RF-COM-300). الصلاحية المطلوبة على مستوى
    الراوت أصبحت committees.request.update (بعد توحيد صلاحية التعديل —
    مراجعة لاما 2026-08-30)، لكن الإرسال نفسه يبقى فعلًا خاصًا بمالك
    الطلب حصرًا بغض النظر عن اتساع نطاقه — حتى صاحب نطاق 'all' يرسل طلبه
    هو فقط، وليس طلب غيره (الإرسال تسليم الطلب من صاحبه، وليس "مراجعة").
    returned مسموحة أيضًا (وليس فقط draft) — بعد إرجاع المكتب التنفيذي
    الطلب مع سبب، يعدّله مقدّم الطلب ثم يعيد إرساله بنفس هذا الإجراء.
    """
    request = await _get_request_or_raise(db, request_id)

    if request.status not in (CommitteeRequestStatus.draft, CommitteeRequestStatus.returned):
        raise CommitteeRequestInvalidTransitionError(
            "لا يمكن إرسال طلب ليس بحالة مسودة أو مُعاد"
        )
    if request.requested_by != actor.user_id and not actor.is_super_admin:
        raise CommitteeRequestForbiddenError("لا يقدر إلا مقدّم الطلب على إرساله")

    from_status = request.status
    request.status = CommitteeRequestStatus.submitted
    request.return_reason = None  # سبب الإرجاع لم يعد ساريًا بعد إعادة الإرسال (السجل الكامل في audit_logs)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="submit",
        target_type="committee_formation_request",
        target_id=request.request_id,
        metadata={"from_status": from_status.value, "to_status": request.status.value},
    )

    await db.commit()
    return await _get_request_or_raise(db, request.request_id)


async def return_to_admin_request(
    db: AsyncSession, *, actor: User, request_id: uuid.UUID, return_reason: str
) -> CommitteeFormationRequest:
    """
    submitted/under_review → returned. المكتب التنفيذي يرجع الطلب لمقدّمه
    (الادمن) مع سبب إلزامي، بدل تعديله مباشرة — خيار ثانٍ متاح له إلى جانب
    التعديل المباشر (update_request) والرفع للاعتماد (escalate_request).
    مقدّم الطلب يعدّله ويعيد إرساله عبر submit_request.

    الراوت مقيَّد فقط بامتلاك committees.request.update (أي صلاحية، أي
    نطاق) — لكن بعد أن صار مقدّم الطلب نفسه (الادمن) يملك هذه الصلاحية
    أيضًا بنطاق own (منذ migration 0015، ليقدر يعدّل مسودته)، يجب فحص
    النطاق هنا صراحة: الإرجاع فعل مراجع (reviewer) حصرًا، وليس فعل مالك —
    نطاق own وحده لا يكفي (حتى لو كان actor هو مقدّم الطلب نفسه).
    """
    request = await _get_request_or_raise(db, request_id)

    scope = actor.scope_for("committees.request.update")
    if scope not in ("department", "all") and not actor.is_super_admin:
        raise CommitteeRequestForbiddenError("إرجاع الطلب للادمن متاح فقط للمكتب التنفيذي")

    if request.status not in (
        CommitteeRequestStatus.submitted,
        CommitteeRequestStatus.under_review,
    ):
        raise CommitteeRequestInvalidTransitionError(
            "لا يمكن إرجاع طلب للادمن إلا وهو submitted أو under_review"
        )

    request.status = CommitteeRequestStatus.returned
    request.return_reason = return_reason

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="returned",
        target_type="committee_formation_request",
        target_id=request.request_id,
        metadata={"direction": "office_to_admin", "return_reason": return_reason},
    )

    await db.commit()
    return await _get_request_or_raise(db, request.request_id)


async def return_to_office_request(
    db: AsyncSession, *, actor: User, request_id: uuid.UUID, return_reason: str
) -> CommitteeFormationRequest:
    """
    pending_approval → under_review. الرئيس التنفيذي يرجع الطلب للمكتب
    التنفيذي مع سبب إلزامي، بدل اعتماده أو رفضه نهائيًا — المكتب يعدّل
    ويرفعه مرة ثانية عبر escalate_request. مختلف عمدًا عن reject_request
    (رفض نهائي، لا رجعة فيه) — هذا مسار غير نهائي.
    """
    request = await _get_request_or_raise(db, request_id)

    if request.status != CommitteeRequestStatus.pending_approval:
        raise CommitteeRequestInvalidTransitionError(
            "لا يمكن إرجاع طلب للمكتب التنفيذي إلا وهو بانتظار الاعتماد"
        )

    request.status = CommitteeRequestStatus.under_review
    request.return_reason = return_reason

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="returned",
        target_type="committee_formation_request",
        target_id=request.request_id,
        metadata={"direction": "ceo_to_office", "return_reason": return_reason},
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
    request.return_reason = None  # لو كان راجعًا من الرئيس التنفيذي سابقًا، السبب لم يعد ساريًا

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

    # دور "رئيس اللجنة"/"عضو اللجنة" الثابتان (committee_role_slug — راجعي
    # db/migrations/0016 وapp/models/role.py) — يُمنحان هنا تلقائيًا حسب
    # chair_user_id، وليس عبر أي اختيار يدوي؛ عضو واحد رئيس، البقية أعضاء
    # (طلب لاما 2026-08-31: "عند تحديد الأعضاء... يتم تلقائيًا اعتبار كل
    # الأعضاء الآخرين المختارين أعضاء عاديين"). هذا لا يغيّر System Role
    # للمستخدم إطلاقًا — فقط committee_members.committee_role_id.
    chair_role_result = await db.execute(select(Role).where(Role.committee_role_slug == "chair"))
    chair_role = chair_role_result.scalar_one()
    member_role_result = await db.execute(
        select(Role).where(Role.committee_role_slug == "member")
    )
    member_role = member_role_result.scalar_one()

    committee = Committee(
        name=request.committee_name,
        statement=request.statement,
        start_date=request.start_date,
        end_date=request.end_date,
        source_request_id=request.request_id,
        member_roles=[
            CommitteeMember(
                user_id=member.user_id,
                committee_role_id=(
                    chair_role.role_id
                    if member.user_id == request.chair_user_id
                    else member_role.role_id
                ),
            )
            for member in request.proposed_members
        ],
        chair_user_id=request.chair_user_id,
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


async def list_committees(db: AsyncSession, *, actor: User, scope: str) -> list[Committee]:
    """
    عرض اللجان المعتمدة (صلاحية committees.view، بعد إعادة تسمية
    committees.view_authorized — migration 0014). سطح قراءة بسيط فقط
    ليثبت أن الاعتماد أنشأ اللجنة فعليًا — إدارة اللجان الكاملة (مناصب،
    صلاحيات الأعضاء...) خارج نطاق Phase 2 (نطاق مختلف موثّق في BRS بند 6:
    "إدارة أعضاء اللجان والمناصب والصلاحيات").

    النطاق ثلاثي فعليًا الآن (مراجعة لاما 2026-08-30 — الجولة الثالثة،
    "مسؤول إدارة يشوف لجان إدارته بس، مو كل لجان النظام، ومو أي لجنة له
    فيها موظف بس"):
    - own: اللجان التي actor رئيسها أو عضو فيها فعليًا فقط (تصحيح سابق —
      الاسم القديم "عرض اللجان المصرح بها" كان يوهم بهذا الفلتر دون
      تطبيقه فعليًا).
    - department: اللجان التي **رئيسها** من نفس إدارة actor فقط — "لجان
      إدارتي" تعني اللجان اللي إدارتي تقودها، وليس أي لجنة فيها أحد
      موظفيها (ذاك سطح منفصل أخف، راجعي list_department_members_elsewhere
      أدناه). actor بدون إدارة (dep_id=None) يرجع له قائمة فارغة — ما
      فيه إدارة يُقارَن بها أصلًا.
    - all: كل اللجان بدون تصفية.
    """
    stmt = select(Committee).options(selectinload(Committee.members)).order_by(
        Committee.created_at.desc()
    )
    if scope == "own":
        stmt = stmt.where(
            or_(
                Committee.chair_user_id == actor.user_id,
                Committee.members.any(User.user_id == actor.user_id),
            )
        )
    elif scope == "department":
        if actor.dep_id is None:
            return []
        chair = aliased(User)
        stmt = stmt.join(chair, Committee.chair_user_id == chair.user_id).where(
            chair.dep_id == actor.dep_id
        )
    # scope == "all": بدون أي تصفية.
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_committee(
    db: AsyncSession, committee_id: uuid.UUID, *, actor: User, scope: str
) -> Committee:
    """راجعي list_committees أعلاه لتفصيل النطاقات الثلاثة — نفس القاعدة هنا لعنصر واحد."""
    result = await db.execute(
        select(Committee)
        .options(selectinload(Committee.members))
        .where(Committee.committee_id == committee_id)
    )
    committee = result.scalar_one_or_none()
    if committee is None:
        raise CommitteeNotFoundError("اللجنة غير موجودة")
    if scope == "own":
        is_member = committee.chair_user_id == actor.user_id or any(
            m.user_id == actor.user_id for m in committee.members
        )
        if not is_member:
            raise CommitteeForbiddenError("ليست لديك صلاحية لعرض هذه اللجنة")
    elif scope == "department":
        # committee.chair مُحمَّل تلقائيًا (lazy="selectin" على مستوى الـ mapper).
        committee_dep_id = committee.chair.dep_id if committee.chair else None
        if actor.dep_id is None or committee_dep_id != actor.dep_id:
            raise CommitteeForbiddenError("ليست لديك صلاحية لعرض هذه اللجنة")
    return committee


async def get_committee_role_permission_codes(
    db: AsyncSession, *, user_id: uuid.UUID, committee_id: uuid.UUID
) -> set[str]:
    """
    أكواد صلاحيات "دور اللجنة" (رئيس/عضو) الفعلية لـuser_id **داخل هذه
    اللجنة تحديدًا فقط** — جوهر متطلب لاما 2026-08-31 (نطاق Committee Role
    ليس own/department/all، بل عضوية اللجنة نفسها). تُرجع مجموعة فارغة إن
    لم يكن user_id عضوًا في committee_id إطلاقًا (لا رئيسًا ولا عضوًا) —
    لا يُسمح باستخدام صلاحيات لجنة هو ليس عضوًا فيها (متطلب صريح).

    ملاحظة تصميم: صلاحيات دور اللجنة تُقرأ حيًا من role_permissions عبر
    Role.permission_codes (نفس مصدر الحقيقة لصلاحيات System Roles تمامًا،
    ولا يوجد أي نسخ/تجميد لها هنا) — فتعديل صلاحيات "رئيس اللجنة" من صفحة
    "الأدوار والصلاحيات" ينعكس فورًا على كل رؤساء اللجان بكل اللجان، بلا أي
    تعديل يدوي لكل لجنة/عضو (متطلب لاما الصريح: نفس الاختبار المطلوب).
    """
    result = await db.execute(
        select(CommitteeMember).where(
            CommitteeMember.committee_id == committee_id,
            CommitteeMember.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        return set()
    return membership.committee_role.permission_codes


async def user_has_committee_role_view_access(db: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """
    بلاغ لاما 2026-09-01: عضو لجنة (مثلًا "عضو اللجنة") بدون صلاحية
    committees.view على مستوى System Role كان لا يقدر يوصل إطلاقًا لقسم
    "اللجان" بالواجهة (لا القائمة الجانبية تظهر له، ولا GET /committees
    نفسه يرد له أي شيء غير 403) — رغم أنه عضو فعلي بلجنة معتمدة ودور
    لجنته (Committee Role) يملك صلاحية committees.view. السبب: get_committee
    (لجنة واحدة) عنده مسار OR يفحص دور اللجنة، لكن list_committees (القائمة
    كاملة، ونقطة الدخول الفعلية لظهور القسم أصلًا) كان يتطلب فقط
    committees.view على مستوى System Role، بلا أي مسار بديل عبر عضوية اللجنة.

    هذه الدالة تفحص: هل يملك user_id صلاحية committees.view ضمن دور أي
    لجنة هو عضو/رئيس فيها (بغض النظر عن أي لجنة تحديدًا) — تُستخدم كبديل
    لنطاق "own" على مستوى النظام حين لا يملكه المستخدم أصلًا (راجعي
    app/api/v1/committees.py::list_committees وGET /users/me أدناه، وكلاهما
    يحتاج فقط "نعم/لا" هنا، وليس أي لجنة بعينها — list_committees بنطاق
    own أصلًا يُرجع فقط اللجان التي هو رئيسها/عضو فيها، فلا حاجة لأي فلترة
    إضافية بعد التأكد من امتلاك الصلاحية في لجنة واحدة على الأقل).
    """
    stmt = (
        select(func.count())
        .select_from(committee_members)
        .join(RolePermission, RolePermission.role_id == committee_members.c.committee_role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(
            committee_members.c.user_id == user_id,
            Permission.code == "committees.view",
        )
    )
    result = await db.execute(stmt)
    return (result.scalar() or 0) > 0


async def list_department_members_elsewhere(
    db: AsyncSession, *, actor: User, search: str | None = None
) -> list[dict]:
    """
    موظفو إدارة actor المشاركون كأعضاء بلجان **لا تتبع إدارته** (رئيسها من
    إدارة ثانية، أو من غير إدارة معروفة) — مراجعة لاما 2026-08-30 (الجولة
    الثالثة): معلومة تعريفية خفيفة بس (اسم الموظف + اسم اللجنة + الإدارة
    التابعة لها)، وليست وصولًا كامل التفاصيل للجنة نفسها (ذاك محجوز لنطاق
    department الكامل في list_committees حين تكون إدارة actor هي القائدة).
    actor بدون إدارة يرجع له قائمة فارغة.
    """
    if actor.dep_id is None:
        return []

    member = aliased(User)
    chair = aliased(User)
    chair_dept = aliased(Department)

    stmt = (
        select(member, Committee.committee_id, Committee.name, chair_dept.name)
        .select_from(committee_members)
        .join(member, committee_members.c.user_id == member.user_id)
        .join(Committee, committee_members.c.committee_id == Committee.committee_id)
        .outerjoin(chair, Committee.chair_user_id == chair.user_id)
        .outerjoin(chair_dept, chair.dep_id == chair_dept.dep_id)
        .where(member.dep_id == actor.dep_id)
        .where(
            or_(
                Committee.chair_user_id.is_(None),
                chair.dep_id.is_(None),
                chair.dep_id != actor.dep_id,
            )
        )
        .order_by(Committee.created_at.desc())
    )
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                member.first_name.ilike(pattern),
                member.last_name.ilike(pattern),
                Committee.name.ilike(pattern),
                chair_dept.name.ilike(pattern),
            )
        )

    result = await db.execute(stmt)
    return [
        {
            "member": row_member,
            "committee_id": committee_id,
            "committee_name": committee_name,
            "department_name": department_name,
        }
        for row_member, committee_id, committee_name, department_name in result.all()
    ]


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
