"""
الهدف:
راوتات REST لوحدة "إدارة الاجتماعات" (Phase 2 + مرفقات الاجتماع). بدون
أي تكامل فعلي مع Microsoft Teams/Graph API — راجعي رأس
app/services/meeting_service.py لتفصيل القرار الموثّق.

ملاحظة مهمة (لماذا لا تستخدم راوتات الإنشاء/التعديل/الحذف require_permission
على مستوى الراوت، بخلاف committees.py): التفويض هنا يعتمد على اللجنة
المحدَّدة بالطلب تحديدًا (Committee Role الخاص بعضوية actor في *تلك*
اللجنة بالذات) وليس فقط على دوره العام — فلا يمكن فحصه بمعزل عن تحميل
السجل نفسه أولًا. يُفرض بالكامل داخل meeting_service.

ملاحظة تقنية: دوال meeting_service (create/update/delete_meeting،
add/update/delete_agenda_item، add/delete_attachment) تُنفّذ commit/rollback
داخليًا بنفسها الآن (بخلاف نمط committees.py الذي يترك الـcommit للراوت) —
ضروري لأن add_attachment يستدعي document_service.create_document الذي
يُنهي معاملته (transaction) الخاصة به بالكامل قبل أن يعود، فلا يمكن تأجيل
الـcommit لهذا الجزء إلى الراوت. طُبِّق نفس النمط على بقية دوال الوحدة
هنا للاتساق، بدل خلط الأسلوبين داخل نفس الملف. الاستثناء الوحيد:
join_meeting/leave_meeting (تكامل Agora) — تُبقي الـcommit/rollback على
مستوى الراوت عمدًا (راجعي تعليق القسم أدناه).
"""

import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import agora_client, storage_client
from app.core.dependencies import CurrentUser, CurrentUserWS
from app.core.meeting_realtime import connection_manager
from app.db.session import get_db
from app.schemas.committee import CommitteeMemberUserOut
from app.schemas.meeting import (
    MeetingAgendaItemCreate,
    MeetingAgendaItemOut,
    MeetingAgendaItemUpdate,
    MeetingAttachmentKind,
    MeetingAttachmentOut,
    MeetingCreate,
    MeetingJoinOut,
    MeetingOut,
    MeetingUpdate,
)
from app.schemas.meeting_draft import MeetingDraftOut, MeetingRecordingOut
from app.schemas.meeting_chat import MeetingChatMessageOut
from app.schemas.meeting_extracted_item import (
    ExtractedItemAssignAsDecision,
    ExtractedItemAssignAsTask,
    ExtractedItemManualCreate,
    MeetingExtractedItemOut,
)
from app.services import meeting_chat_service, meeting_service, notification_service
from app.services.meeting_chat_service import MeetingChatForbiddenError, MeetingChatNotFoundError
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

router = APIRouter(prefix="/meetings", tags=["meetings"])

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
)


def _handle_errors(exc: Exception) -> Exception:
    """يترجم استثناءات طبقة الخدمة إلى استجابات HTTP مناسبة، مركزيًا."""
    if isinstance(exc, (MeetingNotFoundError, AgendaItemNotFoundError, AttachmentNotFoundError, RecordingNotFoundError, DraftNotFoundError, ExtractedItemNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (MeetingForbiddenError, TaskForbiddenError, DecisionForbiddenError)):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, (MeetingInvalidStateError, TaskInvalidStateError, DecisionInvalidStateError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (MeetingValidationError, DocumentValidationError, TaskValidationError, DecisionValidationError, ValueError)):
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


@router.post("", response_model=MeetingOut, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingCreate,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> MeetingOut:
    try:
        meeting = await meeting_service.create_meeting(
            db,
            actor=current_user,
            committee_id=payload.committee_id,
            title=payload.title,
            description=payload.description,
            mode=payload.mode,
            location=payload.location,
            scheduled_at=payload.scheduled_at,
            scheduled_end_at=payload.scheduled_end_at,
            agenda_items=[item.model_dump() for item in payload.agenda_items],
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    # إشعار بريدي لأعضاء اللجنة كـBackgroundTask (بعد commit الناجح) — لا
    # يُبطئ استجابة إنشاء الاجتماع، ولا يُفشلها لو تعذّر إرسال البريد
    # (راجعي core/email_client.py وservices/notification_service.py).
    background_tasks.add_task(
        notification_service.notify_meeting_created, meeting, actor_user_id=current_user.user_id
    )
    return MeetingOut.model_validate(meeting)


@router.get("", response_model=list[MeetingOut])
async def list_meetings(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[MeetingOut]:
    meetings = await meeting_service.list_meetings(db, actor=current_user)
    return [MeetingOut.model_validate(m) for m in meetings]


@router.get("/{meeting_id}", response_model=MeetingOut)
async def get_meeting(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingOut:
    try:
        meeting = await meeting_service.get_meeting(db, meeting_id, actor=current_user)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return MeetingOut.model_validate(meeting)


@router.patch("/{meeting_id}", response_model=MeetingOut)
async def update_meeting(
    meeting_id: uuid.UUID,
    payload: MeetingUpdate,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> MeetingOut:
    try:
        meeting, changes = await meeting_service.update_meeting(
            db,
            actor=current_user,
            meeting_id=meeting_id,
            title=payload.title,
            description=payload.description,
            mode=payload.mode,
            mode_set="mode" in payload.model_fields_set,
            location=payload.location,
            location_set="location" in payload.model_fields_set,
            scheduled_at=payload.scheduled_at,
            scheduled_end_at=payload.scheduled_end_at,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    # إشعار بريدي لأعضاء اللجنة فقط لو تغيّر أحد "الحقول المهمة" (راجعي
    # docstring meeting_service.update_meeting وnotification_service.py) —
    # قرار لاما 2026-09-06. notify_meeting_updated نفسها لا ترسل شيئًا لو
    # changes فارغة، فالفحص هنا للوضوح فقط (تفادي جدولة Task فارغة).
    if changes:
        background_tasks.add_task(
            notification_service.notify_meeting_updated,
            meeting,
            changes,
            actor_user_id=current_user.user_id,
        )
    return MeetingOut.model_validate(meeting)


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(
    meeting_id: uuid.UUID,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        meeting = await meeting_service.delete_meeting(db, actor=current_user, meeting_id=meeting_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    # إشعار إلغاء لأعضاء اللجنة — meeting هنا لسه محمَّل بالكامل بالذاكرة
    # (committee/participants كلاهما lazy="selectin")، رغم إن db.commit()
    # صار قبله مباشرة داخل meeting_service.delete_meeting —
    # expire_on_commit=False بـdb/session.py يضمن بقاء القيم المحمَّلة أصلًا
    # صالحة بلا استعلام إضافي (راجعي notification_service.py).
    background_tasks.add_task(
        notification_service.notify_meeting_cancelled, meeting, actor_user_id=current_user.user_id
    )


# ============================== الانضمام لاجتماع عن بعد (Agora) ==============================
# join_meeting/leave_meeting تُبقي commit/rollback على مستوى الراوت عمدًا
# (بخلاف بقية دوال الوحدة) — meeting_service.join_meeting يُصدر Token عبر
# Agora قبل أي db.add، فلو فشل استدعاء Agora لا شيء التُزم أصلًا بعد.


@router.post("/{meeting_id}/join", response_model=MeetingJoinOut)
async def join_meeting(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingJoinOut:
    try:
        _meeting, join_info = await meeting_service.join_meeting(
            db, actor=current_user, meeting_id=meeting_id
        )
        await db.commit()
    except (MeetingNotFoundError, MeetingForbiddenError, MeetingInvalidStateError) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc
    except agora_client.AgoraError as exc:
        await db.rollback()
        raise _agora_error_to_http(exc) from exc
    return MeetingJoinOut(
        app_id=join_info.app_id,
        channel=join_info.channel,
        token=join_info.token,
        uid=join_info.uid,
        expires_at=join_info.expires_at,
    )


@router.post("/{meeting_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_meeting(
    meeting_id: uuid.UUID,
    current_user: CurrentUser,
    agora_uid: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await meeting_service.leave_meeting(
            db, actor=current_user, meeting_id=meeting_id, agora_uid=agora_uid
        )
        await db.commit()
    except (MeetingNotFoundError, MeetingForbiddenError) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc


@router.post(
    "/{meeting_id}/agenda-items",
    response_model=MeetingAgendaItemOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_agenda_item(
    meeting_id: uuid.UUID,
    payload: MeetingAgendaItemCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingAgendaItemOut:
    try:
        item = await meeting_service.add_agenda_item(
            db,
            actor=current_user,
            meeting_id=meeting_id,
            title=payload.title,
            description=payload.description,
            sort_order=payload.sort_order,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return MeetingAgendaItemOut.model_validate(item)


@router.patch("/agenda-items/{agenda_item_id}", response_model=MeetingAgendaItemOut)
async def update_agenda_item(
    agenda_item_id: uuid.UUID,
    payload: MeetingAgendaItemUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingAgendaItemOut:
    try:
        item = await meeting_service.update_agenda_item(
            db,
            actor=current_user,
            agenda_item_id=agenda_item_id,
            title=payload.title,
            description=payload.description,
            sort_order=payload.sort_order,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return MeetingAgendaItemOut.model_validate(item)


@router.delete("/agenda-items/{agenda_item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agenda_item(
    agenda_item_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    try:
        await meeting_service.delete_agenda_item(
            db, actor=current_user, agenda_item_id=agenda_item_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc


def _attachment_out(document, kind: str, linked_at) -> MeetingAttachmentOut:
    return MeetingAttachmentOut(
        document_id=document.document_id,
        kind=kind,
        title=document.title,
        file_name=document.file_name,
        mime_type=document.mime_type,
        file_size_bytes=document.file_size_bytes,
        uploaded_by=CommitteeMemberUserOut.model_validate(document.uploader),
        linked_at=linked_at,
    )


@router.post(
    "/{meeting_id}/attachments",
    response_model=MeetingAttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_meeting_attachment(
    meeting_id: uuid.UUID,
    current_user: CurrentUser,
    kind: MeetingAttachmentKind = Form(...),
    file: UploadFile = File(...),
    title: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> MeetingAttachmentOut:
    """
    رفع مرفق (kind='attachment') أو عرض تقديمي (kind='presentation')
    وربطه بالاجتماع مباشرة — multipart/form-data بنفس نمط
    POST /documents (documents.py)، وليس JSON، لأن الملف الفعلي يمر عبر
    الـBackend إلى Supabase Storage.
    """
    content = await file.read()
    try:
        document, linked_at = await meeting_service.add_attachment(
            db,
            actor=current_user,
            meeting_id=meeting_id,
            kind=kind,
            title=title or file.filename or "بدون عنوان",
            file_name=file.filename or "unnamed",
            mime_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return _attachment_out(document, kind, linked_at)


@router.get("/{meeting_id}/attachments", response_model=list[MeetingAttachmentOut])
async def list_meeting_attachments(
    meeting_id: uuid.UUID,
    current_user: CurrentUser,
    kind: MeetingAttachmentKind | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[MeetingAttachmentOut]:
    try:
        rows = await meeting_service.list_attachments(
            db, actor=current_user, meeting_id=meeting_id, kind=kind
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return [_attachment_out(document, k, linked_at) for document, k, linked_at in rows]


@router.get("/{meeting_id}/attachments/{document_id}/download")
async def download_meeting_attachment(
    meeting_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    تنزيل محتوى المرفق مباشرة — مسار مخصص بوحدة الاجتماعات (وليس عبر
    GET /documents/{document_id}/download العام) لأن ذلك المسار محمي
    بصلاحية Role نظامية ثابتة (documents.download) لا يملكها عضو اللجنة
    العادي غالبًا، بينما هنا يكفي أن يملك meetings.attachments.view على
    نفس اللجنة (راجعي meeting_service.get_attachment_download).
    """
    try:
        document, content = await meeting_service.get_attachment_download(
            db, actor=current_user, meeting_id=meeting_id, document_id=document_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return Response(
        content=content,
        media_type=document.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{document.file_name}"'},
    )


@router.delete(
    "/{meeting_id}/attachments/{document_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_meeting_attachment(
    meeting_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await meeting_service.delete_attachment(
            db, actor=current_user, meeting_id=meeting_id, document_id=document_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc



# ============================== التسجيل الصوتي + المسودة (AI) ==============================
# راجعي رأس app/services/meeting_service.py (قسم "التسجيل الصوتي +
# المسودة") لتفصيل التفويض والتصميم. ملاحظة: generate_draft لا يرمي
# GeminiError للراوت مباشرة — تلتقطه طبقة الخدمة داخليًا وتخزّن
# status='failed' + error_message بجدول meeting_drafts، فتُعاد استجابة
# 200 عادية بحالة "failed" بدل خطأ HTTP (الواجهة تعرض رسالة الخطأ من
# الحقل نفسه). هذا قرار مقصود: فشل استدعاء خارجي (Gemini) ليس خطأ من
# المستخدم يستحق 4xx/5xx، بل نتيجة عملية طويلة تُحفَظ وتُعرَض كما هي.


def _recording_out(recording) -> MeetingRecordingOut:
    return MeetingRecordingOut(
        recording_id=recording.recording_id,
        file_name=recording.file_name,
        mime_type=recording.mime_type,
        file_size_bytes=recording.file_size_bytes,
        duration_seconds=recording.duration_seconds,
        recorded_by=CommitteeMemberUserOut.model_validate(recording.recorder),
        recorded_at=recording.recorded_at,
    )


def _draft_out(draft) -> MeetingDraftOut:
    return MeetingDraftOut(
        draft_id=draft.draft_id,
        meeting_id=draft.meeting_id,
        status=draft.status.value,
        error_message=draft.error_message,
        full_transcript=draft.full_transcript,
        summary=draft.summary,
        decisions=draft.decisions,
        action_items=draft.action_items,
        key_points=draft.key_points,
        recommendations=draft.recommendations,
        open_items=draft.open_items,
        compliance_notes=draft.compliance_notes,
        generated_by=CommitteeMemberUserOut.model_validate(draft.generator),
        generated_at=draft.generated_at,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


def _extracted_item_out(item) -> MeetingExtractedItemOut:
    return MeetingExtractedItemOut(
        item_id=item.item_id,
        meeting_id=item.meeting_id,
        text=item.text,
        source=item.source,
        status=item.status.value,
        linked_task_id=item.linked_task_id,
        linked_decision_id=item.linked_decision_id,
        created_by=CommitteeMemberUserOut.model_validate(item.creator),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.post(
    "/{meeting_id}/recording",
    response_model=MeetingRecordingOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_meeting_recording(
    meeting_id: uuid.UUID,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    duration_seconds: int | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> MeetingRecordingOut:
    """رفع تسجيل صوتي للاجتماع (FR: تسجيل الاجتماع صوتيًا) — يتطلب
    meetings.record_audio. multipart/form-data بنفس نمط رفع المرفقات."""
    content = await file.read()
    try:
        recording = await meeting_service.upload_recording(
            db,
            actor=current_user,
            meeting_id=meeting_id,
            file_name=file.filename or "recording",
            mime_type=file.content_type or "application/octet-stream",
            content=content,
            duration_seconds=duration_seconds,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return _recording_out(recording)


@router.get("/{meeting_id}/recording", response_model=MeetingRecordingOut)
async def get_meeting_recording(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingRecordingOut:
    try:
        recording = await meeting_service.get_latest_recording(
            db, actor=current_user, meeting_id=meeting_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return _recording_out(recording)


@router.get("/{meeting_id}/recording/download")
async def download_meeting_recording(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> Response:
    try:
        recording, content = await meeting_service.download_recording(
            db, actor=current_user, meeting_id=meeting_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return Response(
        content=content,
        media_type=recording.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{recording.file_name}"'},
    )


@router.post("/{meeting_id}/draft", response_model=MeetingDraftOut, status_code=status.HTTP_201_CREATED)
async def generate_meeting_draft(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingDraftOut:
    """تحويل تسجيل الاجتماع الصوتي إلى مسودة بالذكاء الاصطناعي (FR-AI-001)
    — يتطلب meetings.draft.summarize، وتسجيلًا صوتيًا مرفوعًا مسبقًا.
    مزامنة (لا Background Job) — قد يأخذ الطلب دقيقة أو أكثر لاجتماع
    طويل (رفع الملف لـGemini + المعالجة). راجعي meeting_service.generate_draft."""
    try:
        draft = await meeting_service.generate_draft(db, actor=current_user, meeting_id=meeting_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return _draft_out(draft)


@router.get("/{meeting_id}/draft", response_model=MeetingDraftOut)
async def get_meeting_draft(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingDraftOut:
    try:
        draft = await meeting_service.get_draft(db, actor=current_user, meeting_id=meeting_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return _draft_out(draft)


# ============================== البنود المستخرجة من الاجتماع ==============================
# FR-TASK-005 إلى FR-TASK-012 + FR-DEC-001 إلى FR-DEC-004 — راجعي رأس
# meeting_service.py (قسم "البنود المستخرجة من الاجتماع") للتصميم الكامل
# والصلاحيات المطلوبة لكل مسار.


@router.post(
    "/{meeting_id}/extracted-items/extract",
    response_model=list[MeetingExtractedItemOut],
    status_code=status.HTTP_201_CREATED,
)
async def extract_meeting_items(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[MeetingExtractedItemOut]:
    """FR-TASK-005/UC2: استخراج بنود جديدة من ملخص المسودة (يتطلب مسودة
    مكتملة مسبقًا + meetings.draft.summarize)."""
    try:
        items = await meeting_service.extract_meeting_items(
            db, actor=current_user, meeting_id=meeting_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return [_extracted_item_out(item) for item in items]


@router.get("/{meeting_id}/extracted-items", response_model=list[MeetingExtractedItemOut])
async def list_meeting_extracted_items(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[MeetingExtractedItemOut]:
    try:
        items = await meeting_service.list_extracted_items(
            db, actor=current_user, meeting_id=meeting_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return [_extracted_item_out(item) for item in items]


@router.post(
    "/{meeting_id}/extracted-items",
    response_model=MeetingExtractedItemOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_meeting_extracted_item(
    meeting_id: uuid.UUID,
    payload: ExtractedItemManualCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingExtractedItemOut:
    """FR-TASK-007/UC4: إضافة بند يدوي."""
    try:
        item = await meeting_service.add_manual_extracted_item(
            db, actor=current_user, meeting_id=meeting_id, text=payload.text
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return _extracted_item_out(item)


@router.delete(
    "/{meeting_id}/extracted-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_meeting_extracted_item(
    meeting_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """FR-TASK-009/UC6: حذف بند (متاح فقط طالما pending)."""
    try:
        await meeting_service.delete_extracted_item(db, actor=current_user, item_id=item_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc


@router.post(
    "/{meeting_id}/extracted-items/{item_id}/assign-task",
    response_model=MeetingExtractedItemOut,
)
async def assign_extracted_item_as_task(
    meeting_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ExtractedItemAssignAsTask,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> MeetingExtractedItemOut:
    """FR-TASK-010/011/UC7/UC8: تعيين البند كمهمة — ينشئ Task حقيقيًا عبر
    task_service.create_task (tasks.create)."""
    try:
        item, task = await meeting_service.assign_extracted_item_as_task(
            db,
            actor=current_user,
            item_id=item_id,
            title=payload.title,
            start_date=payload.start_date,
            end_date=payload.end_date,
            assignee_user_id=payload.assignee_user_id,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    # إشعار المُسنَد إليه — بنفس استدعاء POST /tasks تمامًا (راجعي
    # docstring meeting_service.assign_extracted_item_as_task: هذا
    # المسار كان يتخطى tasks.py فيفوّت الإشعار قبل هذا الإصلاح).
    background_tasks.add_task(
        notification_service.notify_task_created, task, actor_user_id=current_user.user_id
    )
    return _extracted_item_out(item)


@router.post(
    "/{meeting_id}/extracted-items/{item_id}/assign-decision",
    response_model=MeetingExtractedItemOut,
)
async def assign_extracted_item_as_decision(
    meeting_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ExtractedItemAssignAsDecision,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> MeetingExtractedItemOut:
    """FR-DEC-004/UC7: تعيين البند كقرار — ينشئ Decision حقيقيًا عبر
    decision_service.create_decision (decisions.create)، مربوطًا
    بالاجتماع المصدر تلقائيًا."""
    try:
        item, decision = await meeting_service.assign_extracted_item_as_decision(
            db,
            actor=current_user,
            item_id=item_id,
            title=payload.title,
            classification=payload.classification,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    background_tasks.add_task(
        notification_service.notify_decision_created, decision, actor_user_id=current_user.user_id
    )
    return _extracted_item_out(item)



# ============================== القناة اللحظية (WebSocket) ==============================
# محادثة الاجتماع + رفع اليد + بث "بند الأجندة قيد المناقشة الآن" —
# راجعي رأس app/core/meeting_realtime.py وdb/migrations/0026_meeting_realtime.sql
# للتصميم الكامل والقرار الموثّق (WebSocket حقيقي بدل Polling، 2026-09-06).


@router.get("/{meeting_id}/chat/messages", response_model=list[MeetingChatMessageOut])
async def get_meeting_chat_messages(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[MeetingChatMessageOut]:
    """تحميل تاريخ المحادثة عند فتح لوحة "المحادثة" — الرسائل الجديدة بعدها
    تصل عبر WebSocket (meeting_live_socket أدناه) لا عبر Polling على هذا
    الراوت. يتطلب meetings.join (نفس صلاحية الانضمام للاجتماع)."""
    try:
        messages = await meeting_chat_service.list_messages(
            db, actor=current_user, meeting_id=meeting_id
        )
    except MeetingChatNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MeetingChatForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return [MeetingChatMessageOut.model_validate(m) for m in messages]


@router.websocket("/{meeting_id}/live")
async def meeting_live_socket(
    websocket: WebSocket,
    meeting_id: uuid.UUID,
    current_user: CurrentUserWS,
    db: AsyncSession = Depends(get_db),
) -> None:
    """القناة اللحظية لغرفة الاجتماع — راجعي app/core/meeting_realtime.py.
    المصادقة عبر Query Param (?token=...، راجعي app/core/dependencies.py::
    get_current_user_ws) لأن اتصال WebSocket من المتصفح لا يقدر يحمل
    Authorization Header مخصص. رفع اليد وبند الأجندة الحالي أحداث عابرة
    فقط (تُبث ولا تُحفَظ بقاعدة البيانات — راجعي تعليق meeting_realtime.py)،
    بخلاف رسائل المحادثة (تُحفَظ فعليًا عبر meeting_chat_service.send_message).

    ملاحظة أداء موثّقة عمدًا: جلسة db تبقى مفتوحة طوال عمر الاتصال (قد
    يكون طول الاجتماع كاملًا) — مقبول بحجم هذا المشروع (عملية Backend
    واحدة، اجتماعات بعدد مشاركين محدود)؛ لو كبر الحجم لاحقًا يحتاج فتح
    جلسة قصيرة العمر فقط عند كل حدث كتابة (رسالة محادثة) بدل جلسة واحدة
    ثابتة طوال الاتصال.
    """
    try:
        await meeting_chat_service.require_realtime_access(
            db, actor=current_user, meeting_id=meeting_id
        )
    except (MeetingChatNotFoundError, MeetingChatForbiddenError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await connection_manager.connect(meeting_id, websocket)
    await connection_manager.broadcast(
        meeting_id,
        {
            "type": "presence.joined",
            "user_id": str(current_user.user_id),
            "full_name": current_user.full_name,
        },
    )

    try:
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except Exception:
                # حمولة غير صالحة (JSON تالف مثلًا) — تُتجاهَل ويستمر الاتصال،
                # بدل قطعه بالكامل بسبب رسالة واحدة سيئة.
                continue

            event_type = data.get("type") if isinstance(data, dict) else None

            if event_type == "chat.send":
                body = str(data.get("body", "")).strip()
                if not body:
                    continue
                try:
                    message = await meeting_chat_service.send_message(
                        db, actor=current_user, meeting_id=meeting_id, body=body
                    )
                except ValueError:
                    continue
                await connection_manager.broadcast(
                    meeting_id,
                    {
                        "type": "chat.message",
                        "message": MeetingChatMessageOut.model_validate(message).model_dump(
                            mode="json"
                        ),
                    },
                )

            elif event_type == "hand.raise":
                await connection_manager.broadcast(
                    meeting_id,
                    {
                        "type": "hand.raised",
                        "user_id": str(current_user.user_id),
                        "full_name": current_user.full_name,
                    },
                )

            elif event_type == "hand.lower":
                await connection_manager.broadcast(
                    meeting_id,
                    {"type": "hand.lowered", "user_id": str(current_user.user_id)},
                )

            elif event_type == "agenda.discussing":
                agenda_item_id = data.get("agenda_item_id")
                title = data.get("title")
                if agenda_item_id and title:
                    await connection_manager.broadcast(
                        meeting_id,
                        {
                            "type": "agenda.discussing",
                            "agenda_item_id": agenda_item_id,
                            "title": title,
                        },
                    )
    finally:
        connection_manager.disconnect(meeting_id, websocket)
        await connection_manager.broadcast(
            meeting_id,
            {
                "type": "presence.left",
                "user_id": str(current_user.user_id),
                "full_name": current_user.full_name,
            },
        )
