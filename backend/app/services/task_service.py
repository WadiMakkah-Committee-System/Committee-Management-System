"""
الهدف:
منطق العمل لوحدة "إدارة المهام" — الإنشاء المباشر من واجهة المهام فقط
(§4 SRS + §6 BRS). بدون المهام المستخرجة من اجتماع بالذكاء الاصطناعي
(تُبنى لاحقًا)، وبدون ربط بالوثائق أو تذكيرات بهذه المرحلة. راجعي رأس
db/migrations/0024_tasks_schema.sql لكل الاجتهادات الموثّقة المتفَق عليها
مع صاحبة المشروع (2026-09-06).

التفويض: نفس النمط الهجين المطبَّق حرفيًا بوحدة القرارات (System Role
scope عبر actor.scope_for، أو Committee Role permission عبر
committee_service.get_committee_role_permission_codes) — بنفس أكواد
النظام تمامًا لكلا المستويين (tasks.create/view/view_details/update/
delete/status.update)، تُمنح لدوري "رئيس اللجنة"/"عضو اللجنة" مباشرة عبر
شاشة الأدوار والصلاحيات (نفس آلية decisions.*، راجعي test_decisions.py
لمثال المنح). ملاحظة: أكواد committee.tasks.manage/view_assigned/
update_assigned المزروعة بـmigration 0016 هي فقط لتصنيف واجهة "أدوار
اللجان" — غير مستخدَمة هنا، بنفس الحال الفعلي لأكواد committee.decisions.*
بوحدة القرارات.

تمييز إضافي غير موجود بالقرارات: "عرض" و"تحديث الحالة" يحتاجان تقييدًا
إضافيًا على مستوى الكائن نفسه (وليس مجرّد امتلاك الكود) — رئيس اللجنة
يشوف/يحدّث أي مهمة بلجنته، بينما العضو العادي (نفس الكود الممنوح له)
يقتصر على المهام المسندة له هو تحديدًا. هذا التمييز يُحسَم بمقارنة
committee.chair_user_id == actor.user_id مباشرة، وليس من قائمة الأكواد.

القفل الحرج (FR-TASK-016/018): التعديل/الحذف/إعادة الإسناد/تحديث الحالة
كلها ممنوعة فعليًا إذا status الحالية = 'completed'.

تحديثات الحالة تُسجَّل بجدول audit_logs العام (نفس نمط تحديثات حالة
القرارات بالضبط) — منفصل تمامًا عن task_assignment_history (مسار
المهمة)، المخصّص فقط لتتبع إعادة تعيين المسؤول.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.committee import Committee, committee_members
from app.models.role import Permission, RolePermission
from app.models.task import Task, TaskAssignmentHistory, TaskStatus
from app.models.user import User
from app.services import audit_service, committee_service

_CREATE = "tasks.create"
_UPDATE = "tasks.update"
_DELETE = "tasks.delete"
_VIEW = "tasks.view"
_VIEW_DETAILS = "tasks.view_details"
_STATUS_UPDATE = "tasks.status.update"


class TaskNotFoundError(Exception):
    """المهمة غير موجودة (أو محذوفة) — تُترجَم إلى 404."""


class TaskForbiddenError(Exception):
    """محاولة إجراء غير مسموح بها لهذا المستخدم تحديدًا — تُترجَم إلى 403."""


class TaskInvalidStateError(Exception):
    """محاولة إجراء لا تسمح به حالة المهمة الحالية (غالبًا completed) — تُترجَم إلى 409."""


class TaskValidationError(Exception):
    """خطأ تحقق من بيانات العمل — تُترجَم إلى 400."""


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
        raise TaskForbiddenError(message)


def _is_chair(actor: User, committee: Committee) -> bool:
    return committee.chair_user_id == actor.user_id


async def _require_object_scoped_access(
    db: AsyncSession,
    actor: User,
    committee: Committee,
    task: Task,
    code: str,
    message: str,
    own_only_message: str,
) -> None:
    """
    فحص صلاحية بمرحلتين: (1) هل يملك الكود أصلًا (نظام أو لجنة)، (2) إن كان
    امتلاكه عبر عضوية اللجنة (لا نطاق نظام) وهو ليس رئيس اللجنة — يُقيَّد
    بمهامه المسندة له هو تحديدًا فقط. رئيس اللجنة أو صاحب نطاق نظام
    (all/department) غير مقيَّدين بهذا الشرط الإضافي.
    """
    if _system_scope_allows(actor, committee, code):
        return
    if not await _has_access(db, actor, committee, code):
        raise TaskForbiddenError(message)
    if not _is_chair(actor, committee) and task.assignee_user_id != actor.user_id:
        raise TaskForbiddenError(own_only_message)


async def _committee_ids_with_role_code(
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


def _committee_member_ids(committee: Committee) -> set[uuid.UUID]:
    """كل من يصلح إسناد مهمة له بهذه اللجنة — رئيسها وأعضاؤها."""
    ids = {m.user_id for m in committee.members}
    if committee.chair_user_id is not None:
        ids.add(committee.chair_user_id)
    return ids


def _validate_assignee_membership(committee: Committee, assignee_user_id: uuid.UUID) -> None:
    if assignee_user_id not in _committee_member_ids(committee):
        raise TaskValidationError("لا يمكن إسناد المهمة لمستخدم ليس عضوًا في اللجنة المرتبطة")


async def _load_committee(db: AsyncSession, committee_id: uuid.UUID) -> Committee:
    result = await db.execute(select(Committee).where(Committee.committee_id == committee_id))
    committee = result.scalar_one_or_none()
    if committee is None or committee.is_deleted:
        raise TaskNotFoundError("اللجنة المرتبطة غير موجودة")
    return committee


async def _load_task(db: AsyncSession, task_id: uuid.UUID) -> Task:
    result = await db.execute(select(Task).where(Task.task_id == task_id))
    task = result.scalar_one_or_none()
    if task is None or task.is_deleted:
        raise TaskNotFoundError("المهمة غير موجودة")
    return task


# ============================== CRUD ==============================


async def create_task(
    db: AsyncSession,
    *,
    actor: User,
    committee_id: uuid.UUID,
    title: str,
    start_date: date,
    end_date: date,
    assignee_user_id: uuid.UUID,
) -> Task:
    """FR-TASK-001/002: إنشاء مباشر من واجهة المهام، مسؤول واحد فقط."""
    committee = await _load_committee(db, committee_id)
    await _require_access(
        db, actor, committee, _CREATE, "ليست لديك صلاحية إنشاء مهمة لهذه اللجنة"
    )
    _validate_assignee_membership(committee, assignee_user_id)

    task = Task(
        committee_id=committee_id,
        title=title,
        start_date=start_date,
        end_date=end_date,
        assignee_user_id=assignee_user_id,
        created_by=actor.user_id,
    )
    db.add(task)
    await db.flush()

    # التعيين الأول — يُسجَّل بمسار المهمة (from_user_id = NULL)
    db.add(
        TaskAssignmentHistory(
            task_id=task.task_id,
            from_user_id=None,
            to_user_id=assignee_user_id,
            changed_by=actor.user_id,
        )
    )

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="create",
        target_type="task",
        target_id=task.task_id,
    )
    await db.commit()
    return await _load_task(db, task.task_id)


async def get_task(db: AsyncSession, task_id: uuid.UUID, *, actor: User) -> Task:
    task = await _load_task(db, task_id)
    committee = await _load_committee(db, task.committee_id)
    await _require_object_scoped_access(
        db,
        actor,
        committee,
        task,
        _VIEW_DETAILS,
        "ليست لديك صلاحية لعرض هذه المهمة",
        "يمكنك عرض المهام المسندة إليك فقط",
    )
    return task


async def list_tasks(db: AsyncSession, *, actor: User) -> list[Task]:
    """
    رئيس اللجنة يشوف كل مهام لجانه (بمن فيها الي مسندة لغيره)، العضو
    العادي يشوف بس مهامه المسندة له (حتى لو عضو بأكثر من لجنة).
    """
    scope = actor.scope_for(_VIEW)
    stmt = select(Task).where(Task.deleted_at.is_(None)).order_by(Task.created_at.desc())

    if scope == "all":
        pass
    elif scope == "department":
        if actor.dep_id is None:
            return []
        chair = aliased(User)
        stmt = (
            stmt.join(Committee, Task.committee_id == Committee.committee_id)
            .join(chair, Committee.chair_user_id == chair.user_id)
            .where(chair.dep_id == actor.dep_id)
        )
    else:
        committee_ids = await _committee_ids_with_role_code(db, actor, _VIEW)
        if not committee_ids:
            return []
        chair_result = await db.execute(
            select(Committee.committee_id).where(
                Committee.committee_id.in_(committee_ids),
                Committee.chair_user_id == actor.user_id,
            )
        )
        chair_ids = set(chair_result.scalars().all())
        member_only_ids = committee_ids - chair_ids

        conditions = []
        if chair_ids:
            conditions.append(Task.committee_id.in_(chair_ids))
        if member_only_ids:
            conditions.append(
                and_(
                    Task.committee_id.in_(member_only_ids),
                    Task.assignee_user_id == actor.user_id,
                )
            )
        stmt = stmt.where(or_(*conditions))

    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def update_task(
    db: AsyncSession,
    *,
    actor: User,
    task_id: uuid.UUID,
    title: str | None,
    start_date: date | None,
    end_date: date | None,
) -> Task:
    task = await _load_task(db, task_id)
    committee = await _load_committee(db, task.committee_id)
    await _require_access(db, actor, committee, _UPDATE, "ليست لديك صلاحية تعديل هذه المهمة")

    if task.status == TaskStatus.completed:
        raise TaskInvalidStateError("لا يمكن تعديل مهمة مكتملة")

    effective_start = start_date if start_date is not None else task.start_date
    effective_end = end_date if end_date is not None else task.end_date
    if effective_end < effective_start:
        raise TaskValidationError("تاريخ نهاية المهمة يجب أن يكون بعد تاريخ البداية أو يساويه")

    if title is not None:
        task.title = title
    if start_date is not None:
        task.start_date = start_date
    if end_date is not None:
        task.end_date = end_date

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="task",
        target_id=task.task_id,
    )
    await db.commit()
    return await _load_task(db, task.task_id)


async def delete_task(db: AsyncSession, *, actor: User, task_id: uuid.UUID) -> None:
    task = await _load_task(db, task_id)
    committee = await _load_committee(db, task.committee_id)
    await _require_access(db, actor, committee, _DELETE, "ليست لديك صلاحية حذف هذه المهمة")

    if task.status == TaskStatus.completed:
        raise TaskInvalidStateError("لا يمكن حذف مهمة مكتملة")

    task.deleted_at = datetime.now(UTC)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="delete",
        target_type="task",
        target_id=task.task_id,
    )
    await db.commit()


# ============================== الحالة وإعادة الإسناد ==============================


async def update_status(
    db: AsyncSession, *, actor: User, task_id: uuid.UUID, status: TaskStatus
) -> Task:
    """FR-TASK-013/016: المسؤول الحالي يحدّث حالة مهامه فقط؛ رئيس اللجنة يحدّث أي مهمة بلجنته."""
    task = await _load_task(db, task_id)
    committee = await _load_committee(db, task.committee_id)
    await _require_object_scoped_access(
        db,
        actor,
        committee,
        task,
        _STATUS_UPDATE,
        "ليست لديك صلاحية تحديث حالة هذه المهمة",
        "يمكنك تحديث حالة المهام المسندة إليك فقط",
    )

    if task.status == TaskStatus.completed:
        raise TaskInvalidStateError("لا يمكن تعديل حالة مهمة مكتملة")

    task.status = status

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="task",
        target_id=task.task_id,
        metadata={"action": "status_update", "status": status.value},
    )
    await db.commit()
    return await _load_task(db, task.task_id)


async def reassign_task(
    db: AsyncSession, *, actor: User, task_id: uuid.UUID, assignee_user_id: uuid.UUID
) -> Task:
    """
    إعادة إسناد المسؤول — نفس صلاحية التعديل (tasks.update)، أي رئيس
    اللجنة فعليًا حسب منح الأدوار المتَّبع. يسجَّل صف جديد بمسار المهمة
    (Task Trail) عند أي تغيير فعلي بالمسؤول فقط (بدون صف مكرَّر لو نفس
    المسؤول الحالي).
    """
    task = await _load_task(db, task_id)
    committee = await _load_committee(db, task.committee_id)
    await _require_access(
        db, actor, committee, _UPDATE, "ليست لديك صلاحية إعادة إسناد هذه المهمة"
    )

    if task.status == TaskStatus.completed:
        raise TaskInvalidStateError("لا يمكن إعادة إسناد مهمة مكتملة")

    _validate_assignee_membership(committee, assignee_user_id)

    if assignee_user_id == task.assignee_user_id:
        return task

    old_assignee_id = task.assignee_user_id
    task.assignee_user_id = assignee_user_id
    db.add(
        TaskAssignmentHistory(
            task_id=task.task_id,
            from_user_id=old_assignee_id,
            to_user_id=assignee_user_id,
            changed_by=actor.user_id,
        )
    )

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="task",
        target_id=task.task_id,
        metadata={"action": "reassign"},
    )
    await db.commit()
    return await _load_task(db, task.task_id)
