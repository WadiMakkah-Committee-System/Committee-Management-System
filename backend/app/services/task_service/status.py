"""
تحديث حالة المهمة وإعادة إسنادها (FR-TASK-013/016 + مسار المهمة).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskAssignmentHistory, TaskStatus
from app.models.user import User
from app.services import audit_service
from app.services.committee_access import CommitteeAccess
from app.services.task_service.access import (
    _require_access,
    _require_object_scoped_access,
    _validate_assignee_membership,
)
from app.services.task_service.codes import _STATUS_UPDATE, _UPDATE
from app.services.task_service.errors import TaskInvalidStateError
from app.services.task_service.loading import load_task


async def update_status(
    db: AsyncSession, *, actor: User, task_id: uuid.UUID, status: TaskStatus
) -> Task:
    """FR-TASK-013/016: المسؤول الحالي يحدّث حالة مهامه فقط؛ رئيس اللجنة يحدّث أي مهمة بلجنته."""
    access = CommitteeAccess(db, actor)
    task = await load_task(db, task_id)
    committee = task.committee  # محمَّلة مع المهمة (loading.task_options)
    await _require_object_scoped_access(
        access,
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
    return await load_task(db, task.task_id, reload=True)


async def reassign_task(
    db: AsyncSession, *, actor: User, task_id: uuid.UUID, assignee_user_id: uuid.UUID
) -> Task:
    """
    إعادة إسناد المسؤول — نفس صلاحية التعديل (tasks.update)، أي رئيس
    اللجنة فعليًا حسب منح الأدوار المتَّبع. يسجَّل صف جديد بمسار المهمة
    (Task Trail) عند أي تغيير فعلي بالمسؤول فقط (بدون صف مكرَّر لو نفس
    المسؤول الحالي).
    """
    access = CommitteeAccess(db, actor)
    task = await load_task(db, task_id, with_members=True)
    committee = task.committee  # محمَّلة مع المهمة (loading.task_options)
    await _require_access(access, committee, _UPDATE, "ليست لديك صلاحية إعادة إسناد هذه المهمة"
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
    return await load_task(db, task.task_id, reload=True)
