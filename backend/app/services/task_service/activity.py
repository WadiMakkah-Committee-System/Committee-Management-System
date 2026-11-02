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


def _reminder_days_label_ar(days: object) -> str:
    """صيغة عدد أيام التذكير بالعربية الفصحى (مطابقة التمييز العددي):
    0 حالة خاصة (يوم الاستحقاق نفسه)، 1 مفرد، 2 مثنى، 3-10 جمع، 11+ تمييز مفرد منصوب."""
    try:
        n = int(days)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return f"{days} يوم"
    if n == 0:
        return "يوم الاستحقاق نفسه"
    if n == 1:
        return "يوم واحد قبل الاستحقاق"
    if n == 2:
        return "يومين قبل الاستحقاق"
    if 3 <= n <= 10:
        return f"{n} أيام قبل الاستحقاق"
    return f"{n} يومًا قبل الاستحقاق"


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

            # تصحيح 2026-11-02 (طلب لجين): بدل عبارة عامة واحدة "تعديل
            # بيانات المهمة"، نبني جملة لكل حقل فعليًا تغيّر من ميتاداتا
            # update_task المفصّلة (X_from/X_to) — وبالأخص فترة التنفيذ:
            # تمديد لو الموعد الجديد أبعد، تقديم لو أقرب، مو عبارة محايدة.
            clauses: list[str] = []
            if "title_to" in meta:
                clauses.append(f'تحديث العنوان إلى "{meta["title_to"]}"')
            if "start_date_to" in meta:
                clauses.append(f'تحديث تاريخ بداية التنفيذ إلى {meta["start_date_to"]}')
            if "end_date_to" in meta:
                old_end = str(meta.get("end_date_from", ""))
                new_end = str(meta["end_date_to"])
                verb = "تمديد" if (old_end and new_end > old_end) else "تقديم"
                clauses.append(f"{verb} فترة التنفيذ من {old_end} إلى {new_end}")
            if "reminder_offset_days_to" in meta:
                clauses.append(f'تحديث التذكير إلى {_reminder_days_label_ar(meta["reminder_offset_days_to"])}')

            if clauses:
                entries.append(
                    TaskActivityEntry(
                        entry_type="details_updated",
                        label="، ".join(clauses),
                        actor=actor_out,
                        occurred_at=log.created_at,
                    )
                )
            elif meta.get("other_fields_changed"):
                # توافق خلفي: صفوف audit_logs قديمة (قبل تصحيح 2026-11-02)
                # ما فيها إلا العلم العام القديم بلا قيم from/to — تُعرض
                # بنفس العبارة العامة السابقة بدل ما تختفي من المسار.
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
