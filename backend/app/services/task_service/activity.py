"""
مسار المهمة الموحَّد (task_assignment_history + audit_logs بخط زمني واحد).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import TaskPriority, TaskStatus
from app.models.user import User
from app.schemas.committee import CommitteeMemberUserOut
from app.schemas.task import TaskActivityEntry
from app.services import audit_service
from app.services.task_service.codes import _PRIORITY_LABELS_AR, _STATUS_LABELS_AR
from app.services.task_service.crud import get_task


async def get_task_activity(
    db: AsyncSession, *, actor: User, task_id: uuid.UUID
) -> list[TaskActivityEntry]:
    """
    مسار المهمة الموحَّد (طلب صاحبة المشروع 2026-09-11، بعد بحث بالأنظمة
    العالمية) — يدمج task_assignment_history (إعادة الإسناد) مع
    audit_logs (تغيير الحالة/الأولوية/بيانات أخرى) بخط زمني واحد مرتَّب
    تصاعديًا. نفس صلاحية عرض المهمة (get_task) تُفرض هنا أولًا.
    """
    task = await get_task(db, task_id, actor=actor)

    entries: list[TaskActivityEntry] = []

    for h in task.assignment_history:
        if h.from_user is None:
            label = f"الإسناد الأول إلى {h.to_user.first_name} {h.to_user.last_name}"
        else:
            label = (
                f"إعادة إسناد من {h.from_user.first_name} {h.from_user.last_name} "
                f"إلى {h.to_user.first_name} {h.to_user.last_name}"
            )
        entries.append(
            TaskActivityEntry(
                entry_type="reassigned",
                label=label,
                actor=CommitteeMemberUserOut.model_validate(h.changer),
                occurred_at=h.changed_at,
            )
        )

    audit_logs, _ = await audit_service.list_audit_logs(
        db, target_type="task", target_id=task_id, limit=200, with_total=False
    )
    for log in audit_logs:
        meta = log.metadata_ or {}
        action = meta.get("action")
        actor_out = CommitteeMemberUserOut.model_validate(log.actor) if log.actor else None

        if action == "status_update":
            raw_status = meta.get("status")
            try:
                status_label = _STATUS_LABELS_AR[TaskStatus(raw_status)]
            except ValueError:
                status_label = str(raw_status)
            entries.append(
                TaskActivityEntry(
                    entry_type="status_changed",
                    label=f"تحديث الحالة إلى {status_label}",
                    actor=actor_out,
                    occurred_at=log.created_at,
                )
            )
        elif action == "task_updated":
            if "priority_to" in meta:
                try:
                    priority_label = _PRIORITY_LABELS_AR[TaskPriority(meta["priority_to"])]
                except ValueError:
                    priority_label = str(meta["priority_to"])
                entries.append(
                    TaskActivityEntry(
                        entry_type="priority_changed",
                        label=f"تحديث الأولوية إلى {priority_label}",
                        actor=actor_out,
                        occurred_at=log.created_at,
                    )
                )
            if meta.get("other_fields_changed"):
                entries.append(
                    TaskActivityEntry(
                        entry_type="details_updated",
                        label="تعديل بيانات المهمة (العنوان أو فترة التنفيذ أو التذكير)",
                        actor=actor_out,
                        occurred_at=log.created_at,
                    )
                )

    entries.sort(key=lambda e: e.occurred_at)
    return entries
