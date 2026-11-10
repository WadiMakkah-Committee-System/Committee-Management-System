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


_REJECTION_REASON_NO_MAJORITY = "لم تتحقق نسبة الأغلبية المطلوبة (أصوات «موافق» لا تتجاوز 50% من الأصوات المسجّلة)"

_ABSTAIN_LABEL = "ممتنع"  # راجعي رأس migration 0040 — نص الخيار الثابت المحجوز.

# تحديث 2026-11-03 (قرار صاحب المشروع، بعد مقارنة منصات الحوكمة مثل OnBoard
# وBoardPro وiBabs اللي تعتمد على خيارات ثابتة للقرارات): خيارات التصويت ثابتة
# دائمًا — "موافق" وحده يُحتسب موافقة، و"غير موافق" لا، و"ممتنع" (أدناه) خارج
# مقام الأغلبية. ما عادت رئيسة اللجنة تكتب خيارات أو تعلّم "تُحسب موافقة"، فلا
# يمكن أن تنقلب النتيجة بتعليم خاطئ. القرارات القديمة بخيارات مخصّصة تبقى كما
# هي (صفوفها بـdecision_vote_options لم تُمس)، والحساب بـ_maybe_close_voting
# يعتمد is_approving المخزَّن فيستمر صحيحًا لها.
_FIXED_VOTE_OPTIONS: tuple[tuple[str, bool], ...] = (("موافق", True), ("غير موافق", False))


# ============================== إغلاق التصويت (كسلي) ==============================


def _is_meeting_guest_vote(vote, decision: Decision) -> bool:
    voter = vote.voter  # lazy="selectin" — محمَّل مع الأصوات
    return (
        voter is not None
        and voter.is_guest
        and decision.meeting_id is not None
        and voter.guest_meeting_id == decision.meeting_id
    )


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
    member_votes = {v.user_id: v for v in decision.votes if v.user_id in voter_ids}
    all_voted = len(member_votes) >= len(voter_ids) and len(voter_ids) > 0
    # أصوات ضيوف اجتماع القرار (0047 — قرار لاما 2026-11-10: الضيف يصوّت مثل
    # العضو) تُحسب بالنتيجة، لكن الإغلاق التلقائي ينتظر أعضاء اللجنة فقط —
    # ضيف خرج من الاجتماع لا يعلّق التصويت للأبد.
    votes_by_user = dict(member_votes)
    for v in decision.votes:
        if _is_meeting_guest_vote(v, decision):
            votes_by_user[v.user_id] = v
    deadline_passed = (
        decision.voting_deadline is not None and datetime.now(UTC) >= decision.voting_deadline
    )
    if not all_voted and not deadline_passed:
        return False

    decision.voting_closed_at = datetime.now(UTC)

    has_approving_option = any(opt.is_approving for opt in decision.vote_options)
    if has_approving_option:
        # إضافة 2026-11-01 (خيار "ممتنع" الثابت): أصوات الامتناع لا تُحتسب
        # بمقام نسبة الأغلبية أصلًا — معيار حوكمة شائع (الامتناع ≠ رفض،
        # ولا ≠ موافقة، بل غير محتسَب إطلاقًا). لا تزال "ممتنع" تُحسب ضمن
        # all_voted أعلاه (شارك فعليًا)، لكنها تُستبعد هنا فقط من حساب
        # النسبة. لو امتنع الجميع: total=0 فتبقى majority_achieved=False
        # (نفس مسار "لم تتحقق الأغلبية" العادي، بلا رسالة خاصة إضافية).
        total = sum(1 for v in votes_by_user.values() if not v.option.is_abstain)
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
    voting_deadline: datetime | None,
) -> Decision:
    """
    FR-009: طرح القرار للتصويت — فقط لقرار classification='voting' بحالة
    pending. الخيارات ثابتة (تحديث 2026-11-03): موافق / غير موافق / ممتنع —
    راجعي _FIXED_VOTE_OPTIONS أعلاه.
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

    decision.status = DecisionStatus.voting
    decision.voting_opened_at = datetime.now(UTC)
    decision.voting_deadline = voting_deadline
    decision.vote_options = [
        DecisionVoteOption(label=label, is_approving=is_approving, sort_order=index)
        for index, (label, is_approving) in enumerate(_FIXED_VOTE_OPTIONS)
    ]
    # خيار "ممتنع" ثابت — يُضاف تلقائيًا لكل تصويت (طلب صاحبة المشروع
    # 2026-11-01)، آخر الخيارات ترتيبًا دائمًا. is_approving=false دومًا
    # (لا يُحتسب موافقة)، ومستبعد من مقام الأغلبية أصلًا (راجعي
    # _maybe_close_voting أعلاه).
    decision.vote_options.append(
        DecisionVoteOption(
            label=_ABSTAIN_LABEL, is_approving=False, is_abstain=True, sort_order=len(_FIXED_VOTE_OPTIONS)
        )
    )

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="decision",
        target_id=decision.decision_id,
        metadata={"action": "open_voting", "options": [opt.label for opt in decision.vote_options]},
    )
    await db.commit()
    # بدون إعادة تحميل بعد commit (تحسين أداء 2026-10-24): القرار محمَّل
    # أصلًا بكل ما تعرضه الاستجابة، والخيارات الجديدة كائنات بالجلسة نفسها
    # (معرّفاتها مُرجَعة من INSERT) — إعادة التحميل كانت 5 استعلامات لنفس البيانات.
    return await _redact_votes_if_unauthorized(access, committee, decision)


async def cast_vote(
    db: AsyncSession, *, actor: User, decision_id: uuid.UUID, option_id: uuid.UUID, reason: str | None = None
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

    is_meeting_guest = (
        actor.is_guest
        and decision.meeting_id is not None
        and actor.guest_meeting_id == decision.meeting_id
    )
    if actor.user_id not in _committee_voter_ids(committee) and not is_meeting_guest:
        raise DecisionForbiddenError("التصويت متاح فقط لأعضاء اللجنة المرتبطة بالقرار")

    _maybe_close_voting(decision, committee)
    if decision.status != DecisionStatus.voting or decision.voting_closed_at is not None:
        raise DecisionInvalidStateError("التصويت على هذا القرار مغلق حاليًا")

    chosen_option = next((opt for opt in decision.vote_options if opt.option_id == option_id), None)
    if chosen_option is None:
        raise DecisionValidationError("هذا الخيار غير موجود ضمن خيارات هذا القرار")

    # سبب الامتناع إلزامي فقط لخيار "ممتنع" الثابت (راجعي رأس migration
    # 0040) — يُتجاهل (يُخزَّن None) لأي خيار آخر حتى لو أُرسل بالخطأ.
    if chosen_option.is_abstain:
        reason = (reason or "").strip() or None
        if reason is None:
            raise DecisionValidationError("ذكر سبب الامتناع إلزامي عند اختيار هذا الخيار")
    else:
        reason = None

    existing = next((v for v in decision.votes if v.user_id == actor.user_id), None)
    if existing is not None:
        existing.option_id = option_id
        existing.reason = reason
        existing.voted_at = datetime.now(UTC)
    else:
        db.add(
            DecisionVote(
                decision_id=decision_id, user_id=actor.user_id, option_id=option_id, reason=reason
            )
        )
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
