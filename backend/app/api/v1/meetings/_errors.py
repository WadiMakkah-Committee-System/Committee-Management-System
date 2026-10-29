"""ترجمة استثناءات طبقة الخدمة إلى استجابات HTTP — مشتركة بين كل راوترات الاجتماعات."""


from fastapi import (
    HTTPException,
    status,
)

from app.core import agora_client, storage_client
from app.services.meeting_minutes_service import (
    MinutesForbiddenError,
    MinutesInvalidStateError,
    MinutesNotFoundError,
    MinutesValidationError,
)
from app.services.decision_service import (
    DecisionForbiddenError,
    DecisionInvalidStateError,
    DecisionValidationError,
)
from app.services.document_service import DocumentValidationError
from app.services.task_service import TaskForbiddenError, TaskInvalidStateError, TaskValidationError
from app.services.meeting_service import (
    AgendaItemNotFoundError,
    AttachmentNotFoundError,
    DraftNotFoundError,
    ExtractedItemNotFoundError,
    MeetingForbiddenError,
    MeetingInvalidStateError,
    MeetingNotFoundError,
    MeetingValidationError,
    RecordingNotFoundError,
)
from app.core.committee_period import CommitteePeriodError


_SERVICE_ERRORS = (
    MeetingNotFoundError,
    AgendaItemNotFoundError,
    AttachmentNotFoundError,
    RecordingNotFoundError,
    DraftNotFoundError,
    ExtractedItemNotFoundError,
    MeetingForbiddenError,
    MeetingInvalidStateError,
    MeetingValidationError,
    DocumentValidationError,
    storage_client.StorageError,
    # نتائج task_service.create_task/decision_service.create_decision —
    # تُستدعى مباشرة من meeting_service.assign_extracted_item_as_task/
    # _as_decision (راجعي رأس meeting_service.py، قسم "البنود المستخرجة")
    # فتُعالَج بنفس نقطة الخطأ المركزية هنا بدل تكرارها.
    TaskForbiddenError,
    TaskInvalidStateError,
    TaskValidationError,
    DecisionForbiddenError,
    DecisionInvalidStateError,
    DecisionValidationError,
    MinutesNotFoundError,
    MinutesForbiddenError,
    MinutesInvalidStateError,
    MinutesValidationError,
    # إصلاح 2026-09-14 (بلاغ لاما — "Network Error" حقيقي/CORS مضلِّل عند
    # إنشاء اجتماع): CommitteePeriodError (app/core/committee_period.py)
    # ترث من ValueError وتوثيقها بنفسها يقول "تُترجَم تلقائيًا إلى 400" —
    # لكنها لم تكن مذكورة هنا إطلاقًا بهذا التuple، فـ except أدناه ما كان
    # يمسكها أصلًا (بغض النظر عن كون _handle_errors تتعامل مع ValueError
    # بشكل عام — لا فرق لأن الاستثناء يفلت قبل ما يوصل لها). أي تاريخ
    # اجتماع (أو نهايته) خارج فترة عمل اللجنة كان يُسبّب 500 حقيقي غير
    # معالَج — نفس الخلل بالضبط بـdecisions.py وtasks.py (CommitteePeriodError
    # تُستخدَم بالثلاثة، أضفتها هناك كمان).
    CommitteePeriodError,
)


def _handle_errors(exc: Exception) -> Exception:
    """يترجم استثناءات طبقة الخدمة إلى استجابات HTTP مناسبة، مركزيًا."""
    if isinstance(exc, (MeetingNotFoundError, AgendaItemNotFoundError, AttachmentNotFoundError, RecordingNotFoundError, DraftNotFoundError, ExtractedItemNotFoundError, MinutesNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (MeetingForbiddenError, TaskForbiddenError, DecisionForbiddenError, MinutesForbiddenError)):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, (MeetingInvalidStateError, TaskInvalidStateError, DecisionInvalidStateError, MinutesInvalidStateError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (MeetingValidationError, DocumentValidationError, TaskValidationError, DecisionValidationError, MinutesValidationError, ValueError)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, storage_client.StorageError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="تعذّر رفع الملف، حاول مرة أخرى"
        )
    raise exc


def _agora_error_to_http(exc: agora_client.AgoraError) -> HTTPException:
    if isinstance(exc, agora_client.AgoraNotConfiguredError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="خدمة الاجتماعات المرئية غير مُهيّأة بعد (راجع إعدادات AGORA_* بالبيئة)",
        )
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
