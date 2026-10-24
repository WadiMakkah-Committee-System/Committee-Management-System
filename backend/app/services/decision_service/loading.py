"""
تحميل القرارات واللجان من قاعدة البيانات — المكان **الوحيد** بوحدة
القرارات الذي يحدد ماذا يُحمَّل مع كل قرار (إعادة هيكلة 2026-10-24).

لماذا: الموديلات تعرّف أغلب العلاقات lazy="selectin"، فـselect(Decision)
بلا خيارات كان يجرّ تلقائيًا شجرة كاملة (اللجنة → رئيسها/أعضاؤها/
member_roles → أدوارهم → صلاحيات كل دور، والمنشئ والمنفذين والمصوّتين →
أدوارهم/مسمياتهم → صلاحياتهم، والاجتماع المصدر → شجرته هو أيضًا). قِيس:
قائمة القرارات = 47 استعلامًا لطلب واحد (كل استعلام ≈ 355ms على الإنتاج).

هنا كل ما يُحمَّل صريح ومحدد بما يحتاجه فعليًا:
- DecisionOut: creator، assignees، vote_options، votes (+ voter وoption لكل صوت).
- فحص الصلاحية: اللجنة + رئيسها (committee_access.system_scope_allows).
- الإغلاق الكسلي للتصويت (_maybe_close_voting): أعضاء اللجنة (من يحق له التصويت).
- الإشعارات (notification_service.notify_decision_*): committee.name وassignees.

أي علاقة غير مذكورة عليها raiseload(sql_only=True): لو حاول كود مستقبلي
قراءتها يفشل فورًا بخطأ واضح بدل أن يطلق استعلامات مخفية.
عدد الاستعلامات ثابت مهما كان عدد القرارات: 5 (رئيسي + أعضاء اللجان +
المنفذون + خيارات التصويت + الأصوات).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, raiseload, selectinload

from app.models.committee import Committee
from app.models.decision import Decision, DecisionVote
from app.services.decision_service.errors import DecisionNotFoundError

_RAISE = {"sql_only": True}


def _committee_options(path) -> tuple:
    """اللجنة + رئيسها (فحص الصلاحية) + أعضاؤها (من يحق له التصويت/المنفذون
    التلقائيون). لا member_roles ولا أدوار/صلاحيات الأعضاء."""
    chair = path.joinedload(Committee.chair)
    members = path.selectinload(Committee.members)
    return (
        path,
        chair,
        chair.raiseload("*", **_RAISE),
        members,
        members.raiseload("*", **_RAISE),
        path.raiseload("*", **_RAISE),
    )


def decision_options() -> tuple:
    creator = joinedload(Decision.creator)
    assignees = selectinload(Decision.assignees)
    votes = selectinload(Decision.votes)
    voter = votes.joinedload(DecisionVote.voter)
    return (
        *_committee_options(joinedload(Decision.committee)),
        creator,
        creator.raiseload("*", **_RAISE),
        assignees,
        assignees.raiseload("*", **_RAISE),
        selectinload(Decision.vote_options),
        votes,
        voter,
        voter.raiseload("*", **_RAISE),
        votes.joinedload(DecisionVote.option),
        raiseload("*", **_RAISE),
    )


def decisions_query(*, reload: bool = False):
    """select(Decision) بخيارات التحميل الصريحة.

    reload=True فقط لإعادة التحميل بعد commit/flush بنفس الدالة
    (populate_existing: تُقرأ القيم الحالية من القاعدة ويُحمَّل ما لم يكن
    محمَّلًا بالكائن الموجود). ليس افتراضيًا لأن الكائنات المرتبطة (اللجنة
    مثلًا) مشتركة بالجلسة بين الخدمات: إعادة تعبئتها مع raiseload تمنع
    علاقات حمّلتها خدمة أخرى قبلها بنفس الطلب."""
    return (
        select(Decision)
        .options(*decision_options())
        .execution_options(populate_existing=reload)
    )


async def load_decision(
    db: AsyncSession, decision_id: uuid.UUID, *, reload: bool = False
) -> Decision:
    result = await db.execute(
        decisions_query(reload=reload).where(Decision.decision_id == decision_id)
    )
    decision = result.unique().scalar_one_or_none()
    if decision is None or decision.is_deleted:
        raise DecisionNotFoundError("القرار غير موجود")
    return decision


async def load_committee(db: AsyncSession, committee_id: uuid.UUID) -> Committee:
    """اللجنة + رئيسها + أعضاؤها (مصدر المنفذين التلقائي عند الإنشاء)."""
    chair = joinedload(Committee.chair)
    members = selectinload(Committee.members)
    result = await db.execute(
        select(Committee)
        .where(Committee.committee_id == committee_id)
        .options(
            chair,
            chair.raiseload("*", **_RAISE),
            members,
            members.raiseload("*", **_RAISE),
            raiseload("*", **_RAISE),
        )
        .execution_options(populate_existing=True)
    )
    committee = result.unique().scalar_one_or_none()
    if committee is None or committee.is_deleted:
        raise DecisionNotFoundError("اللجنة المرتبطة غير موجودة")
    return committee
