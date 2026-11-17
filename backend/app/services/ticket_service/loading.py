"""
الهدف:
تحميل التذاكر والرسائل مع أسماء المستخدمين فقط، وبناء مخرجات الـAPI حسب
صفة المشاهد (مقدّم طلب أو دعم).

المسؤولية:
- تحميل User بأعمدة الاسم والبريد فقط، مع raiseload("*") — بدون أدوار
  وصلاحيات وإدارة كل مستخدم (العلاقات الافتراضية بنموذج User تحمّلها).
- populate_existing عند إعادة التحميل بعد التعديل، عشان العلاقات (مثل
  المسند إليه الجديد) ما تبقى قديمة بذاكرة الجلسة.
- إخفاء الحقول الخاصة بالدعم عن مقدّم الطلب (الأولوية، البريد، حالة المسند).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, raiseload, selectinload

from app.models.ticket import Ticket, TicketAttachment, TicketMessage
from app.models.user import User
from app.schemas.ticket import (
    TicketAttachmentOut,
    TicketMessageOut,
    TicketOut,
    TicketPersonOut,
    TicketViewerActionsOut,
)
from app.services.ticket_service.access import Viewer, eligible_support_user_ids_query, viewer_actions
from app.services.ticket_service.errors import TicketNotFoundError

_PERSON_COLUMNS = (User.user_id, User.first_name, User.last_name, User.email)


def person_loader(relationship_attr):
    """
    الهدف: خيار تحميل لعلاقة مستخدم (مقدّم الطلب/المسند إليه/الكاتب) بأعمدة
    الاسم والبريد فقط، ومنع تحميل أي علاقة أخرى للمستخدم.
    المدخلات: العلاقة (مثال: Ticket.requester). المخرجات: خيار تحميل SQLAlchemy.
    """
    return selectinload(relationship_attr).options(load_only(*_PERSON_COLUMNS), raiseload("*"))


TICKET_OPTIONS = (person_loader(Ticket.requester), person_loader(Ticket.assignee))
MESSAGE_OPTIONS = (person_loader(TicketMessage.author), selectinload(TicketMessage.attachments))


async def load_ticket(db: AsyncSession, ticket_id: uuid.UUID, *, for_update: bool = False) -> Ticket:
    """
    الهدف: تحميل تذكرة واحدة مع اسم مقدّم الطلب والمسند إليه.

    المدخلات:
    - ticket_id: معرّف التذكرة.
    - for_update: قفل صف التذكرة لين نهاية المعاملة (للعمليات اللي تغيّر
      الحالة أو الإسناد — يمنع تعارض عمليتين بنفس اللحظة).

    المخرجات: Ticket محدَّث من القاعدة (populate_existing).
    الأخطاء: TicketNotFoundError لو غير موجودة.
    """
    stmt = (
        select(Ticket)
        .where(Ticket.ticket_id == ticket_id)
        .options(*TICKET_OPTIONS)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update(of=Ticket)
    ticket = (await db.execute(stmt)).scalar_one_or_none()
    if ticket is None:
        raise TicketNotFoundError("التذكرة غير موجودة")
    return ticket


async def load_message(db: AsyncSession, message_id: uuid.UUID) -> TicketMessage:
    """
    الهدف: تحميل رسالة واحدة مع اسم كاتبها ومرفقاتها (بعد الحفظ أو عند التكرار).
    الأخطاء: TicketNotFoundError لو غير موجودة.
    """
    stmt = (
        select(TicketMessage)
        .where(TicketMessage.message_id == message_id)
        .options(*MESSAGE_OPTIONS)
        .execution_options(populate_existing=True)
    )
    message = (await db.execute(stmt)).scalar_one_or_none()
    if message is None:
        raise TicketNotFoundError("الرسالة غير موجودة")
    return message


async def eligible_support_ids(db: AsyncSession) -> set[uuid.UUID]:
    """
    الهدف: معرّفات أعضاء الدعم المؤهلين حاليًا (استعلام واحد).
    يُستخدم لمعرفة هل المسند إليه ما زال عضو دعم، ولتبويب "غير مسندة".
    """
    return set((await db.scalars(eligible_support_user_ids_query())).all())


def _person(user: User | None, *, include_email: bool) -> TicketPersonOut | None:
    """الهدف: اسم المستخدم المختصر — البريد للدعم فقط."""
    if user is None:
        return None
    return TicketPersonOut(
        user_id=user.user_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email if include_email else None,
    )


def ticket_out(
    ticket: Ticket, *, actor: User, viewer: Viewer, support_ids: set[uuid.UUID] | None = None
) -> TicketOut:
    """
    الهدف: بناء مخرجات التذكرة حسب صفة المشاهد.

    المدخلات:
    - ticket: محمَّلة بـTICKET_OPTIONS.
    - actor: المستخدم الحالي (لحساب الأزرار المتاحة).
    - viewer: "requester" أو "support".
    - support_ids: أعضاء الدعم المؤهلين (للدعم فقط — لحساب assignee_is_active_support).

    المخرجات: TicketOut. مقدّم الطلب ما يشوف الأولوية ولا البريد ولا حالة المسند.
    """
    support = viewer == "support"
    assignee_active = None
    if support:
        assignee_active = (
            ticket.assignee_id is not None and support_ids is not None and ticket.assignee_id in support_ids
        )
    return TicketOut(
        ticket_id=ticket.ticket_id,
        ticket_number=ticket.ticket_number,
        title=ticket.title,
        ticket_type=ticket.ticket_type,
        module=ticket.module,
        status=ticket.status,
        priority=ticket.priority if support else None,
        requester=_person(ticket.requester, include_email=support),
        assignee=_person(ticket.assignee, include_email=support),
        assignee_is_active_support=assignee_active,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at if support else ticket.last_public_activity_at,
        last_public_activity_at=ticket.last_public_activity_at,
        resolved_at=ticket.resolved_at,
        closed_at=ticket.closed_at,
        cancelled_at=ticket.cancelled_at,
        viewer=viewer,
        actions=TicketViewerActionsOut(**viewer_actions(actor, ticket, viewer)),
    )


def message_out(message: TicketMessage, *, viewer: Viewer) -> TicketMessageOut:
    """
    الهدف: بناء مخرجات رسالة (محمَّلة بـMESSAGE_OPTIONS).
    الأمان: المستدعي مسؤول عن عدم تمرير ملاحظة داخلية لمقدّم الطلب — هذه
    الدالة ترفضها كطبقة حماية ثانية.
    الأخطاء: TicketNotFoundError لو رسالة داخلية لمشاهد غير الدعم.
    """
    if message.is_internal and viewer != "support":
        raise TicketNotFoundError("الرسالة غير موجودة")
    return TicketMessageOut(
        message_id=message.message_id,
        ticket_id=message.ticket_id,
        author=_person(message.author, include_email=viewer == "support"),
        author_side=message.author_side,
        is_internal=message.is_internal,
        is_description=message.is_description,
        body_json=message.body_json,
        client_message_id=message.client_message_id,
        created_at=message.created_at,
        attachments=[TicketAttachmentOut.model_validate(a) for a in message.attachments],
    )


__all__ = [
    "MESSAGE_OPTIONS",
    "TICKET_OPTIONS",
    "TicketAttachment",
    "eligible_support_ids",
    "load_message",
    "load_ticket",
    "message_out",
    "person_loader",
    "ticket_out",
]
