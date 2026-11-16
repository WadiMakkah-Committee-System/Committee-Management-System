"""
الهدف:
تعديل عضوية اللجنة الدائمة بعد اعتمادها، وتمديد فترة اللجنة، مع سجل دائم
لكل تغيير (migration 0050 — طلب لاما 2026-11-16: "اللجان الدائمة تكون
بسنوات، فيلزم تعديل الأعضاء من داخلها مع سجل يوضح التغييرات").

المسؤولية:
- إضافة عضو / حذف عضو / تغيير الرئيس / تغيير أمين السر — للجان الدائمة فقط
  (المؤقتة تبقى عضويتها مقفلة بعد الاعتماد كما قرّرت 0009).
- تمديد نهاية فترة اللجنة (الدائمة والمؤقتة).
- تسجيل كل تغيير في committee_changes (يُعرض بصفحة اللجنة) وفي audit_logs.

الصلاحيات (تُفحص هنا — نطاق System Role أو دور اللجنة، عبر CommitteeAccess):
- committees.members.add / committees.members.remove: إضافة/حذف عضو.
- committees.members.roles: تغيير الرئيس أو أمين السر.
- committees.extend: تمديد الفترة.
- committees.view: عرض سجل التغييرات.

الأخطاء: CommitteeNotFoundError (404)، CommitteeForbiddenError (403)،
ValueError (400) لمخالفة قاعدة عمل.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload, selectinload

from app.models.committee import Committee, CommitteeMember
from app.models.committee_change import CommitteeChange, CommitteeChangeType
from app.models.role import Role
from app.models.user import User, UserStatus
from app.services import audit_service
from app.services.committee_access import CommitteeAccess
from app.services.committee_service import (
    CommitteeForbiddenError,
    CommitteeNotFoundError,
    _committee_detail_load_options,
)


#: من يملك أيًا منها يشوف سجل تغييرات اللجنة (إضافة لأعضائها).
_HISTORY_CODES = (
    "committees.view",
    "committees.members.add",
    "committees.members.remove",
    "committees.members.roles",
    "committees.extend",
)


async def _load_committee(db: AsyncSession, committee_id: uuid.UUID) -> Committee:
    """
    اللجنة بعضويتها الحالية (member_roles + الرئيس، يحمّلهما الـmapper تلقائيًا
    بـselectin) — غير المحذوفة فقط. الأخطاء: CommitteeNotFoundError.
    """
    result = await db.execute(select(Committee).where(Committee.committee_id == committee_id))
    committee = result.scalar_one_or_none()
    if committee is None or committee.is_deleted:
        raise CommitteeNotFoundError("اللجنة غير موجودة")
    return committee


async def _require(db: AsyncSession, actor: User, committee: Committee, code: str, message: str) -> None:
    """يرفع CommitteeForbiddenError لو actor لا يملك code على هذه اللجنة (نظامي أو دور لجنة)."""
    if not await CommitteeAccess(db, actor).has(committee, code):
        raise CommitteeForbiddenError(message)


def _assert_permanent(committee: Committee) -> None:
    """تعديل العضوية بعد الاعتماد للجان الدائمة فقط (قرار لاما 2026-11-16)."""
    if not committee.is_permanent:
        raise ValueError("تعديل أعضاء اللجنة بعد اعتمادها متاح للجان الدائمة فقط")


async def _committee_role_ids(db: AsyncSession) -> dict[str, uuid.UUID]:
    """معرّفات أدوار اللجنة الثابتة: {'chair': ..., 'member': ..., 'secretary': ...}."""
    result = await db.execute(
        select(Role.committee_role_slug, Role.role_id).where(
            Role.committee_role_slug.in_(("chair", "member", "secretary"))
        )
    )
    return {slug: role_id for slug, role_id in result.all()}


def _membership(committee: Committee, user_id: uuid.UUID) -> CommitteeMember | None:
    return next((m for m in committee.member_roles if m.user_id == user_id), None)


async def _record(
    db: AsyncSession,
    *,
    committee: Committee,
    actor: User,
    change_type: CommitteeChangeType,
    subject_user_id: uuid.UUID | None = None,
    previous_user_id: uuid.UUID | None = None,
    details: dict | None = None,
    reason: str | None = None,
) -> None:
    """
    يسجّل التغيير في committee_changes (السجل الظاهر بصفحة اللجنة) وفي
    audit_logs (سجل التدقيق العام) ضمن نفس المعاملة. لا commit هنا.
    """
    db.add(
        CommitteeChange(
            committee_id=committee.committee_id,
            change_type=change_type.value,
            subject_user_id=subject_user_id,
            previous_user_id=previous_user_id,
            details=details or {},
            reason=reason,
            changed_by=actor.user_id,
        )
    )
    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="committee",
        target_id=committee.committee_id,
        metadata={
            "change_type": change_type.value,
            "subject_user_id": str(subject_user_id) if subject_user_id else None,
            "previous_user_id": str(previous_user_id) if previous_user_id else None,
            **(details or {}),
        },
    )


async def _commit_and_reload(db: AsyncSession, committee_id: uuid.UUID) -> Committee:
    """commit ثم إعادة تحميل اللجنة بشكل CommitteeOut الكامل."""
    await db.commit()
    result = await db.execute(
        select(Committee)
        .options(*_committee_detail_load_options())
        .where(Committee.committee_id == committee_id)
        .execution_options(populate_existing=True)
    )
    return result.unique().scalar_one()


async def _get_active_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    """مستخدم نشط غير محذوف وليس ضيفًا مؤقتًا. الأخطاء: ValueError."""
    result = await db.execute(
        select(User)
        .options(raiseload("*", sql_only=True))
        .where(User.user_id == user_id, User.deleted_at.is_(None), User.is_guest.is_(False))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("المستخدم غير موجود")
    if user.status != UserStatus.active:
        raise ValueError("لا يمكن إضافة مستخدم موقوف للجنة")
    return user


async def add_member(
    db: AsyncSession, *, actor: User, committee_id: uuid.UUID, user_id: uuid.UUID, reason: str | None
) -> Committee:
    """
    إضافة عضو للجنة دائمة معتمدة (بدور "عضو اللجنة").
    الصلاحية: committees.members.add. الأخطاء: لجنة مؤقتة، مستخدم غير
    موجود/موقوف، أو عضو أصلًا (ValueError).
    """
    committee = await _load_committee(db, committee_id)
    await _require(db, actor, committee, "committees.members.add", "ليست لديك صلاحية إضافة أعضاء لهذه اللجنة")
    _assert_permanent(committee)
    user = await _get_active_user(db, user_id)
    if _membership(committee, user.user_id) is not None:
        raise ValueError("المستخدم عضو في اللجنة أصلًا")

    roles = await _committee_role_ids(db)
    committee.member_roles.append(CommitteeMember(user_id=user.user_id, committee_role_id=roles["member"]))
    await _record(
        db, committee=committee, actor=actor, change_type=CommitteeChangeType.member_added,
        subject_user_id=user.user_id, reason=reason,
    )
    return await _commit_and_reload(db, committee_id)


async def remove_member(
    db: AsyncSession, *, actor: User, committee_id: uuid.UUID, user_id: uuid.UUID, reason: str | None
) -> Committee:
    """
    حذف عضو من لجنة دائمة. رئيس اللجنة لا يُحذف مباشرة (يُغيَّر الرئيس أولًا)،
    وحذف أمين السر يلغي تعيينه أمينًا.
    الصلاحية: committees.members.remove.
    """
    committee = await _load_committee(db, committee_id)
    await _require(db, actor, committee, "committees.members.remove", "ليست لديك صلاحية حذف أعضاء من هذه اللجنة")
    _assert_permanent(committee)
    membership = _membership(committee, user_id)
    if membership is None:
        raise ValueError("المستخدم ليس عضوًا في اللجنة")
    if committee.chair_user_id == user_id:
        raise ValueError("لا يمكن حذف رئيس اللجنة — غيّر الرئيس أولًا")
    if len(committee.member_roles) <= 1:
        raise ValueError("لا يمكن حذف آخر عضو في اللجنة")

    was_secretary = committee.secretary_user_id == user_id
    if was_secretary:
        committee.secretary_user_id = None
    committee.member_roles.remove(membership)
    await _record(
        db, committee=committee, actor=actor, change_type=CommitteeChangeType.member_removed,
        subject_user_id=user_id, details={"was_secretary": was_secretary}, reason=reason,
    )
    return await _commit_and_reload(db, committee_id)


async def change_chair(
    db: AsyncSession, *, actor: User, committee_id: uuid.UUID, user_id: uuid.UUID, reason: str | None
) -> Committee:
    """
    تعيين رئيس جديد للجنة دائمة من بين أعضائها. الرئيس السابق يبقى عضوًا
    عاديًا، ولو كان الجديد أمين السر يُلغى تعيينه أمينًا.
    الصلاحية: committees.members.roles.
    """
    committee = await _load_committee(db, committee_id)
    await _require(db, actor, committee, "committees.members.roles", "ليست لديك صلاحية تغيير رئيس هذه اللجنة")
    _assert_permanent(committee)
    new_membership = _membership(committee, user_id)
    if new_membership is None:
        raise ValueError("الرئيس الجديد لازم يكون من أعضاء اللجنة")
    if committee.chair_user_id == user_id:
        raise ValueError("المستخدم هو رئيس اللجنة حاليًا")

    roles = await _committee_role_ids(db)
    previous_chair_id = committee.chair_user_id
    if previous_chair_id is not None:
        previous = _membership(committee, previous_chair_id)
        if previous is not None:
            previous.committee_role_id = roles["member"]
    details: dict = {}
    if committee.secretary_user_id == user_id:
        committee.secretary_user_id = None
        details["was_secretary"] = True
    new_membership.committee_role_id = roles["chair"]
    committee.chair_user_id = user_id
    await _record(
        db, committee=committee, actor=actor, change_type=CommitteeChangeType.chair_changed,
        subject_user_id=user_id, previous_user_id=previous_chair_id, details=details, reason=reason,
    )
    return await _commit_and_reload(db, committee_id)


async def change_secretary(
    db: AsyncSession, *, actor: User, committee_id: uuid.UUID, user_id: uuid.UUID | None, reason: str | None
) -> Committee:
    """
    تعيين أمين سر جديد للجنة دائمة من أعضائها، أو إلغاء التعيين (user_id=None).
    الأمين السابق يبقى عضوًا عاديًا. الرئيس لا يكون أمينًا.
    الصلاحية: committees.members.roles.
    """
    committee = await _load_committee(db, committee_id)
    await _require(db, actor, committee, "committees.members.roles", "ليست لديك صلاحية تغيير أمين سر هذه اللجنة")
    _assert_permanent(committee)
    if committee.secretary_user_id == user_id:
        raise ValueError("لا يوجد تغيير على أمين السر")
    new_membership = None
    if user_id is not None:
        new_membership = _membership(committee, user_id)
        if new_membership is None:
            raise ValueError("أمين السر لازم يكون من أعضاء اللجنة")
        if committee.chair_user_id == user_id:
            raise ValueError("رئيس اللجنة لا يمكن أن يكون أمين السر")

    roles = await _committee_role_ids(db)
    previous_id = committee.secretary_user_id
    if previous_id is not None:
        previous = _membership(committee, previous_id)
        if previous is not None:
            previous.committee_role_id = roles["member"]
    if new_membership is not None:
        new_membership.committee_role_id = roles["secretary"]
    committee.secretary_user_id = user_id
    await _record(
        db, committee=committee, actor=actor, change_type=CommitteeChangeType.secretary_changed,
        subject_user_id=user_id, previous_user_id=previous_id, reason=reason,
    )
    return await _commit_and_reload(db, committee_id)


async def extend_committee(
    db: AsyncSession, *, actor: User, committee_id: uuid.UUID, end_date: date, reason: str | None
) -> Committee:
    """
    تمديد نهاية فترة اللجنة (طلب لاما 2026-11-16: "بداية ونهاية + تمديد الوقت").
    النهاية الجديدة لازم تكون بعد الحالية. يُصفَّر expiry_notified_at حتى
    يُشعَر بالانتهاء الجديد لاحقًا (app/core/scheduler.py).
    الصلاحية: committees.extend.
    """
    committee = await _load_committee(db, committee_id)
    await _require(db, actor, committee, "committees.extend", "ليست لديك صلاحية تمديد هذه اللجنة")
    if committee.end_date is None or committee.start_date is None:
        raise ValueError("اللجنة بلا فترة محددة — حدّد تاريخ البداية والنهاية أولًا من تعديل الفترة")
    if end_date <= committee.end_date:
        raise ValueError("تاريخ النهاية الجديد لازم يكون بعد النهاية الحالية")

    before = committee.end_date
    committee.end_date = end_date
    committee.expiry_notified_at = None
    await _record(
        db, committee=committee, actor=actor, change_type=CommitteeChangeType.period_extended,
        details={"previous_end_date": before.isoformat(), "new_end_date": end_date.isoformat()},
        reason=reason,
    )
    return await _commit_and_reload(db, committee_id)


async def list_changes(db: AsyncSession, *, actor: User, committee_id: uuid.UUID) -> list[CommitteeChange]:
    """
    سجل تغييرات اللجنة، الأحدث أولًا — لأعضائها، ولمن يملك على اللجنة
    committees.view أو أي صلاحية تعديل عليها (_HISTORY_CODES).
    """
    committee = await _load_committee(db, committee_id)
    is_member = committee.chair_user_id == actor.user_id or _membership(committee, actor.user_id) is not None
    if not is_member:
        # عرض اللجنة، أو أي صلاحية تعديل عليها (من يعدّل يشوف سجل ما عدّله).
        access = CommitteeAccess(db, actor)
        allowed = False
        for code in _HISTORY_CODES:
            if await access.has(committee, code):
                allowed = True
                break
        if not allowed:
            raise CommitteeForbiddenError("ليست لديك صلاحية عرض سجل هذه اللجنة")
    result = await db.execute(
        select(CommitteeChange)
        .options(
            selectinload(CommitteeChange.subject_user).raiseload("*", sql_only=True),
            selectinload(CommitteeChange.previous_user).raiseload("*", sql_only=True),
            selectinload(CommitteeChange.changed_by_user).raiseload("*", sql_only=True),
        )
        .where(CommitteeChange.committee_id == committee_id)
        .order_by(CommitteeChange.created_at.desc())
    )
    return list(result.scalars().all())


async def list_member_candidates(
    db: AsyncSession, *, actor: User, committee_id: uuid.UUID
) -> list[User]:
    """
    المستخدمون النشطون غير الأعضاء — لاختيار عضو جديد. الصلاحية:
    committees.members.add (نفس صلاحية الإضافة نفسها).
    """
    committee = await _load_committee(db, committee_id)
    await _require(db, actor, committee, "committees.members.add", "ليست لديك صلاحية إضافة أعضاء لهذه اللجنة")
    member_ids = {m.user_id for m in committee.member_roles}
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.department).raiseload("*", sql_only=True),
            selectinload(User.job_title).raiseload("*", sql_only=True),
            raiseload("*", sql_only=True),
        )
        .where(
            User.deleted_at.is_(None),
            User.is_guest.is_(False),
            User.status == UserStatus.active,
        )
        .order_by(User.first_name, User.last_name)
    )
    return [u for u in result.scalars().all() if u.user_id not in member_ids]


async def capabilities(db: AsyncSession, *, actor: User, committee_id: uuid.UUID) -> dict[str, bool]:
    """
    وش يقدر actor يسوي على هذه اللجنة (لإظهار/إخفاء أزرار الواجهة فقط — الفحص
    الفعلي يبقى بكل عملية أعلاه). تعديل العضوية للدائمة فقط.
    """
    committee = await _load_committee(db, committee_id)
    access = CommitteeAccess(db, actor)
    permanent = committee.is_permanent
    can_add = permanent and await access.has(committee, "committees.members.add")
    can_remove = permanent and await access.has(committee, "committees.members.remove")
    can_roles = permanent and await access.has(committee, "committees.members.roles")
    can_extend = committee.end_date is not None and await access.has(committee, "committees.extend")
    is_member = committee.chair_user_id == actor.user_id or _membership(committee, actor.user_id) is not None
    can_history = is_member
    if not can_history:
        for code in _HISTORY_CODES:
            if await access.has(committee, code):
                can_history = True
                break
    return {
        "can_add_members": can_add,
        "can_remove_members": can_remove,
        "can_change_roles": can_roles,
        "can_extend": can_extend,
        "can_view_history": can_history,
    }
