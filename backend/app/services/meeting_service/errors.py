"""استثناءات وحدة الاجتماعات — تُترجَم إلى رموز HTTP بطبقة الـAPI
(راجعي app/api/v1/meetings/_errors.py)."""


class MeetingNotFoundError(Exception):
    """الاجتماع غير موجود (أو محذوف) — تُترجَم إلى 404 في طبقة الـ API."""


class AgendaItemNotFoundError(Exception):
    """بند جدول الأعمال غير موجود — تُترجَم إلى 404."""


class AttachmentNotFoundError(Exception):
    """المرفق غير موجود أو غير مرتبط بهذا الاجتماع — تُترجَم إلى 404."""


class MeetingForbiddenError(Exception):
    """محاولة إجراء غير مسموح بها لهذا المستخدم تحديدًا — تُترجَم إلى 403."""


class MeetingInvalidStateError(Exception):
    """محاولة تعديل/حذف اجتماع في حالة لا تسمح بذلك (مثال: بعد انعقاده) — تُترجَم إلى 409."""


class MeetingValidationError(Exception):
    """خطأ تحقق من بيانات العمل (مثال: مكان الاجتماع مفقود لحضوري) — تُترجَم إلى 400."""



class RecordingNotFoundError(Exception):
    """لا يوجد تسجيل صوتي مرفوع لهذا الاجتماع — تُترجَم إلى 404."""


class DraftNotFoundError(Exception):
    """لا توجد مسودة مولَّدة بعد لهذا الاجتماع — تُترجَم إلى 404."""


class ExtractedItemNotFoundError(Exception):
    """البند المستخرج غير موجود — تُترجَم إلى 404."""

