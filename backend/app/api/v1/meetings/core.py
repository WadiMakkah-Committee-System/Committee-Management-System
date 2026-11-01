"""إنشاء/عرض/قائمة/تعديل/حذف الاجتماعات + الانضمام/المغادرة + جدول الأعمال."""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import agora_client
from app.core.background import run_detached
from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.meeting import (
    MeetingAgendaItemCreate,
    MeetingAgendaItemOut,
    MeetingAgendaItemUpdate,
    MeetingCreate,
    MeetingExtend,
    MeetingJoinOut,
    MeetingListItem,
    MeetingOut,
    MeetingUpdate,
)
from app.services import meeting_service, notification_service
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
