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
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import agora_client, storage_client
from app.core.dependencies import CurrentUser
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
from app.services import meeting_service, notification_service
from app.services.document_service import DocumentValidationError
from app.services.meeting_service import (
    AgendaItemNotFoundError,
    AttachmentNotFoundError,
    DraftNotFoundError,
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
    MeetingForbiddenError,
    MeetingInvalidStateError,
    MeetingValidationError,
    DocumentValidationError,
    storage_client.StorageError,
)


def _handle_errors(exc: Exception) -> Exception:
    """يترجم استثناءات طبقة الخدمة إلى استجابات HTTP مناسبة، مركزيًا."""
    if isinstance(exc, (MeetingNotFoundError, AgendaItemNotFoundError, AttachmentNotFoundError, RecordingNotFoundError, DraftNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, MeetingForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, MeetingInvalidStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (MeetingValidationError, DocumentValidationError, ValueError)):
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
    background_tasks.add_task(notification_service.notify_meeting_created, meeting)
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
        background_tasks.add_task(notification_service.notify_meeting_updated, meeting, changes)
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
    background_tasks.add_task(notification_service.notify_meeting_cancelled, meeting)


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
        generated_by=CommitteeMemberUserOut.model_validate(draft.generator),
        generated_at=draft.generated_at,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
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
