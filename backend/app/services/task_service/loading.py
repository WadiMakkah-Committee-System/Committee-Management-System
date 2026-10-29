"""
تحميل المهام واللجان — المكان **الوحيد** بوحدة المهام الذي يحدد ماذا
يُحمَّل مع كل مهمة (إعادة هيكلة 2026-10-24).

لماذا: علاقات الموديل lazy="selectin" كانت تجرّ تلقائيًا مع كل مهمة اللجنة
(بأعضائها وأدوارهم وصلاحياتهم) والمسؤول والمنشئ ومسار الإسناد (بثلاثة
مستخدمين لكل سطر)، ولكل مستخدم دوره ومسماه وصلاحياته. قِيس: قائمة المهام =
30 استعلامًا لطلب واحد (كل استعلام ≈ 355ms على الإنتاج).

ما يُحمَّل هنا صريح:
- TaskOut: assignee، creator، assignment_history (+ from_user/to_user/changer).
- فحص الصلاحية: اللجنة + رئيسها.
- الإشعارات (notify_task_*): committee.name وchair_user_id وassignee.email.
- with_members=True (عمليات تتحقق من عضوية المسؤول فقط: الإنشاء/إعادة الإسناد).
أي علاقة أخرى عليها raiseload(sql_only=True).
عدد الاستعلامات ثابت مهما كان عدد المهام: 2 (رئيسي + مسار الإسناد).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, raiseload, selectinload

from app.models.committee import Committee
from app.models.task import Task, TaskAssignmentHistory
from app.services.task_service.errors import TaskNotFoundError

_RAISE = {"sql_only": True}


def _user(path) -> tuple:
    """مستخدم بأعمدته فقط (CommitteeMemberUserOut) — بلا دوره/مسماه/صلاحياته."""
    return (path, path.raiseload("*", **_RAISE))


def task_options(*, with_members: bool = False, summary: bool = False) -> tuple:
    committee = joinedload(Task.committee)
    options: list = [*_user(committee.joinedload(Committee.chair))]
    if summary:
        # لوحة التحكم: المهمة + لجنتها (الاسم وفحص الرئيس) فقط.
        return (*options, committee, committee.raiseload("*", **_RAISE), raiseload("*", **_RAISE))
    if with_members:
        options += _user(committee.selectinload(Committee.members))
    history = selectinload(Task.assignment_history)
    options += [
        committee,
        committee.raiseload("*", **_RAISE),
        *_user(joinedload(Task.assignee)),
        *_user(joinedload(Task.creator)),
        history,
        *_user(history.joinedload(TaskAssignmentHistory.from_user)),
        *_user(history.joinedload(TaskAssignmentHistory.to_user)),
        *_user(history.joinedload(TaskAssignmentHistory.changer)),
        history.raiseload("*", **_RAISE),
        raiseload("*", **_RAISE),
    ]
    return tuple(options)


def tasks_query(*, with_members: bool = False, reload: bool = False, summary: bool = False):
    """reload=True فقط لإعادة التحميل بعد commit بنفس الدالة (populate_existing
    يقرأ القيم الحالية فعلًا — مثلًا المسؤول الجديد بعد إعادة الإسناد، وهذا
    ما كان يُفشل test_reassign_records_task_trail سابقًا: الكائن الموجود
    بالجلسة كان يُعاد كما هو بالمسؤول القديم). ليس افتراضيًا: الكائنات
    المرتبطة (اللجنة) مشتركة بين الخدمات بنفس الجلسة، وإعادة تعبئتها مع
    raiseload تمنع علاقات حمّلتها خدمة أخرى قبلها."""
    return (
        select(Task)
        .options(*task_options(with_members=with_members, summary=summary))
        .execution_options(populate_existing=reload)
    )


async def load_task(
    db: AsyncSession, task_id: uuid.UUID, *, with_members: bool = False, reload: bool = False
) -> Task:
    result = await db.execute(
        tasks_query(with_members=with_members, reload=reload).where(Task.task_id == task_id)
    )
    task = result.unique().scalar_one_or_none()
    if task is None or task.is_deleted:
        raise TaskNotFoundError("المهمة غير موجودة")
    return task


async def load_committee(db: AsyncSession, committee_id: uuid.UUID) -> Committee:
    """اللجنة + رئيسها + أعضاؤها (للتحقق أن المسؤول عضو فيها)."""
    result = await db.execute(
        select(Committee)
        .where(Committee.committee_id == committee_id)
        .options(
            *_user(joinedload(Committee.chair)),
            *_user(selectinload(Committee.members)),
            raiseload("*", **_RAISE),
        )
        .execution_options(populate_existing=True)
    )
    committee = result.unique().scalar_one_or_none()
    if committee is None or committee.is_deleted:
        raise TaskNotFoundError("اللجنة المرتبطة غير موجودة")
    return committee
