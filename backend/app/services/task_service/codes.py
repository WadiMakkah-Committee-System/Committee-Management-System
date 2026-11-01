"""أكواد الصلاحيات وتسميات العرض لوحدة المهام."""

from app.models.task import TaskPriority, TaskStatus

_STATUS_LABELS_AR: dict[TaskStatus, str] = {
    TaskStatus.todo: "للقيام",
    TaskStatus.in_progress: "جارية",
    TaskStatus.on_hold: "معلّقة",
    TaskStatus.completed: "مكتملة",
}
_PRIORITY_LABELS_AR: dict[TaskPriority, str] = {
    TaskPriority.low: "منخفضة",
    TaskPriority.medium: "متوسطة",
    TaskPriority.high: "عالية",
}

_CREATE = "tasks.create"
_UPDATE = "tasks.update"
_DELETE = "tasks.delete"
_VIEW = "tasks.view"
_VIEW_DETAILS = "tasks.view_details"
_STATUS_UPDATE = "tasks.status.update"
