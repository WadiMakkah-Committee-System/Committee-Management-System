"""التسجيل الصوتي + مسودة الذكاء الاصطناعي + البنود المستخرجة."""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import run_detached
from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.committee import CommitteeMemberUserOut
from app.schemas.meeting_draft import MeetingDraftOut, MeetingRecordingOut
from app.schemas.meeting_extracted_item import (
    ExtractedItemAssignAsDecision,
    ExtractedItemAssignAsTask,
    ExtractedItemManualCreate,
    MeetingExtractedItemOut,
)
from app.services import meeting_service, notification_service

from app.api.v1.documents import _content_disposition
from app.api.v1.meetings._errors import _SERVICE_ERRORS, _handle_errors

router = APIRouter(prefix="/meetings", tags=["meetings"])


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


def _draft_out(
    draft,
    *,
    can_view_transcript: bool = True,
    can_view_summary: bool = True,
    can_view_full: bool = True,
) -> MeetingDraftOut:
    """
    تحديث 2026-09-16 (تفصيل صلاحيات عرض المسودة — راجعي رأس
    db/migrations/0035 وmeeting_service.get_draft للخلفية الكاملة):
    كل المعاملات افتراضيًا True هنا (مسار generate_meeting_draft أدناه —
    لا يصله إلا من يملك meetings.draft.summarize أصلًا، فمن المنطقي يشوف
    كل ما ولّده لتوّه) — get_meeting_draft وحدها تُمرّر القيم الفعلية
    المحسوبة من get_draft. can_view_full تحديدًا تتحكم بالحقول
    "الإدارية" (القرارات/المهام/نقاط مهمة/التوصيات/نقاط معلّقة/ملاحظات
    الالتزام) التي لم تطلب لاما توسيعها لعضو اللجنة — تبقى حصرًا لمن يملك
    meetings.draft.view الكاملة، حتى لو مَلَك transcript.view/summary.view
    فقط. الإخفاء هنا استبدال بـNone/[] فقط عند False، وليس حذفًا للحقل.
    """
    return MeetingDraftOut(
        draft_id=draft.draft_id,
        meeting_id=draft.meeting_id,
        status=draft.status.value,
        error_message=draft.error_message,
        full_transcript=draft.full_transcript if can_view_transcript else None,
        summary=draft.summary if can_view_summary else None,
        can_view_transcript=can_view_transcript,
        can_view_summary=can_view_summary,
        decisions=draft.decisions if can_view_full else None,
        action_items=draft.action_items if can_view_full else None,
        key_points=draft.key_points if can_view_full else None,
        recommendations=draft.recommendations if can_view_full else None,
        open_items=draft.open_items if can_view_full else None,
        compliance_notes=draft.compliance_notes if can_view_full else None,
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
        headers={"Content-Disposition": _content_disposition(recording.file_name)},
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
        draft, can_view_transcript, can_view_summary, can_view_full = await meeting_service.get_draft(
            db, actor=current_user, meeting_id=meeting_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return _draft_out(
        draft,
        can_view_transcript=can_view_transcript,
        can_view_summary=can_view_summary,
        can_view_full=can_view_full,
    )


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
    run_detached(
        notification_service.notify_task_created(task, actor_user_id=current_user.user_id)
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
    run_detached(
        notification_service.notify_decision_created(decision, actor_user_id=current_user.user_id)
    )
    return _extracted_item_out(item)
