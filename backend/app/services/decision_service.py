"""
الهدف:
منطق العمل لوحدة "إدارة القرارات" — القرارات المستقلة فقط (FR-001 مسار
الإصدار المباشر، §5 SRS + §7 BRS). بدون القرارات المستخرجة من اجتماع
بالذكاء الاصطناعي (تُبنى لاحقًا)، وبدون أي ربط بالوثائق (تُبنى من طرف آخر
بالفريق حاليًا). راجعي رأس db/migrations/0021_decisions_schema.sql لكل
الاجتهادات الموثّقة المتفَق عليها مع صاحبة المشروع (2026-09-02).

التفويض: نفس النمط الهجين المطبَّق بوحدة الاجتماعات بالضبط (System Role
scope أو Committee Role permission، عبر committee_service.
get_committee_role_permission_codes) — الأكواد المستخدَمة هنا من كتالوج
0006 الأصلي: decisions.view / decisions.create / decisions.update /
decisions.delete / decisions.vote.open / decisions.vote.cast /
decisions.vote.view_result / decisions.approve.

إغلاق التصويت بالموعد (voting_deadline) يُقيَّم كسليًا (Lazy) عند أي
تفاعل مع القرار (عرض/تصويت/محاولة اعتماد) — لا يوجد Scheduler/Cron
بالمشروع بعد لإغلاقه تلقائيًا بلحظة انتهاء الموعد بالضبط؛ التأخر هنا لا
يتجاوز وقت أول طلب API يلمس القرار بعد الموعد.

تحديث 2026-09-02 (بعد تجربة فعلية من صاحبة المشروع): المنفذون (assignees)
لم يعودوا يُختارون يدويًا عند الإنشاء/التعديل — كل أعضاء اللجنة (بمن فيهم
رئيسها) يُضافون تلقائيًا، بنفس مبدأ مشاركي الاجتماع تمامًا (راجعي
meeting_service._all_committee_members). هذا تراجع عن التصميم الأول
(اختيار يدوي مقيَّد بعضوية اللجنة) — القيد نفسه (لا يمكن إسناد قرار لغير
عضو باللجنة) أصبح تلقائيًا بحكم الاشتقاق، لا حاجة للتحقق منه صراحة.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.committee import Committee, committee_members
from app.models.decision import (
    Decision,
    DecisionClassification,
    DecisionStatus,
    DecisionVote,
    DecisionVoteChoice,
)
from app.models.role import Permission, RolePermission
from app.models.user import User
from app.services import audit_service, committee_service


class DecisionNotFoundError(Exception):
    """القرار غير موجود (أو محذوف) — تُترجَم إلى 404."""


class DecisionForbiddenError(Exception):
    """محاولة إجراء غير مسموح بها لهذا المستخدم تحديدًا — تُترجَم إلى 403."""


class DecisionInvalidStateError(Exception):
    """محاولة إجراء لا تسمح به حالة القرار الحالية — تُترجَم إلى 409."""


class DecisionValidationError(Exception):
    """خطأ تحقق من بيانات العمل — تُترجَم إلى 400."""


_REJECTION_REASON_NO_MAJORITY = "لم تتحقق نسبة الأغلبية المطلوبة (الموافقون لا يتجاوزون 50% من الأصوات المسجّلة)"


# ============================== تحقق الصلاحية ==============================


def _system_scope_allows(actor: User, committee: Committee, code: str) -> bool:
    scope = actor.scope_for(code)
    if scope == "all":
        return True
    if scope == "department":
        committee_dep_id = committee.chair.dep_id if committee.chair else None
        return actor.dep_id is not None and actor.dep_id == committee_dep_id
    return False


async def _has_access(db: AsyncSession, actor: User, committee: Committee, code: str) -> bool:
    if _system_scope_allows(actor, committee, code):
        return True
    committee_role_codes = await committee_service.get_committee_role_permission_codes(
        db, user_id=actor.user_id, committee_id=committee.committee_id
    )
    return code in committee_role_codes


async def _require_access(
    db: AsyncSession, actor: User, committee: Committee, code: str, message: str
) -> None:
    if not await _has_access(db, actor, committee, code):
        raise DecisionForbiddenError(message)


async def _committee_ids_with_committee_role_code(
    db: AsyncSession, actor: User, code: str
) -> set[uuid.UUID]:
    stmt = (
        select(committee_members.c.committee_id)
        .select_from(committee_members)
        .join(RolePermission, RolePermission.role_id == committee_members.c.committee_role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(committee_members.c.user_id == actor.user_id, Permission.code == code)
    )
    result = await db.execute(stmt)
    return set(result.scalars().all())


async def _load_committee(db: AsyncSession, committee_id: uuid.UUID) -> Committee:
    result = await db.execute(select(Committee).where(Committee.committee_id == committee_id))
    committee = result.scalar_one_or_none()
    if committee is None or committee.is_deleted:
        raise DecisionNotFoundError("اللجنة المرتبطة غير موجودة")
    return committee


async def _load_decision(db: AsyncSession, decision_id: uuid.UUID) -> Decision:
    result = await db.execute(select(Decision).where(Decision.decision_id == decision_id))
    decision = result.scalar_one_or_none()
    if decision is None or decision.is_deleted:
        raise DecisionNotFoundError("القرار غير موجود")
    return decision


def _committee_voter_ids(committee: Committee) -> set[uuid.UUID]:
    """كل من يحق له التصويت على قرارات هذه اللجنة — رئيسها وأعضاؤها (FR-010)."""
    ids = {m.user_id for m in committee.members}
    if committee.chair_user_id is not None:
        ids.add(committee.chair_user_id)
    return ids


def _all_committee_members(committee: Committee) -> list[User]:
    """
    كل أعضاء اللجنة (بمن فيهم رئيسها) — مصدر المنفذين التلقائي الوحيد
    الآن (قرار مُعدَّل 2026-09-02: من اختيار يدوي مقيَّد بعضوية اللجنة،
    إلى اشتقاق تلقائي كامل — بنفس مبدأ meeting_service._all_committee_members
    تمامًا). لا تكرار: الرئيس قد يكون أيضًا ضمن committee.members حسب لحظة
    الاستعلام، فنستبعد تكراره صراحة.
    """
    members: dict[uuid.UUID, User] = {m.user_id: m for m in committee.members}
    if committee.chair is not None:
        members[committee.chair_user_id] = committee.chair
    return list(members.values())


# ============================== إغلاق التصويت (كسلي) ==============================


def _maybe_close_voting(decision: Decision, committee: Committee) -> bool:
    """
    يُستدعى عند أي تفاعل مع قرار بحالة 'voting' — راجعي docstring الملف
    بخصوص التقييم الكسلي (Lazy) لعدم وجود Scheduler. يغلق التصويت إذا صوّت
    كل من يحق له التصويت، أو إذا حلّ voting_deadline (إن كان محدَّدًا) —
    أيهما أسبق (يحل تعارض FR-011 مقابل FR-012، راجعي ملاحظة migration (2)).
    يُرجع True إن غيّر شيئًا فعليًا (يحتاج المستدعي commit عندها).
    """
    if decision.status != DecisionStatus.voting or decision.voting_closed_at is not None:
        return False

    voter_ids = _committee_voter_ids(committee)
    votes_by_user = {v.user_id: v for v in decision.votes if v.user_id in voter_ids}
    all_voted = len(votes_by_user) >= len(voter_ids) and len(voter_ids) > 0
    deadline_passed = (
        decision.voting_deadline is not None and datetime.now(UTC) >= decision.voting_deadline
    )
    if not all_voted and not deadline_passed:
        return False

    decision.voting_closed_at = datetime.now(UTC)
    total = len(votes_by_user)
    approve_count = sum(1 for v in votes_by_user.values() if v.choice.value == "approve")
    majority_achieved = total > 0 and (approve_count / total) > 0.5

    if not majority_achieved:
        decision.status = DecisionStatus.rejected
        decision.rejection_reason = _REJECTION_REASON_NO_MAJORITY
    # وإلا: يبقى status == 'voting' مع voting_closed_at محدَّدًا — بانتظار
    # اعتماد رئيس اللجنة اليدوي الصريح (FR-013)، وليس اعتمادًا تلقائيًا.
    return True


# ============================== CRUD ==============================


async def create_decision(
    db: AsyncSession,
    *,
    actor: User,
    committee_id: uuid.UUID,
    title: str,
    classification: DecisionClassification,
    start_date: date,
    end_date: date,
) -> Decision:
    """FR-001 (إصدار مباشر) + FR-005 (تسجيل البيانات) + FR-006 (التصنيف)."""
    committee = await _load_committee(db, committee_id)
    await _require_access(
        db, actor, committee, "decisions.create", "ليست لديك صلاحية إنشاء قرار لهذه اللجنة"
    )

    decision = Decision(
        committee_id=committee_id,
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
    return await _load_decision(db, decision.decision_id)


async def get_decision(db: AsyncSession, decision_id: uuid.UUID, *, actor: User) -> Decision:
    decision = await _load_decision(db, decision_id)
    committee = await _load_committee(db, decision.committee_id)
    await _require_access(
        db, actor, committee, "decisions.view", "ليست لديك صلاحية لعرض هذا القرار"
    )
    changed = _maybe_close_voting(decision, committee)
    if changed:
        await db.commit()
        await db.refresh(decision)
    return decision


async def list_decisions(db: AsyncSession, *, actor: User) -> list[Decision]:
    """نفس منطق الوصول المزدوج بوحدة الاجتماعات (System Role scope أو Committee Role permission)."""
    scope = actor.scope_for("decisions.view")
    stmt = select(Decision).where(Decision.deleted_at.is_(None)).order_by(
        Decision.created_at.desc()
    )

    if scope == "all":
        pass
    elif scope == "department":
        if actor.dep_id is None:
            return []
        chair = aliased(User)
        stmt = (
            stmt.join(Committee, Decision.committee_id == Committee.committee_id)
            .join(chair, Committee.chair_user_id == chair.user_id)
            .where(chair.dep_id == actor.dep_id)
        )
    else:
        committee_ids = await _committee_ids_with_committee_role_code(
            db, actor, "decisions.view"
        )
        if not committee_ids:
            return []
        stmt = stmt.where(Decision.committee_id.in_(committee_ids))

    result = await db.execute(stmt)
    decisions = list(result.scalars().unique().all())

    changed = False
    for decision in decisions:
        committee = await _load_committee(db, decision.committee_id)
        if _maybe_close_voting(decision, committee):
            changed = True
    if changed:
        await db.commit()

    return decisions


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
    decision = await _load_decision(db, decision_id)
    committee = await _load_committee(db, decision.committee_id)
    await _require_access(
        db, actor, committee, "decisions.update", "ليست لديك صلاحية تعديل هذا القرار"
    )

    if decision.status != DecisionStatus.pending:
        raise DecisionInvalidStateError(
            "لا يمكن تعديل القرار بعد فتح التصويت أو اعتماده أو رفضه"
        )

    effective_start = start_date if start_date is not None else decision.start_date
    effective_end = end_date if end_date is not None else decision.end_date
    if effective_end < effective_start:
        raise DecisionValidationError("تاريخ نهاية التنفيذ يجب أن يكون بعد تاريخ البداية أو يساويه")

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
    return await _load_decision(db, decision.decision_id)


async def delete_decision(db: AsyncSession, *, actor: User, decision_id: uuid.UUID) -> None:
    """FR-018: حذف — متاح فقط بحالة pending (Soft Delete)."""
    decision = await _load_decision(db, decision_id)
    committee = await _load_committee(db, decision.committee_id)
    await _require_access(
        db, actor, committee, "decisions.delete", "ليست لديك صلاحية حذف هذا القرار"
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


# ============================== التصويت والاعتماد ==============================


async def open_voting(
    db: AsyncSession, *, actor: User, decision_id: uuid.UUID, voting_deadline: datetime | None
) -> Decision:
    """FR-009: طرح القرار للتصويت — فقط لقرار classification='voting' بحالة pending."""
    decision = await _load_decision(db, decision_id)
    committee = await _load_committee(db, decision.committee_id)
    await _require_access(
        db, actor, committee, "decisions.vote.open", "ليست لديك صلاحية طرح هذا القرار للتصويت"
    )

    if decision.classification != DecisionClassification.voting:
        raise DecisionInvalidStateError("هذا القرار مصنَّف كنهائي — لا يُطرح للتصويت")
    if decision.status != DecisionStatus.pending:
        raise DecisionInvalidStateError("لا يمكن طرح القرار للتصويت من حالته الحالية")

    decision.status = DecisionStatus.voting
    decision.voting_opened_at = datetime.now(UTC)
    decision.voting_deadline = voting_deadline

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="decision",
        target_id=decision.decision_id,
        metadata={"action": "open_voting"},
    )
    await db.commit()
    return await _load_decision(db, decision.decision_id)


async def cast_vote(
    db: AsyncSession, *, actor: User, decision_id: uuid.UUID, choice: DecisionVoteChoice
) -> Decision:
    """FR-010: تصويت عضو اللجنة (بمن فيه رئيسها) — قابل للتغيير طالما التصويت مفتوحًا."""
    decision = await _load_decision(db, decision_id)
    committee = await _load_committee(db, decision.committee_id)
    await _require_access(
        db, actor, committee, "decisions.vote.cast", "ليست لديك صلاحية التصويت على هذا القرار"
    )

    if actor.user_id not in _committee_voter_ids(committee):
        raise DecisionForbiddenError("التصويت متاح فقط لأعضاء اللجنة المرتبطة بالقرار")

    _maybe_close_voting(decision, committee)
    if decision.status != DecisionStatus.voting or decision.voting_closed_at is not None:
        raise DecisionInvalidStateError("التصويت على هذا القرار مغلق حاليًا")

    existing = next((v for v in decision.votes if v.user_id == actor.user_id), None)
    if existing is not None:
        existing.choice = choice
        existing.voted_at = datetime.now(UTC)
    else:
        db.add(DecisionVote(decision_id=decision_id, user_id=actor.user_id, choice=choice))
        await db.flush()
        await db.refresh(decision, attribute_names=["votes"])

    _maybe_close_voting(decision, committee)
    await db.commit()
    return await _load_decision(db, decision.decision_id)


async def approve_decision(db: AsyncSession, *, actor: User, decision_id: uuid.UUID) -> Decision:
    """
    FR-007 (نهائي) / FR-013 (تصويت بعد تحقق الأغلبية) — الفعل الوحيد الذي
    يُحوّل القرار فعليًا إلى 'approved'؛ حتى مع تحقق الأغلبية، لا اعتماد
    تلقائي بدون هذا الاستدعاء الصريح من رئيس اللجنة (أو من يملك الصلاحية).
    """
    decision = await _load_decision(db, decision_id)
    committee = await _load_committee(db, decision.committee_id)
    await _require_access(
        db, actor, committee, "decisions.approve", "ليست لديك صلاحية اعتماد هذا القرار"
    )

    if decision.classification == DecisionClassification.final:
        if decision.status != DecisionStatus.pending:
            raise DecisionInvalidStateError("لا يمكن اعتماد القرار من حالته الحالية")
    else:
        _maybe_close_voting(decision, committee)
        if decision.status == DecisionStatus.rejected:
            raise DecisionInvalidStateError("تم رفض هذا القرار تلقائيًا لعدم تحقق الأغلبية")
        if decision.status != DecisionStatus.voting or decision.voting_closed_at is None:
            raise DecisionInvalidStateError("التصويت لم يكتمل بعد — لا يمكن الاعتماد الآن")

    decision.status = DecisionStatus.approved

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="decision",
        target_id=decision.decision_id,
        metadata={"action": "approve"},
    )
    await db.commit()
    return await _load_decision(db, decision.decision_id)
