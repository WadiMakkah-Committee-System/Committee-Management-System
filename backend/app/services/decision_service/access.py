"""
تحقق الصلاحية بوحدة القرارات (إعادة هيكلة 2026-10-24).

النمط الهجين (System Role scope أو Committee Role permission) صار مشتركًا
بكل الوحدات في app/services/committee_access.py — هنا فقط قواعد القرارات
الخاصة: من يحق له التصويت، المنفذون التلقائيون، رؤية القرار المعلّق،
وخصوصية نتيجة التصويت. الأكواد من كتالوج 0006: decisions.view /
decisions.create / decisions.update / decisions.delete / decisions.vote.open /
decisions.vote.cast / decisions.vote.view_result / decisions.approve.
"""

import uuid

from sqlalchemy.orm.attributes import set_committed_value

from app.models.committee import Committee
from app.models.decision import Decision
from app.models.user import User
from app.services.committee_access import CommitteeAccess
from app.services.decision_service.errors import DecisionForbiddenError


async def _require_access(
    access: CommitteeAccess, committee: Committee, code: str, message: str
) -> None:
    if not await access.has(committee, code):
        raise DecisionForbiddenError(message)


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


async def _redact_votes_if_unauthorized(
    access: CommitteeAccess, committee: Committee, decision: Decision
) -> Decision:
    """
    خصوصية نتيجة التصويت (بلاغ خطأ 2026-09-07: "عضو اللجنة ليه يمديه يشوف
    نتيجة التصويت؟! غلط ما أعطيته الصلاحية"): decisions.view تسمح برؤية
    القرار نفسه (وخيارات التصويت المتاحة، ضرورية لمجرد التصويت)، لكنها
    لا تعني تلقائيًا حق رؤية *نتيجة* التصويت (تفصيلها في تصويتات الجميع)
    — تلك محكومة حصرًا بكود decisions.vote.view_result المنفصل أصلًا
    بالكتالوج (0006)، ولم يكن يُفحص فعليًا بأي مكان قبل هذا الإصلاح.

    من لا يملك الكود: يبقى يشوف صوته الشخصي فقط (يحتاجه ليعرف هل صوّت
    وعلى أي خيار)، وتُحذف بقية الأصوات من الاستجابة (تحرير عرض غير
    محفوظ — لا يمس القاعدة).

    إصلاح 2026-10-24 (فقدان بيانات مثبت باختبار
    tests/test_decisions_query_budget.py::test_listing_does_not_delete_votes):
    كان التحرير بإسناد decision.votes = [...] مباشرة. العلاقة votes عليها
    cascade="all, delete-orphan"، فالأصوات المحذوفة من القائمة تُعلَّم
    "يتيمة" وتُحذف فعليًا من القاعدة عند أول flush (autoflush مع أي
    استعلام لاحق بنفس الطلب) ثم تُحفظ مع أي commit بعده — مثلًا
    list_decisions بعد إغلاق كسلي لتصويت قرار آخر: عضو بلا view_result
    يفتح القائمة فتنحذف أصوات بقية الأعضاء نهائيًا. set_committed_value
    يغيّر ما يُعرض فقط بدون تسجيل أي تغيير بالجلسة، فلا يُحذف شيء أبدًا.
    """
    if await access.has(committee, "decisions.vote.view_result"):
        return decision
    actor_id = access.actor_id
    set_committed_value(decision, "votes", [v for v in decision.votes if v.user_id == actor_id])
    return decision


async def _can_see_pending_decision(access: CommitteeAccess, committee: Committee) -> bool:
    """
    بلاغ خطأ 2026-09-08 من صاحبة المشروع (بحضور رئيسة لجنة فعلية): قرار
    بحالة 'pending' (أُنشئ، لم يُطرح للتصويت أو يُعتمَد بعد — لا تزال
    رئيسة اللجنة "تجهّزه") كان يظهر لأي عضو يملك decisions.view فقط،
    رغم أن لا قرار فعليًا اتُّخذ بشأنه بعد ليراه أحد غير من يديره. من
    يقدر على decisions.update (عمليًا: رئيسة اللجنة فقط، أو من يملك صلاحية
    نظامية مكافئة) هو وحده من يرى القرار بحالة pending — بقية الحالات
    (voting/approved/rejected) تبقى مرئية بلا أي قيد إضافي كالسابق تمامًا.
    """
    return await access.has(committee, "decisions.update")
