"""
جدول أعمال الاجتماع (FR-MEET §3.1.3) — إضافة/تعديل/حذف البنود.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting import MeetingAgendaItem
from app.models.user import User
from app.services.meeting_service.access import _require_access
from app.services.meeting_service.errors import AgendaItemNotFoundError
from app.services.meeting_service.loading import load_meeting


# ============================== جدول الأعمال ==============================


async def add_agenda_item(
    db: AsyncSession,
    *,
    actor: User,
    meeting_id: uuid.UUID,
    title: str,
    description: str | None,
    sort_order: int,
) -> MeetingAgendaItem:
    """FR-MEET §3.1.3: إضافة بند لجدول الأعمال — يتطلب meetings.agenda.item.add."""
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_access(
        db,
        actor,
        committee,
        "meetings.agenda.item.add",
        "ليست لديك صلاحية إضافة بند لجدول أعمال هذا الاجتماع",
    )

    item = MeetingAgendaItem(
        meeting_id=meeting_id, title=title, description=description, sort_order=sort_order
    )
    db.add(item)
    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    await db.refresh(item)
    await db.commit()
    return item


async def _load_agenda_item(db: AsyncSession, agenda_item_id: uuid.UUID) -> MeetingAgendaItem:
    result = await db.execute(
        select(MeetingAgendaItem).where(MeetingAgendaItem.agenda_item_id == agenda_item_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise AgendaItemNotFoundError("بند جدول الأعمال غير موجود")
    return item


async def update_agenda_item(
    db: AsyncSession,
    *,
    actor: User,
    agenda_item_id: uuid.UUID,
    title: str | None,
    description: str | None,
    sort_order: int | None,
) -> MeetingAgendaItem:
    item = await _load_agenda_item(db, agenda_item_id)
    meeting = await load_meeting(db, item.meeting_id)
    committee = meeting.committee
    await _require_access(
        db,
        actor,
        committee,
        "meetings.agenda.item.update",
        "ليست لديك صلاحية تعديل هذا البند",
    )

    if title is not None:
        item.title = title
    if description is not None:
        item.description = description
    if sort_order is not None:
        item.sort_order = sort_order
    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    await db.refresh(item)
    await db.commit()
    return item


async def delete_agenda_item(db: AsyncSession, *, actor: User, agenda_item_id: uuid.UUID) -> None:
    item = await _load_agenda_item(db, agenda_item_id)
    meeting = await load_meeting(db, item.meeting_id)
    committee = meeting.committee
    await _require_access(
        db,
        actor,
        committee,
        "meetings.agenda.item.delete",
        "ليست لديك صلاحية حذف هذا البند",
    )

    await db.delete(item)
    await db.commit()

