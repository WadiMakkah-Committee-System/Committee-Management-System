"""إنشاء/عرض/قائمة/تعديل/حذف الاجتماعات + الانضمام/المغادرة + جدول الأعمال."""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import agora_client
from app.core.background import run_detached
from app.core.config import settings
from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.meeting import (
    MeetingAgendaItemCreate,
    MeetingAgendaItemOut,
    MeetingAgendaItemUpdate,
    MeetingCreate,
    MeetingExtend,
    MeetingCreateWithAttachmentsOut,
    MeetingJoinOut,
    MeetingListItem,
    MeetingOut,
    MeetingUpdate,
)
from app.services import meeting_service, notification_service, user_service
from app.services.meeting_service import (
    MeetingForbiddenError,
    MeetingInvalidStateError,
    MeetingNotFoundError,
)

from app.api.v1.meetings._errors import _SERVICE_ERRORS, _agora_error_to_http, _handle_errors

router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.post("", response_model=MeetingOut, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingCreate,
    current_user: CurrentUser,
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
    # إشعار بريدي لأعضاء اللجنة عبر run_detached (بعد commit الناجح) — لا
    # يُبطئ استجابة إنشاء الاجتماع، ولا يُفشلها لو تعذّر إرسال البريد، ولا
    # يُبقي جلسة db الخاصة بهذا الطلب محجوزة أثناء انتظار SMTP (تحقيق أداء
    # لاما 2026-09-15 — راجعي core/background.py وcore/email_client.py
    # وservices/notification_service.py).
    run_detached(
        notification_service.notify_meeting_created(meeting, actor_user_id=current_user.user_id)
    )
    return MeetingOut.model_validate(meeting)


@router.post(
    "/with-attachments",
    response_model=MeetingCreateWithAttachmentsOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_meeting_with_attachments(
    current_user: CurrentUser,
    payload: str = Form(..., description="MeetingCreate كـJSON"),
    presentation: UploadFile | None = File(None),
    attachments: list[UploadFile] = File(default=[]),
    agenda_files: list[UploadFile] = File(default=[]),
    agenda_file_indexes: list[int] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
) -> MeetingCreateWithAttachmentsOut:
    """
    POST /meetings/with-attachments (multipart) — طلب لاما 2026-11-01:
    "إيميل واحد بكل شي". ينشئ الاجتماع وجدول أعماله، ثم يرفع العرض التقديمي
    ومرفقات الاجتماع ومرفقات كل بند، وبعدها فقط يُرسل بريد "اجتماع جديد" واحد
    لكل مشارك فيه جدول الأعمال والملفات (حتى 10 ميجا مرفقة، والباقي باسمه).

    الحقول:
    - payload: نفس جسم POST /meetings (MeetingCreate) كنص JSON.
    - presentation / attachments: العرض التقديمي ومرفقات الاجتماع العامة.
    - agenda_files + agenda_file_indexes: لكل ملف بند رقم البند (ترتيبه
      بـpayload.agenda_items، يبدأ من 0) — نفس الطول بالضبط.

    الصلاحيات: meetings.schedule للإنشاء، وmeetings.attachments.add للملفات
    (نفس المسارات المنفصلة). الاستجابات: 201 {meeting, failed_files} — لو
    تعذّر رفع ملف بعد إنشاء الاجتماع يبقى الاجتماع ويُذكر الملف بـfailed_files.
    400: بيانات/ملفات غير صالحة قبل الإنشاء (لا يُنشأ شيء). 422: payload لا
    يطابق MeetingCreate.
    """
    try:
        data = MeetingCreate.model_validate_json(payload)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors(include_url=False)) from exc

    if len(agenda_file_indexes) != len(agenda_files):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="عدد ملفات البنود لا يطابق أرقام البنود")
    if any(i < 0 or i >= len(data.agenda_items) for i in agenda_file_indexes):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="رقم بند غير صالح لأحد الملفات")

    # قراءة كل الملفات والتحقق من أحجامها قبل إنشاء أي شيء — حتى لا يُنشأ
    # اجتماع ثم يفشل رفع ملفاته لسبب كان معروفًا مسبقًا.
    max_bytes = settings.MAX_DOCUMENT_UPLOAD_MB * 1024 * 1024

    async def read(upload: UploadFile) -> tuple[str, str, bytes]:
        content = await upload.read()
        name = upload.filename or "ملف"
        if not content:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"الملف فارغ: {name}")
        if len(content) > max_bytes:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"حجم الملف «{name}» يتجاوز الحد المسموح ({settings.MAX_DOCUMENT_UPLOAD_MB} ميجابايت)",
            )
        return name, upload.content_type or "application/octet-stream", content

    presentation_file = await read(presentation) if presentation is not None and presentation.filename else None
    general_files = [await read(f) for f in attachments if f.filename]
    agenda_uploads = [(i, await read(f)) for i, f in zip(agenda_file_indexes, agenda_files)]

    try:
        meeting = await meeting_service.create_meeting(
            db,
            actor=current_user,
            committee_id=data.committee_id,
            title=data.title,
            description=data.description,
            mode=data.mode,
            location=data.location,
            scheduled_at=data.scheduled_at,
            scheduled_end_at=data.scheduled_end_at,
            # ترتيب البند = موقعه بالقائمة، حتى نطابق ملف كل بند بمعرّفه بعد الإنشاء.
            agenda_items=[{**item.model_dump(), "sort_order": i} for i, item in enumerate(data.agenda_items)],
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc

    # تُقرأ قبل أي رفع: فشل رفع ملف يعمل rollback يُنهي صلاحية كائنات الجلسة،
    # وقراءة meeting.agenda_items بعدها تحاول تحميلًا كسولًا يفشل بسياق async.
    meeting_id = meeting.meeting_id
    item_ids = {item.sort_order: item.agenda_item_id for item in meeting.agenda_items}
    actor = current_user
    actor_id = current_user.user_id

    async def after_failure() -> None:
        """rollback ثم إعادة تحميل المستخدم الحالي (أُنهيت صلاحية كائنه مع rollback)."""
        nonlocal actor
        await db.rollback()
        actor = await user_service.get_user(db, actor_id)

    email_files: list[notification_service.MeetingEmailFile] = []
    failed: list[str] = []
    meeting_files = [("presentation", presentation_file)] if presentation_file else []
    meeting_files += [("attachment", f) for f in general_files]
    for kind, (name, mime, content) in meeting_files:
        try:
            await meeting_service.add_attachment(
                db,
                actor=actor,
                meeting_id=meeting_id,
                kind=kind,
                title=name,
                file_name=name,
                mime_type=mime,
                content=content,
            )
            email_files.append(notification_service.MeetingEmailFile(filename=name, content=content, mime_type=mime))
        except _SERVICE_ERRORS:
            await after_failure()
            failed.append(name)

    by_item: dict[int, list[tuple[str, str, bytes]]] = {}
    for index, file in agenda_uploads:
        by_item.setdefault(index, []).append(file)
    for index, files in by_item.items():
        try:
            await meeting_service.add_agenda_item_attachments(
                db, actor=actor, meeting_id=meeting_id, agenda_item_id=item_ids[index], files=files
            )
            email_files += [
                notification_service.MeetingEmailFile(
                    filename=name, content=content, mime_type=mime, agenda_item_id=item_ids[index]
                )
                for name, mime, content in files
            ]
        except _SERVICE_ERRORS:
            await after_failure()
            failed += [name for name, _, _ in files]

    meeting = await meeting_service.get_meeting(db, meeting_id, actor=actor)
    run_detached(
        notification_service.notify_meeting_created(meeting, actor_user_id=actor_id, files=email_files)
    )
    return MeetingCreateWithAttachmentsOut(meeting=MeetingOut.model_validate(meeting), failed_files=failed)


@router.get("", response_model=list[MeetingListItem])
async def list_meetings(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[MeetingListItem]:
    """قائمة مختصرة (MeetingListItem) — التفاصيل الكاملة على GET /meetings/{meeting_id}."""
    rows = await meeting_service.list_meetings(db, actor=current_user)
    return [
        MeetingListItem.model_validate(meeting).model_copy(update={"participant_count": count})
        for meeting, count in rows
    ]


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
        run_detached(
            notification_service.notify_meeting_updated(
                meeting, changes, actor_user_id=current_user.user_id
            )
        )
    return MeetingOut.model_validate(meeting)


@router.post("/{meeting_id}/extend", response_model=MeetingOut)
async def extend_meeting(
    meeting_id: uuid.UUID,
    payload: MeetingExtend,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingOut:
    """
    POST /meetings/{id}/extend — تمديد وقت نهاية الاجتماع قبله أو أثناءه
    (طلب لاما 2026-11-01). نفس صلاحية التعديل (meetings.update) ونطاقها.

    200: الاجتماع بعد التمديد. 400: وقت غير صالح (ليس بعد النهاية الحالية،
    في الماضي، أو خارج فترة عمل اللجنة). 403: بلا صلاحية. 404: غير موجود.
    409: الاجتماع انتهى.
    التأثير الجانبي: إشعار المشاركين بتغيّر موعد النهاية — نفس إشعار التعديل
    (notify_meeting_updated) عبر run_detached.
    """
    try:
        meeting, changes = await meeting_service.extend_meeting(
            db, actor=current_user, meeting_id=meeting_id, new_end_at=payload.new_end_at
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    run_detached(
        notification_service.notify_meeting_updated(meeting, changes, actor_user_id=current_user.user_id)
    )
    return MeetingOut.model_validate(meeting)


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(
    meeting_id: uuid.UUID,
    current_user: CurrentUser,
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
    # صالحة بلا استعلام إضافي (راجعي notification_service.py). run_detached
    # بدل background_tasks.add_task (تحقيق أداء لاما 2026-09-15 — راجعي
    # core/background.py): لا يُبقي جلسة db لهذا الطلب محجوزة أثناء SMTP.
    run_detached(
        notification_service.notify_meeting_cancelled(meeting, actor_user_id=current_user.user_id)
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
