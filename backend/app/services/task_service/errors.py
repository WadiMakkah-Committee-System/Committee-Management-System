"""أخطاء وحدة المهام — تترجمها طبقة الـAPI لأكواد HTTP (راجعي api/v1/tasks.py)."""


class TaskNotFoundError(Exception):
    """المهمة غير موجودة (أو محذوفة) — تُترجَم إلى 404."""


class TaskForbiddenError(Exception):
    """محاولة إجراء غير مسموح بها لهذا المستخدم تحديدًا — تُترجَم إلى 403."""


class TaskInvalidStateError(Exception):
    """محاولة إجراء لا تسمح به حالة المهمة الحالية (غالبًا completed) — تُترجَم إلى 409."""


class TaskValidationError(Exception):
    """خطأ تحقق من بيانات العمل — تُترجَم إلى 400."""
