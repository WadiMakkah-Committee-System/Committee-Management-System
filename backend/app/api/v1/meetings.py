"""
الهدف:
راوتات REST لوحدة "إدارة الاجتماعات" (Phase 2). بدون أي تكامل مع
Microsoft Teams/Graph API وبدون خدمات الذكاء الاصطناعي — راجعي رأس
db/migrations/0018_meetings_schema.sql وapp/services/meeting_service.py
لتفصيل القرار الموثّق.

ملاحظة مهمة (لماذا لا تستخدم راوتات الإنشاء/التعديل/الحذف require_permission
على مستوى الراوت، بخلاف committees.py): التفويض هنا يعتمد على اللجنة
المحدَّدة بالطلب تحديدًا (Committee Role الخاص بعضوية actor في *تلك*
اللجنة بالذات) وليس فقط على دوره العام — فلا يمكن فحصه بمعزل عن تحميل
السجل نفسه أولًا. يُفرض بالكامل داخل meeting_service (دالة _require_access
هناك)، بنفس منطق الوصول المزدوج (System Role scope أو Committee Role
permission) المطبَّق في committee_service.get_committee — راجعي docstring
meeting_service.py للتفصيل الكامل بعد تحديث 2026-09-01 ("أدوار اللجان").
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.meeting import (
    MeetingAgendaItemCreate,
    MeetingAgendaItemOut,
    MeetingAgendaItemUpdate,
    MeetingCreate,
    MeetingOut,
    MeetingUpdate,
)
from app.services import meeting_service
from app.services.meeting_service import (
    AgendaItemNotFoundError,
    MeetingForbiddenError,
    MeetingInvalidStateError,
    MeetingNotFoundError,
)

router = APIRouter(prefix="/meetings", tags=["meetings"])


def _handle_errors(exc: Exception) -> Exception:
    """يترجم استثناءات طبقة الخدمة إلى استجابات HTTP مناسبة، مركزيًا (بنفس نمط committees.py)."""
    if isinstance(exc, (MeetingNotFoundError, AgendaItemNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, MeetingForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, MeetingInvalidStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


@router.post("", response_model=MeetingOut, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingOut:
    try:
        meeting = await meeting_service.create_meeting(
            db,
            actor=current_user,
            committee_id=payload.committee_id,
            title=payload.title,
            description=payload.description,
            meeting_type=payload.meeting_type,
            scheduled_at=payload.scheduled_at,
            participant_ids=payload.participant_ids,
            agenda_items=[item.model_dump() for item in payload.agenda_items],
        )
        await db.commit()
    except (MeetingNotFoundError, MeetingForbiddenError, ValueError) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc
    await db.refresh(meeting)
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
    except (MeetingNotFoundError, MeetingForbiddenError) as exc:
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
        meeting = await meeting_service.update_meeting(
            db,
            actor=current_user,
            meeting_id=meeting_id,
            title=payload.title,
            description=payload.description,
            meeting_type=payload.meeting_type,
            scheduled_at=payload.scheduled_at,
            participant_ids=payload.participant_ids,
        )
        await db.commit()
    except (
        MeetingNotFoundError,
        MeetingForbiddenError,
        MeetingInvalidStateError,
        ValueError,
    ) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc
    await db.refresh(meeting)
    return MeetingOut.model_validate(meeting)


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    try:
        await meeting_service.delete_meeting(db, actor=current_user, meeting_id=meeting_id)
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
        await db.commit()
    except (MeetingNotFoundError, MeetingForbiddenError) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc
    await db.refresh(item)
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
        await db.commit()
    except (AgendaItemNotFoundError, MeetingNotFoundError, MeetingForbiddenError) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc
    await db.refresh(item)
    return MeetingAgendaItemOut.model_validate(item)


@router.delete("/agenda-items/{agenda_item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agenda_item(
    agenda_item_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    try:
        await meeting_service.delete_agenda_item(
            db, actor=current_user, agenda_item_id=agenda_item_id
        )
        await db.commit()
    except (AgendaItemNotFoundError, MeetingNotFoundError, MeetingForbiddenError) as exc:
        await db.rollback()
        raise _handle_errors(exc) from exc
