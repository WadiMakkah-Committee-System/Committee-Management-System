"""
الهدف:
إنشاء التذاكر وعرضها: الإرسال، "تذاكري"، قائمة الدعم بتبويباتها، التفاصيل،
سجل التذكرة، وقائمة أعضاء الدعم للإسناد (TKT-FR-001/002/010/017/020).

قواعد العمل:
- الإنشاء لمن يملك tickets.create: التذكرة + وصفها (أول رسالة) + مرفقاته
  بمعاملة واحدة (القاعدة ترفض تذكرة بدون وصف عند COMMIT).
- "تذاكري": تذاكر المستخدم نفسه فقط — المعرّف من التوكن، لا من الطلب.
- قائمة الدعم: غير مسندة / المسندة لي / الكل، مع الفلاتر والبحث.
  "غير مسندة" تشمل المسندة لشخص ما عاد عضو دعم (القسم 10 بالمواصفات).
"""

import re
import uuid
from typing import Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.ticket import Ticket, TicketAuthorSide, TicketMessage, TicketStatus
from app.models.user import User
from app.schemas.ticket import TicketHistoryEntryOut, TicketPersonOut, TicketSupportMemberOut
from app.services.ticket_service.access import (
    Viewer,
    eligible_support_user_ids_query,
    require_requester,
    require_support,
    resolve_viewer,
)
from app.services.ticket_service.codes import TICKETS_ASSIGN
from app.services.ticket_service.content import (
    IncomingFile,
    parse_body,
    validate_body,
    validate_files,
    validate_title,
)
from app.services.ticket_service.errors import TicketInvalidStateError
from app.services.ticket_service.loading import TICKET_OPTIONS, load_message, load_ticket
from app.services.ticket_service.messages import find_by_client_id, insert_message, remove_uploaded
from app.services.ticket_service.workflow import audit

SupportTab = Literal["unassigned", "mine", "all"]

_OPEN_FILTER = Ticket.status.notin_([TicketStatus.closed.value, TicketStatus.cancelled.value])
_TICKET_NUMBER_RE = re.compile(r"^TKT-\d{4}-\d+$", re.IGNORECASE)

#: أحداث سجل التذكرة المعروضة للدعم (TKT-FR-017) — الرسائل نفسها خارجه.
_HISTORY_EVENTS = frozenset(
    {"created", "status_changed", "assigned", "priority_changed", "type_changed", "module_changed"}
)


async def create_ticket(
    db: AsyncSession,
    *,
    actor: User,
    title: str,
    ticket_type: str,
    module: str,
    body_raw: str | None,
    client_message_id: uuid.UUID | None,
    files: list[IncomingFile],
) -> tuple[Ticket, bool]:
    """
    الهدف: إرسال تذكرة جديدة (TKT-FR-001).

    المدخلات:
    - title: 5 إلى 150 حرف. ticket_type/module: من القوائم الثابتة (يتحقق منها الراوت).
    - body_raw: الوصف كـJSON بصيغة TipTap (10 إلى 5000 حرف).
    - client_message_id: لو أعاد المتصفح الإرسال بنفس المعرّف، ترجع التذكرة
      المحفوظة بدل تذكرة مكررة.
    - files: مرفقات الوصف (5 كحد أقصى).

    المخرجات: (التذكرة محمَّلة بالأسماء، created) — created=False لإعادة محاولة.

    التأثيرات الجانبية: INSERT تذكرة + رسالة + مرفقات، رفع الملفات، تدقيق، commit.
    الصلاحيات: tickets.create. الأخطاء: 400 / 403 / 409 / 503.
    """
    require_requester(actor)
    clean_title = validate_title(title)

    existing = await find_by_client_id(db, author_id=actor.user_id, client_message_id=client_message_id)
    if existing is not None:
        if not existing.is_description:
            raise TicketInvalidStateError("معرّف الرسالة مستخدم لرسالة أخرى")
        return await load_ticket(db, existing.ticket_id), False

    validated_files = validate_files(files)
    doc, text = validate_body(parse_body(body_raw), is_description=True, has_attachments=bool(validated_files))

    # نفس نمط post_message: الكتابة داخل savepoint عشان تعارض إعادة المحاولة
    # المتزامنة ما يُبطل الجلسة كاملة (والمستخدم الحالي معها).
    uploaded: list[str] = []
    try:
        async with db.begin_nested():
            ticket = Ticket(requester_id=actor.user_id, title=clean_title, ticket_type=ticket_type, module=module)
            db.add(ticket)
            await db.flush()
            await audit(
                db,
                actor_id=actor.user_id,
                ticket_id=ticket.ticket_id,
                event="created",
                action="create",
                ticket_number=ticket.ticket_number,
            )
            _, uploaded = await insert_message(
                db,
                ticket_id=ticket.ticket_id,
                author=actor,
                side=TicketAuthorSide.requester.value,
                is_internal=False,
                is_description=True,
                body=doc,
                text=text,
                client_message_id=client_message_id,
                files=validated_files,
            )
    except IntegrityError as exc:
        await remove_uploaded(uploaded)
        duplicate = await find_by_client_id(db, author_id=actor.user_id, client_message_id=client_message_id)
        if duplicate is not None and duplicate.is_description:
            await db.commit()
            return await load_ticket(db, duplicate.ticket_id), False
        raise TicketInvalidStateError("تعذّر حفظ التذكرة — حاول مرة ثانية") from exc
    except Exception:
        await remove_uploaded(uploaded)
        raise

    try:
        await db.commit()
    except IntegrityError as exc:
        await remove_uploaded(uploaded)
        raise TicketInvalidStateError("تعذّر حفظ التذكرة — حاول مرة ثانية") from exc
    return await load_ticket(db, ticket.ticket_id), True


async def get_ticket(db: AsyncSession, *, actor: User, ticket_id: uuid.UUID) -> tuple[Ticket, Viewer]:
    """
    الهدف: تفاصيل تذكرة واحدة مع صفة المشاهد.
    الأخطاء: 404 لمن ما له علاقة، و403 لصاحبها بدون tickets.create.
    """
    ticket = await load_ticket(db, ticket_id)
    return ticket, resolve_viewer(actor, ticket)


async def get_description(db: AsyncSession, *, ticket_id: uuid.UUID) -> TicketMessage:
    """الهدف: رسالة الوصف لتذكرة (لإرجاعها مع نتيجة الإنشاء). المخرجات: TicketMessage."""
    message_id = await db.scalar(
        select(TicketMessage.message_id).where(TicketMessage.ticket_id == ticket_id, TicketMessage.is_description)
    )
    return await load_message(db, message_id)


async def _page(
    db: AsyncSession, stmt: Select, *, order_by: tuple, limit: int, offset: int
) -> tuple[list[Ticket], int]:
    """
    الهدف: تنفيذ استعلام قائمة مع العدد الكلي (نفس نمط صفحات audit_logs).
    المخرجات: (التذاكر محمَّلة بالأسماء، العدد الكلي).
    """
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = await db.execute(stmt.options(*TICKET_OPTIONS).order_by(*order_by).limit(limit).offset(offset))
    return list(rows.scalars().all()), int(total or 0)


def _apply_filters(
    stmt: Select,
    *,
    statuses: list[str] | None,
    ticket_type: str | None,
    module: str | None,
    priority: str | None,
) -> Select:
    """الهدف: فلاتر القائمة المشتركة (الحالة/النوع/الوحدة/الأولوية)."""
    if statuses:
        stmt = stmt.where(Ticket.status.in_(statuses))
    if ticket_type:
        stmt = stmt.where(Ticket.ticket_type == ticket_type)
    if module:
        stmt = stmt.where(Ticket.module == module)
    if priority:
        stmt = stmt.where(Ticket.priority == priority)
    return stmt


def _escape_like(value: str) -> str:
    """الهدف: تعطيل محارف LIKE الخاصة (% و_ و\\) داخل نص البحث."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_my_tickets(
    db: AsyncSession, *, actor: User, statuses: list[str] | None, limit: int, offset: int
) -> tuple[list[Ticket], int]:
    """
    الهدف: "تذاكري" لمقدّم الطلب (TKT-FR-002) — بترتيب آخر تحديث.
    الصلاحيات: tickets.create. الأخطاء: 403.
    """
    require_requester(actor)
    stmt = _apply_filters(
        select(Ticket).where(Ticket.requester_id == actor.user_id),
        statuses=statuses,
        ticket_type=None,
        module=None,
        priority=None,
    )
    return await _page(
        db, stmt, order_by=(Ticket.last_public_activity_at.desc(), Ticket.ticket_id), limit=limit, offset=offset
    )


async def list_support_tickets(
    db: AsyncSession,
    *,
    actor: User,
    tab: SupportTab,
    statuses: list[str] | None,
    ticket_type: str | None,
    module: str | None,
    priority: str | None,
    query: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Ticket], int]:
    """
    الهدف: قائمة الدعم بتبويباتها (TKT-FR-010).

    قواعد العمل:
    - unassigned: المفتوحة بدون مسند إليه، أو مسندة لشخص ما عاد عضو دعم — الأقدم أولًا.
    - mine: المسندة لي (المفتوحة ما لم يُحدَّد فلتر حالة) — آخر تحديث أولًا.
    - all: الكل — آخر تحديث أولًا.
    - البحث: برقم التذكرة (TKT-2026-0042 أو جزء رقمي منه) أو بالعنوان.

    الصلاحيات: tickets.view_all بنطاق all. الأخطاء: 403.
    """
    require_support(actor)
    stmt = _apply_filters(
        select(Ticket), statuses=statuses, ticket_type=ticket_type, module=module, priority=priority
    )
    if tab == "unassigned":
        if not statuses:
            stmt = stmt.where(_OPEN_FILTER)
        stmt = stmt.where(
            or_(Ticket.assignee_id.is_(None), Ticket.assignee_id.notin_(eligible_support_user_ids_query()))
        )
        order_by = (Ticket.created_at.asc(), Ticket.ticket_id)
    elif tab == "mine":
        if not statuses:
            stmt = stmt.where(_OPEN_FILTER)
        stmt = stmt.where(Ticket.assignee_id == actor.user_id)
        order_by = (Ticket.updated_at.desc(), Ticket.ticket_id)
    else:
        order_by = (Ticket.updated_at.desc(), Ticket.ticket_id)

    text = (query or "").strip()
    if text:
        if _TICKET_NUMBER_RE.match(text):
            stmt = stmt.where(Ticket.ticket_number == text.upper())
        elif text.isdigit():
            stmt = stmt.where(Ticket.ticket_number.like(f"%{_escape_like(text)}", escape="\\"))
        else:
            stmt = stmt.where(Ticket.title.ilike(f"%{_escape_like(text)}%", escape="\\"))
    return await _page(db, stmt, order_by=order_by, limit=limit, offset=offset)


async def list_support_members(db: AsyncSession, *, actor: User) -> list[TicketSupportMemberOut]:
    """
    الهدف: أعضاء الدعم اللي يقدر يُسند لهم (قائمة إعادة الإسناد).
    الصلاحيات: tickets.assign. الأخطاء: 403.
    """
    require_support(actor, TICKETS_ASSIGN)
    stmt = (
        select(User.user_id, User.first_name, User.last_name, User.email)
        .where(User.user_id.in_(eligible_support_user_ids_query()))
        .order_by(User.first_name, User.last_name)
    )
    rows = (await db.execute(stmt)).all()
    return [
        TicketSupportMemberOut(user_id=r.user_id, first_name=r.first_name, last_name=r.last_name, email=r.email)
        for r in rows
    ]


async def get_history(db: AsyncSession, *, actor: User, ticket_id: uuid.UUID) -> list[TicketHistoryEntryOut]:
    """
    الهدف: سجل التذكرة للدعم (TKT-FR-017) — من audit_logs (target_type = 'ticket').

    المخرجات: الأحداث بالترتيب الزمني، مع اسم الفاعل (None للعمليات التلقائية).
    الصلاحيات: tickets.view_all. الأخطاء: 403 / 404.
    """
    require_support(actor)
    await load_ticket(db, ticket_id)
    stmt = (
        select(AuditLog, User.user_id, User.first_name, User.last_name, User.email)
        .outerjoin(User, User.user_id == AuditLog.actor_user_id)
        .where(AuditLog.target_type == "ticket", AuditLog.target_id == ticket_id)
        .order_by(AuditLog.created_at.asc(), AuditLog.log_id)
    )
    entries: list[TicketHistoryEntryOut] = []
    for log, user_id, first_name, last_name, email in (await db.execute(stmt)).all():
        data = log.metadata_ or {}
        event = data.get("event")
        if event not in _HISTORY_EVENTS:
            continue
        actor_out = (
            TicketPersonOut(user_id=user_id, first_name=first_name, last_name=last_name, email=email)
            if user_id is not None
            else None
        )
        from_value = data.get("from")
        to_value = data.get("to")
        entries.append(
            TicketHistoryEntryOut(
                event=event,
                from_value=str(from_value) if from_value is not None else None,
                to_value=str(to_value) if to_value is not None else None,
                actor=actor_out,
                created_at=log.created_at,
            )
        )
    return entries
