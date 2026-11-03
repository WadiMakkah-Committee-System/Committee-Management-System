"""ترجمة استثناءات طبقة الخدمة إلى استجابات HTTP — مشتركة بين كل راوترات الاجتماعات."""

import logging

from fastapi import (
    HTTPException,
    status,
)

from app.core import acs_client, storage_client, teams_client
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
    # تكامل Microsoft Teams (migration 0041) — راجعي app/core/teams_client.py.
    teams_client.TeamsError,
    # تجربة الانضمام المدمج عبر Azure Communication Services.
    acs_client.AcsError,
)

logger = logging.getLogger(__name__)


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
    if isinstance(exc, teams_client.TeamsError):
        return _teams_error_to_http(exc)
    if isinstance(exc, acs_client.AcsError):
        logger.warning("Azure Communication Services error: %s", exc)
        if isinstance(exc, acs_client.AcsTeamsIdentityError):
            return HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="تعذّر الدخول بحساب Microsoft — تأكد أنك تستخدم حساب الشركة، أو ادخل كضيف",
            )
        if isinstance(exc, acs_client.AcsNotConfiguredError):
            return HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="الانضمام من داخل المنصة غير مُهيّأ بعد (ACS_CONNECTION_STRING) — استخدم فتح في تيمز",
            )
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="تعذّر تجهيز الاتصال بالاجتماع، حاول مرة أخرى بعد قليل",
        )
    if isinstance(exc, storage_client.StorageError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="تعذّر رفع الملف، حاول مرة أخرى"
        )
    raise exc


def _teams_error_to_http(exc: teams_client.TeamsError) -> HTTPException:
    """
    ترجمة أخطاء Microsoft Graph: التفاصيل الفنية (رموز Graph) تُسجَّل
    بالسجلات فقط، والمستخدم يرى رسالة عامة واضحة — بلا تسريب تفاصيل داخلية.
    - غير مهيّأ ⇒ 503 (إعداد ناقص بالبيئة، ليس خطأ المستخدم).
    - غير موجود بـTeams ⇒ 404 (مثلًا تسجيل انتهت مدة احتفاظه).
    - أي فشل آخر ⇒ 502 (خدمة خارجية).
    """
    logger.warning("Microsoft Teams error: %s", exc)
    if isinstance(exc, teams_client.TeamsNotConfiguredError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="تكامل Microsoft Teams غير مُهيّأ بعد (راجع إعدادات TEAMS_* بالبيئة)",
        )
    if isinstance(exc, teams_client.TeamsNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="العنصر المطلوب غير موجود في Microsoft Teams (ربما حُذف أو انتهت مدة الاحتفاظ به)",
        )
    # 403 من Graph = صلاحية ناقصة بتطبيق Entra (مو مشكلة مؤقتة) — نقولها صراحة
    # بدل "حاول مرة أخرى" اللي تخلي المستخدم يعيد بلا فايدة.
    if isinstance(exc, teams_client.TeamsForbiddenError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="رفضت Microsoft Teams الطلب: صلاحيات تطبيق المنصة لا تسمح بهذه العملية "
            "(تحتاج موافقة مدير Microsoft 365) — رمز الخطأ 403",
        )
    # رمز HTTP فقط (بدون رسالة Graph الداخلية) يسهّل تشخيص السبب من لقطة الشاشة.
    code = f" — رمز الخطأ {exc.status_code}" if exc.status_code else ""
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"تعذّر إتمام العملية مع Microsoft Teams، حاول مرة أخرى بعد قليل{code}",
    )
