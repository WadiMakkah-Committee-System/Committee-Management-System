"""
التصويت والاعتماد (FR-007/009/010/011/012/013) + الإغلاق الكسلي للتصويت.

إغلاق التصويت بالموعد (voting_deadline) يُقيَّم كسليًا عند أي تفاعل مع
القرار — راجعي docstring الحزمة (decision_service/__init__.py).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.committee import Committee
from app.models.decision import (
    Decision,
    DecisionClassification,
    DecisionStatus,
    DecisionVote,
    DecisionVoteOption,
)
from app.models.user import User
from app.services import audit_service
from app.services.committee_access import CommitteeAccess
from app.services.decision_service.access import (
    _committee_voter_ids,
    _redact_votes_if_unauthorized,
    _require_access,
)
from app.services.decision_service.errors import (
    DecisionForbiddenError,
    DecisionInvalidStateError,
    DecisionValidationError,
)
from app.services.decision_service.loading import load_decision


_REJECTION_REASON_NO_MAJORITY = "لم تتحقق نسبة الأغلبية المطلوبة (الخيارات المعلَّمة كموافقة لا تتجاوز 50% من الأصوات المسجّلة)"


# ============================== إغلاق التصويت (كسلي) ==============================


def _maybe_close_voting(decision: Decision, committee: Committee) -> bool:
    """
    يُستدعى عند أي تفاعل مع قرار بحالة 'voting' — راجعي docstring الملف
    بخصوص التقييم الكسلي (Lazy) لعدم وجود Scheduler. يغلق التصويت إذا صوّت
    كل من يحق له التصويت، أو إذا حلّ voting_deadline (إن كان محدَّدًا) —
    أيهما أسبق (يحل تعارض FR-011 مقابل FR-012، راجعي ملاحظة migration
    0021 (2)). يُرجع True إن غيّر شيئًا فعليًا (يحتاج المستدعي commit عندها).

    حساب الأغلبية مع خيارات حرة (راجعي رأس الملف وrأس migration 0025):
    - فيه خيار is_approving=true واحد على الأقل → المجموع مقابل الإجمالي،
      تعميم للقاعدة الثنائية القديمة (موافق/غير موافق) وليست قاعدة جديدة.
    - ولا خيار معلَّم إطلاقًا → استطلاع رأي بحت، لا رفض تلقائي (يبقى
      'voting' بانتظار اعتماد يدوي بتقدير رئيسة اللجنة الشخصي).
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

    has_approving_option = any(opt.is_approving for opt in decision.vote_options)
    if has_approving_option:
        total = len(votes_by_user)
        approve_count = sum(1 for v in votes_by_user.values() if v.option.is_approving)
        majority_achieved = total > 0 and (approve_count / total) > 0.5
        if not majority_achieved:
            decision.status = DecisionStatus.rejected
            decision.rejection_reason = _REJECTION_REASON_NO_MAJORITY
        # وإلا: يبقى status == 'voting' مع voting_closed_at محدَّدًا — بانتظار
        # اعتماد رئيس اللجنة اليدوي الصريح (FR-013)، وليس اعتمادًا تلقائيًا.
    # وإلا (استطلاع رأي بحت بلا أي خيار "موافقة"): لا شيء آخر يُفعل هنا —
    # يبقى 'voting' مع voting_closed_at محدَّدًا فقط، بانتظار قرار رئيسة
    # اللجنة اليدوي بالكامل (لا خوارزمية تحسم بدلًا عنها).
    return True


# ============================== التصويت والاعتماد ==============================


async def open_voting(
    db: AsyncSession,
    *,
    actor: User,
    decision_id: uuid.UUID,
    options: list[dict],
    voting_deadline: datetime | None,
) -> Decision:
    """
    FR-009: طرح القرار للتصويت — فقط لقرار classification='voting' بحالة
    pending. الخيارات (options) تحدّدها رئيسة اللجنة هنا بالكامل (قرار
    صريح 2026-09-07) — كل عنصر {"label": نص حر, "is_approving": bool}.
    يُتحقَّق من عدم تكرار label بين الخيارات (منعًا لالتباس عند التصويت).
    """
    access = CommitteeAccess(db, actor)
    decision = await load_decision(db, decision_id)
    committee = decision.committee  # محمَّلة مع القرار (loading.decision_options)
    await _require_access(
        access, committee, "decisions.vote.open", "ليست لديك صلاحية طرح هذا القرار للتصويت"
    )

    if decision.classification != DecisionClassification.voting:
        raise DecisionInvalidStateError("هذا القرار مصنَّف كنهائي — لا يُطرح للتصويت")
    if decision.status != DecisionStatus.pending:
        raise DecisionInvalidStateError("لا يمكن طرح القرار للتصويت من حالته الحالية")

    labels = [opt["label"].strip() for opt in options]
    if len(labels) != len(set(labels)):
        raise DecisionValidationError("لا يمكن تكرار نفس نص الخيار أكثر من مرة")

    decision.status = DecisionStatus.voting
    decision.voting_opened_at = datetime.now(UTC)
    decision.voting_deadline = voting_deadline
    decision.vote_options = [
        DecisionVoteOption(
            label=opt["label"].strip(),
            is_approving=opt.get("is_approving", False),
            sort_order=index,
        )
        for index, opt in enumerate(options)
    ]

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="decision",
        target_id=decision.decision_id,
        metadata={"action": "open_voting", "options": labels},
    )
    await db.commit()
    # بدون إعادة تحميل بعد commit (تحسين أداء 2026-10-24): القرار محمَّل
    # أصلًا بكل ما تعرضه الاستجابة، والخيارات الجديدة كائنات بالجلسة نفسها
    # (معرّفاتها مُرجَعة من INSERT) — إعادة التحميل كانت 5 استعلامات لنفس البيانات.
    return await _redact_votes_if_unauthorized(access, committee, decision)


async def cast_vote(
    db: AsyncSession, *, actor: User, decision_id: uuid.UUID, option_id: uuid.UUID
) -> tuple[Decision, bool]:
    """
    FR-010: تصويت عضو اللجنة (بمن فيه رئيسها) لخيار محدَّد من خيارات هذا
    القرار تحديدًا — قابل للتغيير طالما التصويت مفتوحًا. يُرجع (القرار،
    just_rejected) — راجعي docstring get_decision لتفصيل معنى just_rejected
    ولماذا (غالبًا هذا التصويت هو آخر صوت أكمل مشاركة الجميع، فيغلق
    التصويت ويرفض القرار في نفس هذا الاستدعاء تحديدًا).
    """
    access = CommitteeAccess(db, actor)
    decision = await load_decision(db, decision_id)
    committee = decision.committee  # محمَّلة مع القرار (loading.decision_options)
    await _require_access(
        access, committee, "decisions.vote.cast", "ليست لديك صلاحية التصويت على هذا القرار"
    )

    if actor.user_id not in _committee_voter_ids(committee):
        raise DecisionForbiddenError("التصويت متاح فقط لأعضاء اللجنة المرتبطة بالقرار")

    _maybe_close_voting(decision, committee)
    if decision.status != DecisionStatus.voting or decision.voting_closed_at is not None:
        raise DecisionInvalidStateError("التصويت على هذا القرار مغلق حاليًا")

    if not any(opt.option_id == option_id for opt in decision.vote_options):
        raise DecisionValidationError("هذا الخيار غير موجود ضمن خيارات هذا القرار")

    existing = next((v for v in decision.votes if v.user_id == actor.user_id), None)
    if existing is not None:
        existing.option_id = option_id
        existing.voted_at = datetime.now(UTC)
    else:
        db.add(DecisionVote(decision_id=decision_id, user_id=actor.user_id, option_id=option_id))
    # إعادة تحميل واحدة بعد flush (في الحالتين) تكفي: الأصوات بخياراتها
    # الحالية جاهزة لحساب الإغلاق وللاستجابة معًا — كانت إعادة تحميل ثانية
    # بعد commit لنفس البيانات (تحسين أداء 2026-10-24). تغيير خيار صوت
    # موجود يحتاجها أيضًا: vote.option المحمَّلة كانت ستبقى على الخيار القديم.
    await db.flush()
    decision = await load_decision(db, decision_id, reload=True)

    just_closed = _maybe_close_voting(decision, committee)
    just_rejected = just_closed and decision.status == DecisionStatus.rejected
    await db.commit()
    final_decision = await _redact_votes_if_unauthorized(access, committee, decision)
    return final_decision, just_rejected


async def approve_decision(db: AsyncSession, *, actor: User, decision_id: uuid.UUID) -> Decision:
    """
    FR-007 (نهائي) / FR-013 (تصويت بعد تحقق الأغلبية، أو استطلاع رأي بحت
    بلا خيار موافقة معلَّم — راجعي docstring الملف) — الفعل الوحيد الذي
    يُحوّل القرار فعليًا إلى 'approved'؛ لا اعتماد تلقائي أبدًا بدون هذا
    الاستدعاء الصريح من رئيس اللجنة (أو من يملك الصلاحية).
    """
    access = CommitteeAccess(db, actor)
    decision = await load_decision(db, decision_id)
    committee = decision.committee  # محمَّلة مع القرار (loading.decision_options)
    await _require_access(
        access, committee, "decisions.approve", "ليست لديك صلاحية اعتماد هذا القرار"
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
    # بدون إعادة تحميل بعد commit (تحسين أداء 2026-10-24): التغييرات هنا
    # أعمدة بالقرار نفسه (أو قائمة منفذين من كائنات محمَّلة أصلًا)، والكائن
    # يحتفظ بقيمه بعد commit (expire_on_commit=False) — إعادة التحميل كانت
    # 5 استعلامات إضافية لنفس البيانات.
    return await _redact_votes_if_unauthorized(access, committee, decision)
