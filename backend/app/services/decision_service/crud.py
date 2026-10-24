"""
إنشاء/عرض/قائمة/تعديل/حذف القرارات (FR-001/005/006/017/018).

قائمة القرارات (إعادة هيكلة 2026-10-24): عدد استعلامات ثابت مهما كان عدد
القرارات — التحميل كله من loading.decisions_query()، والصلاحيات عبر
CommitteeAccess (أكواد أدوار اللجان مرة واحدة للطلب كله، بدل استعلامين
لكل قرار). شكل الاستجابة (DecisionOut) لم يتغيّر: لوحة القرارات داخل غرفة
الاجتماع تستخدم الأصوات والخيارات من القائمة مباشرة.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.committee_period import assert_committee_not_expired, assert_within_committee_period
from app.models.committee import Committee
from app.models.decision import Decision, DecisionClassification, DecisionStatus
from app.models.meeting import Meeting
from app.models.user import User
from app.services import audit_service
from app.services.committee_access import CommitteeAccess
from app.services.decision_service.access import (
    _all_committee_members,
    _can_see_pending_decision,
    _redact_votes_if_unauthorized,
    _require_access,
)
from app.services.decision_service.errors import (
    DecisionInvalidStateError,
    DecisionNotFoundError,
    DecisionValidationError,
)
from app.services.decision_service.loading import decisions_query, load_committee, load_decision
from app.services.decision_service.voting import _maybe_close_voting


async def create_decision(
    db: AsyncSession,
    *,
    actor: User,
    committee_id: uuid.UUID,
    title: str,
    classification: DecisionClassification,
    start_date: date,
    end_date: date,
    meeting_id: uuid.UUID | None = None,
) -> Decision:
    """FR-001 (إصدار مباشر) + FR-005 (تسجيل البيانات) + FR-006 (التصنيف).

    meeting_id (جديد، راجعي 0026_meeting_realtime.sql): لو أُرسل من لوحة
    "القرارات" داخل غرفة الاجتماع — يُتحقَّق أنه ينتمي لنفس اللجنة قبل
    الربط (منع ربط قرار لجنة بموعد اجتماع لجنة أخرى بالخطأ)."""
    access = CommitteeAccess(db, actor)
    committee = await load_committee(db, committee_id)
    await _require_access(
        access, committee, "decisions.create", "ليست لديك صلاحية إنشاء قرار لهذه اللجنة"
    )
    assert_committee_not_expired(committee, action_label="إصدار قرار جديد لهذه اللجنة")
    assert_within_committee_period(committee, field_label="تاريخ بداية القرار", value=start_date)
    assert_within_committee_period(committee, field_label="تاريخ نهاية القرار", value=end_date)

    if meeting_id is not None:
        # عمودان فقط (لا كائن Meeting كامل بشجرة علاقاته selectin).
        meeting_result = await db.execute(
            select(Meeting.committee_id, Meeting.deleted_at).where(Meeting.meeting_id == meeting_id)
        )
        meeting = meeting_result.one_or_none()
        if meeting is None or meeting.deleted_at is not None or meeting.committee_id != committee_id:
            raise DecisionValidationError("الاجتماع المحدَّد لا ينتمي لنفس اللجنة")

    decision = Decision(
        committee_id=committee_id,
        meeting_id=meeting_id,
        title=title,
        classification=classification,
        start_date=start_date,
        end_date=end_date,
        created_by=actor.user_id,
        assignees=_all_committee_members(committee),
    )
    db.add(decision)
    await db.flush()

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="create",
        target_type="decision",
        target_id=decision.decision_id,
    )
    await db.commit()
    return await _redact_votes_if_unauthorized(
        access, committee, await load_decision(db, decision.decision_id, reload=True)
    )


async def get_decision(
    db: AsyncSession, decision_id: uuid.UUID, *, actor: User
) -> tuple[Decision, bool]:
    """
    يُرجع (القرار، just_rejected) — just_rejected=True فقط إذا تسبَّب هذا
    الاستدعاء تحديدًا (إغلاق كسلي بموعد التصويت) برفض القرار الآن (وليس
    قرارًا كان مرفوضًا أصلًا من قبل) — تستخدمه طبقة الـAPI لإطلاق
    notify_decision_rejected مرة واحدة بالضبط عند حدوثه فعليًا.
    """
    access = CommitteeAccess(db, actor)
    decision = await load_decision(db, decision_id)
    committee = decision.committee  # محمَّلة مع القرار (loading.decision_options)
    await _require_access(
        access, committee, "decisions.view", "ليست لديك صلاحية لعرض هذا القرار"
    )
    if decision.status == DecisionStatus.pending and not await _can_see_pending_decision(access, committee):
        # نفس رسالة "غير موجود" العادية (وليس 403) عمدًا — لا داعي لكشف
        # وجود قرار لم يُتَّخذ بشأنه شيء بعد لمن لا يديره أصلًا.
        raise DecisionNotFoundError("القرار غير موجود")
    changed = _maybe_close_voting(decision, committee)
    just_rejected = changed and decision.status == DecisionStatus.rejected
    if changed:
        await db.commit()
    return await _redact_votes_if_unauthorized(access, committee, decision), just_rejected


async def list_decisions(
    db: AsyncSession,
    *,
    actor: User,
    meeting_id: uuid.UUID | None = None,
    access: CommitteeAccess | None = None,
    with_assignees: bool = True,
) -> list[Decision]:
    """نفس منطق الوصول المزدوج بوحدة الاجتماعات (System Role scope أو Committee
    Role permission). meeting_id (جديد): تفلتر لقرارات اجتماع واحد بالذات —
    تستخدمها لوحة "القرارات" داخل غرفة الاجتماع (بخلاف شاشة "إدارة القرارات"
    العامة اللي تستدعيها بلا meeting_id).

    with_assignees=False: لمن لا يعرض المنفذين (لوحة التحكم) — استعلام أقل.

    access (اختياري — تحسين أداء 2026-10-24): CommitteeAccess مشترك من
    المستدعي (لوحة التحكم تستدعي عدة قوائم بنفس الطلب) حتى تُجلب أكواد أدوار
    لجان المستخدم مرة واحدة للطلب كله بدل مرة لكل قائمة. نفس القاعدة حرفيًا."""
    access = access or CommitteeAccess(db, actor)
    scope = actor.scope_for("decisions.view")
    stmt = decisions_query(with_assignees=with_assignees).where(Decision.deleted_at.is_(None)).order_by(
        Decision.created_at.desc()
    )
    if meeting_id is not None:
        stmt = stmt.where(Decision.meeting_id == meeting_id)

    # إصلاح 2026-09-13 (بلاغ لاما — رئيسة لجنة أنشأت قرارًا فظهر لها ولم
    # يظهر لبقية الأعضاء): "department" كان حصريًا (elif) فيُقصي مسار
    # Committee Role بالكامل — بنفس العلة المُصلَحة بـ
    # meeting_service.list_meetings (راجعيها لتفصيل السبب الجذري). الحل
    # نفسه: شرطان مستقلّان يُدمَجان بـOR بدل الإقصاء المتبادل.
    if scope != "all":
        conditions = []
        if scope == "department" and actor.dep_id is not None:
            chair = aliased(User)
            dept_committee_ids = (
                select(Committee.committee_id)
                .join(chair, Committee.chair_user_id == chair.user_id)
                .where(chair.dep_id == actor.dep_id)
            )
            conditions.append(Decision.committee_id.in_(dept_committee_ids))

        committee_ids = await access.committee_ids_with_code("decisions.view")
        if committee_ids:
            conditions.append(Decision.committee_id.in_(committee_ids))

        if not conditions:
            return []
        stmt = stmt.where(or_(*conditions))

    result = await db.execute(stmt)
    decisions = list(result.scalars().unique().all())

    changed = False
    redacted: list[Decision] = []
    for decision in decisions:
        committee = decision.committee  # محمَّلة مع القرار (loading.decision_options)
        if decision.status == DecisionStatus.pending and not await _can_see_pending_decision(
            access, committee
        ):
            continue
        if _maybe_close_voting(decision, committee):
            changed = True
        redacted.append(await _redact_votes_if_unauthorized(access, committee, decision))
    if changed:
        await db.commit()

    return redacted


async def update_decision(
    db: AsyncSession,
    *,
    actor: User,
    decision_id: uuid.UUID,
    title: str | None,
    classification: DecisionClassification | None,
    start_date: date | None,
    end_date: date | None,
) -> Decision:
    """FR-017: تعديل — متاح فقط بحالة pending (قبل فتح التصويت أو الاعتماد المباشر)."""
    access = CommitteeAccess(db, actor)
    decision = await load_decision(db, decision_id)
    committee = decision.committee  # محمَّلة مع القرار (loading.decision_options)
    await _require_access(
        access, committee, "decisions.update", "ليست لديك صلاحية تعديل هذا القرار"
    )

    if decision.status != DecisionStatus.pending:
        raise DecisionInvalidStateError(
            "لا يمكن تعديل القرار بعد فتح التصويت أو اعتماده أو رفضه"
        )

    effective_start = start_date if start_date is not None else decision.start_date
    effective_end = end_date if end_date is not None else decision.end_date
    if effective_end < effective_start:
        raise DecisionValidationError("تاريخ نهاية التنفيذ يجب أن يكون بعد تاريخ البداية أو يساويه")
    assert_within_committee_period(committee, field_label="تاريخ بداية القرار", value=effective_start)
    assert_within_committee_period(committee, field_label="تاريخ نهاية القرار", value=effective_end)

    if title is not None:
        decision.title = title
    if classification is not None:
        decision.classification = classification
    if start_date is not None:
        decision.start_date = start_date
    if end_date is not None:
        decision.end_date = end_date
    # المنفذون تُعاد إعادة اشتقاقهم دائمًا من عضوية اللجنة الحالية (قد
    # تكون تغيّرت منذ الإنشاء) — بلا حاجة لحقل مُدخَل، بنفس منطق الإنشاء.
    decision.assignees = _all_committee_members(committee)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="decision",
        target_id=decision.decision_id,
    )
    await db.commit()
    # بدون إعادة تحميل بعد commit (تحسين أداء 2026-10-24): التغييرات هنا
    # أعمدة بالقرار نفسه (أو قائمة منفذين من كائنات محمَّلة أصلًا)، والكائن
    # يحتفظ بقيمه بعد commit (expire_on_commit=False) — إعادة التحميل كانت
    # 5 استعلامات إضافية لنفس البيانات.
    return await _redact_votes_if_unauthorized(access, committee, decision)


async def delete_decision(db: AsyncSession, *, actor: User, decision_id: uuid.UUID) -> None:
    """FR-018: حذف — متاح فقط بحالة pending (Soft Delete)."""
    access = CommitteeAccess(db, actor)
    decision = await load_decision(db, decision_id)
    committee = decision.committee  # محمَّلة مع القرار (loading.decision_options)
    await _require_access(
        access, committee, "decisions.delete", "ليست لديك صلاحية حذف هذا القرار"
    )

    if decision.status != DecisionStatus.pending:
        raise DecisionInvalidStateError(
            "لا يمكن حذف القرار بعد فتح التصويت أو اعتماده أو رفضه"
        )

    decision.deleted_at = datetime.now(UTC)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="delete",
        target_type="decision",
        target_id=decision.decision_id,
    )
    await db.commit()
