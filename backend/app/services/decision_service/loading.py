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
from sqlalchemy.orm.attributes import set_committed_value

from app.models.committee import Committee, committee_members
from app.models.user import User
from app.models.decision import Decision, DecisionVote
from app.services.decision_service.errors import DecisionNotFoundError

_RAISE = {"sql_only": True}


def _committee_options(path, *, with_members: bool = True) -> tuple:
    """اللجنة + رئيسها (فحص الصلاحية) + أعضاؤها (من يحق له التصويت/المنفذون
    التلقائيون). لا member_roles ولا أدوار/صلاحيات الأعضاء.

    with_members=False (القوائم — تحسين أداء 2026-10-25): الأعضاء لا يُحتاجون
    إلا لإغلاق تصويت مفتوح، فتُحمَّل لاحقًا للجان القرارات المفتوحة للتصويت
    فقط عبر ensure_committee_members (ولا استعلام إطلاقًا لو ما فيه تصويت مفتوح)."""
    chair = path.joinedload(Committee.chair)
    options: list = [path, chair, chair.raiseload("*", **_RAISE)]
    if with_members:
        members = path.selectinload(Committee.members)
        options += [members, members.raiseload("*", **_RAISE)]
    options.append(path.raiseload("*", **_RAISE))
    return tuple(options)


def decision_options(*, with_assignees: bool = True, with_members: bool = True) -> tuple:
    creator = joinedload(Decision.creator)
    assignees = (selectinload(Decision.assignees),) if with_assignees else ()
    votes = selectinload(Decision.votes)
    voter = votes.joinedload(DecisionVote.voter)
    return (
        *_committee_options(joinedload(Decision.committee), with_members=with_members),
        creator,
        creator.raiseload("*", **_RAISE),
        *assignees,
        *(a.raiseload("*", **_RAISE) for a in assignees),
        selectinload(Decision.vote_options),
        votes,
        voter,
        voter.raiseload("*", **_RAISE),
        votes.joinedload(DecisionVote.option),
        raiseload("*", **_RAISE),
    )


def decisions_query(*, reload: bool = False, with_assignees: bool = True, with_members: bool = True):
    """select(Decision) بخيارات التحميل الصريحة.

    reload=True فقط لإعادة التحميل بعد commit/flush بنفس الدالة
    (populate_existing: تُقرأ القيم الحالية من القاعدة ويُحمَّل ما لم يكن
    محمَّلًا بالكائن الموجود). ليس افتراضيًا لأن الكائنات المرتبطة (اللجنة
    مثلًا) مشتركة بالجلسة بين الخدمات: إعادة تعبئتها مع raiseload تمنع
    علاقات حمّلتها خدمة أخرى قبلها بنفس الطلب."""
    return (
        select(Decision)
        .options(*decision_options(with_assignees=with_assignees, with_members=with_members))
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


async def ensure_committee_members(db: AsyncSession, committees) -> None:
    """يحمّل Committee.members (بأعمدة المستخدم فقط) للجان اللي ما تحمّلت
    أعضاؤها بعد — استعلام واحد لكل اللجان. يكتبها كقيمة محمَّلة
    (set_committed_value) بدل populate_existing حتى لا يمس أي علاقة أخرى
    حمّلتها خدمة ثانية لنفس اللجنة بنفس الجلسة. نفس صفوف selectinload(
    Committee.members) بالضبط (نفس جدول committee_members)."""
    pending = {c.committee_id: c for c in committees if "members" not in c.__dict__}
    if not pending:
        return
    result = await db.execute(
        select(committee_members.c.committee_id, User)
        .join(User, User.user_id == committee_members.c.user_id)
        .where(committee_members.c.committee_id.in_(pending))
        .options(raiseload("*", **_RAISE))
    )
    by_committee: dict[uuid.UUID, list[User]] = {cid: [] for cid in pending}
    for committee_id, user in result.all():
        by_committee[committee_id].append(user)
    for committee_id, committee in pending.items():
        set_committed_value(committee, "members", by_committee[committee_id])
