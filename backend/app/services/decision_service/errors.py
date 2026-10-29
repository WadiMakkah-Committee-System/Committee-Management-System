"""أخطاء وحدة القرارات — تترجمها طبقة الـAPI لأكواد HTTP (راجعي api/v1/decisions.py)."""


class DecisionNotFoundError(Exception):
    """القرار غير موجود (أو محذوف) — تُترجَم إلى 404."""


class DecisionForbiddenError(Exception):
    """محاولة إجراء غير مسموح بها لهذا المستخدم تحديدًا — تُترجَم إلى 403."""


class DecisionInvalidStateError(Exception):
    """محاولة إجراء لا تسمح به حالة القرار الحالية — تُترجَم إلى 409."""


class DecisionValidationError(Exception):
    """خطأ تحقق من بيانات العمل — تُترجَم إلى 400."""
