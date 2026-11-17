"""
الهدف:
سير عمل التذكرة: الحالات، الاستلام والإسناد، تعديل الحقول، الإلغاء،
والإغلاق التلقائي — مع تسجيل كل تغيير في audit_logs (TKT-FR-023).

قواعد العمل (القسم 4 بالمواصفات):
- الانتقالات المسموحة يفرضها trigger بالقاعدة أيضًا؛ هنا نتحقق قبلها عشان
  الرسالة تكون واضحة، ونعمل flush بعد كل خطوة لأن الـtrigger يقارن الحالة
  القديمة بالجديدة لكل UPDATE.
- الاستلام ينقل "جديدة" إلى "قيد المعالجة" بنفس الخطوة.
- الإلغاء لصاحب التذكرة فقط وهي "جديدة".
- الإغلاق التلقائي بعد 4 أيام من "تم الحل" (المجدول).

الاعتماديات: audit_service، وloading (التحميل مع القفل)، وaccess (الصلاحيات).
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticket import FINAL_STATUSES, Ticket, TicketStatus
from app.models.user import User
from app.services import audit_service
from app.services.ticket_service.access import (
    has_support_permission,
    require_requester,
    require_support,
)
from app.services.ticket_service.codes import TICKETS_ASSIGN, TICKETS_MANAGE
from app.services.ticket_service.errors import (
    TicketInvalidStateError,
    TicketNotFoundError,
    TicketValidationError,
)
from app.services.ticket_service.loading import eligible_support_ids, load_ticket

#: مدة "تم الحل" قبل الإغلاق التلقائي (قرار 2026-11-17).
AUTO_CLOSE_AFTER = timedelta(days=4)

_NEW = TicketStatus.new.value
_IN_PROGRESS = TicketStatus.in_progress.value
_WAITING = TicketStatus.waiting_on_requester.value
_RESOLVED = TicketStatus.resolved.value
_CLOSED = TicketStatus.closed.value
_CANCELLED = TicketStatus.cancelled.value

#: مسار الوصول لحالة يختارها الدعم مع الرد — بعض الأهداف تحتاج خطوة وسيطة
#: (مثال: جديدة ← قيد المعالجة ← بانتظار رد المستخدم)، لأن الـtrigger يسمح
#: فقط بالانتقالات المباشرة الموجودة بجدول المواصفات.
_REPLY_PATHS: dict[tuple[str, str], list[str]] = {
    (_NEW, _IN_PROGRESS): [_IN_PROGRESS],
    (_NEW, _WAITING): [_IN_PROGRESS, _WAITING],
    (_NEW, _RESOLVED): [_RESOLVED],
    (_IN_PROGRESS, _WAITING): [_WAITING],
    (_IN_PROGRESS, _RESOLVED): [_RESOLVED],
    (_WAITING, _IN_PROGRESS): [_IN_PROGRESS],
    (_WAITING, _RESOLVED): [_RESOLVED],
}
# ملاحظة: لا مسار من "تم الحل" هنا عمدًا — إعادة الفتح برد مقدّم الطلب فقط
# (القسم 4 بالمواصفات). رد الدعم على تذكرة محلولة يبقيها "تم الحل".

#: التغيير اليدوي من زر الحالة (tickets.manage) — أضيق من مسارات الرد:
#: "جديدة" تتحرك بالاستلام، و"تم الحل" ترجع برد مقدّم الطلب فقط.
_MANUAL_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        (_WAITING, _IN_PROGRESS),
        (_IN_PROGRESS, _WAITING),
        (_NEW, _RESOLVED),
        (_IN_PROGRESS, _RESOLVED),
        (_WAITING, _RESOLVED),
    }
)

_STALE_MESSAGE = "تغيّرت التذكرة من مكان ثاني — حدّث الصفحة وحاول مرة ثانية"


@dataclass
class StatusChange:
    """الهدف: خطوة تغيير حالة واحدة (للتدقيق والإشعارات)."""

    from_status: str
    to_status: str


@dataclass
class WorkflowResult:
    """
    الهدف: نتيجة عملية على التذكرة يحتاجها الراوت للإشعارات والبث اللحظي.

    الحقول:
    - ticket: التذكرة بعد الحفظ (محمَّلة بالأسماء).
    - status_changes: خطوات الحالة اللي صارت (بالترتيب).
    - assigned_to: عضو الدعم الجديد لو تغيّر الإسناد.
    """

    ticket: Ticket
    status_changes: list[StatusChange] = field(default_factory=list)
    assigned_to: uuid.UUID | None = None


def now_utc() -> datetime:
    """الهدف: الوقت الحالي بتوقيت UTC (نقطة واحدة تسهّل الاختبار)."""
    return datetime.now(UTC)


async def audit(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    ticket_id: uuid.UUID,
    event: str,
    action: str = "update",
    **data: object,
) -> None:
    """
    الهدف: تسجيل حدث تذكرة في audit_logs (target_type = 'ticket').

    المدخلات:
    - actor_id: الفاعل، أو None للعمليات التلقائية (المجدول).
    - event: نوع الحدث (created، status_changed، assigned، ...) — يُقرأ منه سجل التذكرة.
    - action: نوع عملية التدقيق (create أو update).
    - data: تفاصيل إضافية (from/to/message_id...).

    التأثيرات الجانبية: يضيف صفًا لجلسة القاعدة (بدون commit — نفس المعاملة).
    """
    await audit_service.log_action(
        db,
        actor_user_id=actor_id,
        action_type=action,
        target_type="ticket",
        target_id=ticket_id,
        metadata={"event": event, **data},
    )


async def flush_or_conflict(db: AsyncSession) -> None:
    """
    الهدف: تنفيذ التغييرات المعلّقة وتحويل رفض القاعدة لخطأ 409 واضح.

    سبب الحاجة: الـtriggers والقيود بالقاعدة طبقة حماية أخيرة؛ لو رفضت
    شيئًا هنا فالسبب غالبًا تعارض متزامن (عمليتين بنفس اللحظة)، فنطلب
    تحديث الصفحة بدل عرض نص الخطأ الداخلي.

    ملاحظة: بدون rollback هنا عمدًا — rollback الكامل يُبطل (expire) كل
    كائنات الجلسة ومنها المستخدم الحالي وصلاحياته. المستدعي إما داخل
    savepoint (begin_nested) يُلغى تلقائيًا، أو يرفع الخطأ للراوت فتُغلق
    الجلسة كاملة.

    الأخطاء: TicketInvalidStateError.
    """
    try:
        await db.flush()
    except IntegrityError as exc:
        raise TicketInvalidStateError(_STALE_MESSAGE) from exc


async def set_status(db: AsyncSession, ticket: Ticket, target: str, *, actor_id: uuid.UUID | None) -> StatusChange:
    """
    الهدف: تنفيذ خطوة حالة واحدة مباشرة مع تواريخها وتسجيلها.

    قواعد العمل:
    - تم الحل ← resolved_at الآن. الخروج من "تم الحل" (إعادة فتح) ← resolved_at فارغ.
    - مغلقة ← closed_at الآن. ملغاة ← cancelled_at الآن.

    التأثيرات الجانبية: UPDATE على التذكرة (flush) + صف تدقيق.
    الأخطاء: TicketInvalidStateError لو رفضها الـtrigger (تعارض).
    """
    previous = ticket.status
    ticket.status = target
    now = now_utc()
    if target == _RESOLVED:
        ticket.resolved_at = now
    elif previous == _RESOLVED and target == _IN_PROGRESS:
        ticket.resolved_at = None
    if target == _CLOSED:
        ticket.closed_at = now
    if target == _CANCELLED:
        ticket.cancelled_at = now
    await flush_or_conflict(db)
    await audit(db, actor_id=actor_id, ticket_id=ticket.ticket_id, event="status_changed", **{"from": previous, "to": target})
    return StatusChange(from_status=previous, to_status=target)


async def move_for_reply(
    db: AsyncSession, ticket: Ticket, target: str, *, actor_id: uuid.UUID
) -> list[StatusChange]:
    """
    الهدف: نقل التذكرة للحالة اللي اختارها الدعم مع الرد (TKT-FR-013)، عبر
    خطوة وسيطة إن لزم.

    المدخلات: التذكرة (مقفولة)، والحالة المطلوبة (in_progress/waiting/resolved).
    المخرجات: خطوات الحالة المنفذة (فاضية لو نفس الحالة).
    الأخطاء: TicketInvalidStateError لو ما فيه مسار مسموح.
    """
    if ticket.status == target:
        return []
    path = _REPLY_PATHS.get((ticket.status, target))
    if path is None:
        raise TicketInvalidStateError("لا يمكن نقل التذكرة لهذه الحالة الآن")
    return [await set_status(db, ticket, step, actor_id=actor_id) for step in path]


def ensure_open(ticket: Ticket) -> None:
    """
    الهدف: إيقاف أي تعديل على تذكرة مغلقة أو ملغاة (للقراءة فقط).
    الأخطاء: TicketInvalidStateError (409).
    """
    if TicketStatus(ticket.status) in FINAL_STATUSES:
        raise TicketInvalidStateError("التذكرة مغلقة أو ملغاة ولا يمكن تعديلها")


def _display_name(user: User | None) -> str | None:
    """الهدف: الاسم المحفوظ بسجل التذكرة (يبقى حتى لو تغيّر لاحقًا)."""
    return f"{user.first_name} {user.last_name}" if user is not None else None


async def _assign(
    db: AsyncSession, ticket: Ticket, assignee: User, *, actor_id: uuid.UUID
) -> list[StatusChange]:
    """
    الهدف: إسناد التذكرة لعضو دعم (مشترك بين الاستلام وإعادة الإسناد والرد الأول).

    قواعد العمل: "جديدة" تصير "قيد المعالجة" بنفس الخطوة (القاعدة تمنع
    "جديدة" مع مسند إليه).
    التأثيرات الجانبية: UPDATE + صف تدقيق (assigned) + صف حالة لو تغيرت.
    """
    previous_name = _display_name(ticket.assignee)
    previous_id = ticket.assignee_id
    changes: list[StatusChange] = []
    ticket.assignee_id = assignee.user_id
    if ticket.status == _NEW:
        changes.append(await set_status(db, ticket, _IN_PROGRESS, actor_id=actor_id))
    else:
        await flush_or_conflict(db)
    await audit(
        db,
        actor_id=actor_id,
        ticket_id=ticket.ticket_id,
        event="assigned",
        **{
            "from": previous_name,
            "to": _display_name(assignee),
            "from_id": str(previous_id) if previous_id else None,
            "to_id": str(assignee.user_id),
        },
    )
    return changes


async def _commit_and_reload(db: AsyncSession, ticket_id: uuid.UUID) -> Ticket:
    """الهدف: حفظ المعاملة ثم إعادة تحميل التذكرة بأسمائها المحدثة."""
    try:
        await db.commit()
    except IntegrityError as exc:
        raise TicketInvalidStateError(_STALE_MESSAGE) from exc
    return await load_ticket(db, ticket_id)


async def _finish_without_change(db: AsyncSession, ticket_id: uuid.UUID) -> WorkflowResult:
    """
    الهدف: إنهاء عملية ما غيّرت شيئًا (نفس الحالة/الإسناد) — commit فاضي
    يفك قفل الصف بدون rollback (اللي يُبطل كائنات الجلسة ومنها المستخدم الحالي).
    """
    await db.commit()
    return WorkflowResult(ticket=await load_ticket(db, ticket_id))


async def claim_ticket(db: AsyncSession, *, actor: User, ticket_id: uuid.UUID) -> WorkflowResult:
    """
    الهدف: استلام عضو الدعم للتذكرة بنفسه (TKT-FR-011).

    قواعد العمل:
    - يتطلب tickets.assign (بنطاق all).
    - لو مسندة لعضو دعم فعّال غيره → 409 برسالة "استلمها فلان" (الاستلام
      المتزامن: الأول ياخذها — القفل FOR UPDATE على صف التذكرة).
    - لو مسندة لشخص ما عاد في الدعم → يقدر يستلمها (تظهر بتبويب "غير مسندة").
    - لو مسندة له أصلًا → بدون تغيير.

    المخرجات: WorkflowResult. الأخطاء: 403/404/409.
    التأثيرات الجانبية: UPDATE + تدقيق + commit.
    """
    require_support(actor, TICKETS_ASSIGN)
    ticket = await load_ticket(db, ticket_id, for_update=True)
    ensure_open(ticket)
    if ticket.assignee_id == actor.user_id:
        return await _finish_without_change(db, ticket_id)
    if ticket.assignee_id is not None and ticket.assignee_id in await eligible_support_ids(db):
        raise TicketInvalidStateError(f"التذكرة استلمها {_display_name(ticket.assignee)}")
    changes = await _assign(db, ticket, actor, actor_id=actor.user_id)
    return WorkflowResult(
        ticket=await _commit_and_reload(db, ticket_id), status_changes=changes, assigned_to=actor.user_id
    )


async def assign_ticket(
    db: AsyncSession, *, actor: User, ticket_id: uuid.UUID, assignee_id: uuid.UUID
) -> WorkflowResult:
    """
    الهدف: إعادة إسناد التذكرة لعضو دعم آخر (TKT-FR-012).

    قواعد العمل:
    - يتطلب tickets.assign.
    - المسند إليه لازم عضو دعم مؤهل الآن (view_all بنطاق all، نشِط) — وإلا 400.

    المدخلات: معرّف التذكرة، ومعرّف عضو الدعم الجديد.
    المخرجات: WorkflowResult (assigned_to = الجديد، أو None لو نفسه).
    الأخطاء: 400/403/404/409.
    """
    require_support(actor, TICKETS_ASSIGN)
    if assignee_id not in await eligible_support_ids(db):
        raise TicketValidationError("المستخدم المختار ليس عضو دعم فنّي فعّال")
    ticket = await load_ticket(db, ticket_id, for_update=True)
    ensure_open(ticket)
    if ticket.assignee_id == assignee_id:
        return await _finish_without_change(db, ticket_id)
    assignee = await db.get(User, assignee_id)
    if assignee is None:
        raise TicketValidationError("المستخدم المختار غير موجود")
    changes = await _assign(db, ticket, assignee, actor_id=actor.user_id)
    return WorkflowResult(
        ticket=await _commit_and_reload(db, ticket_id), status_changes=changes, assigned_to=assignee_id
    )


async def change_status(db: AsyncSession, *, actor: User, ticket_id: uuid.UUID, target: str) -> WorkflowResult:
    """
    الهدف: تغيير الحالة يدويًا من الدعم (TKT-FR-015).

    قواعد العمل: المسموح فقط: قيد المعالجة ⇄ بانتظار رد المستخدم، و
    (جديدة/قيد المعالجة/بانتظار) ← تم الحل. يتطلب tickets.manage.
    الأخطاء: 403/404/409.
    """
    require_support(actor, TICKETS_MANAGE)
    ticket = await load_ticket(db, ticket_id, for_update=True)
    ensure_open(ticket)
    if ticket.status == target:
        return await _finish_without_change(db, ticket_id)
    if (ticket.status, target) not in _MANUAL_TRANSITIONS:
        raise TicketInvalidStateError("انتقال الحالة هذا غير مسموح")
    change = await set_status(db, ticket, target, actor_id=actor.user_id)
    return WorkflowResult(ticket=await _commit_and_reload(db, ticket_id), status_changes=[change])


async def update_fields(
    db: AsyncSession,
    *,
    actor: User,
    ticket_id: uuid.UUID,
    priority: str | None,
    ticket_type: str | None,
    module: str | None,
) -> WorkflowResult:
    """
    الهدف: تعديل الأولوية والنوع والوحدة (TKT-FR-016) — العنوان ثابت.

    قواعد العمل: يتطلب tickets.manage، والتذكرة مفتوحة. كل حقل تغيّر فعلًا
    يُسجَّل بحدث مستقل (priority_changed/type_changed/module_changed).
    الأخطاء: 403/404/409.
    """
    require_support(actor, TICKETS_MANAGE)
    ticket = await load_ticket(db, ticket_id, for_update=True)
    ensure_open(ticket)
    changes = [
        ("priority", "priority_changed", priority),
        ("ticket_type", "type_changed", ticket_type),
        ("module", "module_changed", module),
    ]
    changed_any = False
    for attr, event, value in changes:
        if value is None or getattr(ticket, attr) == value:
            continue
        previous = getattr(ticket, attr)
        setattr(ticket, attr, value)
        await flush_or_conflict(db)
        await audit(db, actor_id=actor.user_id, ticket_id=ticket.ticket_id, event=event, **{"from": previous, "to": value})
        changed_any = True
    if not changed_any:
        return await _finish_without_change(db, ticket_id)
    return WorkflowResult(ticket=await _commit_and_reload(db, ticket_id))


async def cancel_ticket(db: AsyncSession, *, actor: User, ticket_id: uuid.UUID) -> WorkflowResult:
    """
    الهدف: إلغاء صاحب التذكرة لها وهي "جديدة" (TKT-FR-005).

    قواعد العمل: صاحب التذكرة فقط (مع tickets.create) — غيره يشوف 404.
    بعد الاستلام ممنوع (409): يرد ويطلب إغلاقها.
    """
    require_requester(actor)
    ticket = await load_ticket(db, ticket_id, for_update=True)
    if ticket.requester_id != actor.user_id:
        raise TicketNotFoundError("التذكرة غير موجودة")
    if ticket.status != _NEW:
        raise TicketInvalidStateError("الإلغاء متاح فقط قبل ما يستلم الدعم التذكرة")
    change = await set_status(db, ticket, _CANCELLED, actor_id=actor.user_id)
    return WorkflowResult(ticket=await _commit_and_reload(db, ticket_id), status_changes=[change])


@dataclass(frozen=True)
class AutoClosedTicket:
    """الهدف: تذكرة أُغلقت تلقائيًا — بيانات الإشعار فقط."""

    ticket_id: uuid.UUID
    ticket_number: str
    requester_id: uuid.UUID


async def auto_close_resolved(db: AsyncSession, *, now: datetime | None = None) -> list[AutoClosedTicket]:
    """
    الهدف: إغلاق التذاكر اللي مرّ على حلّها 4 أيام (TKT-FR-021) — يستدعيها المجدول.

    قواعد العمل:
    - SKIP LOCKED: تذكرة يرد عليها مقدّم الطلب الآن (صفها مقفول) تُترك
      للدورة الجاية، فالرد يعيد فتحها بدل ما تنقفل تحته.
    - الفاعل None (عملية تلقائية) بسجل التدقيق — السجل يعرضها "تلقائي".

    المخرجات: التذاكر اللي انقفلت (للإشعارات).
    التأثيرات الجانبية: UPDATE + تدقيق + commit.
    """
    now = now or now_utc()
    stmt = (
        select(Ticket)
        .where(Ticket.status == _RESOLVED, Ticket.resolved_at <= now - AUTO_CLOSE_AFTER)
        .with_for_update(skip_locked=True)
    )
    tickets = (await db.execute(stmt)).scalars().all()
    closed: list[AutoClosedTicket] = []
    for ticket in tickets:
        await set_status(db, ticket, _CLOSED, actor_id=None)
        closed.append(
            AutoClosedTicket(ticket_id=ticket.ticket_id, ticket_number=ticket.ticket_number, requester_id=ticket.requester_id)
        )
    await db.commit()
    return closed


def can_auto_assign_on_reply(actor: User) -> bool:
    """
    الهدف: هل رد الدعم الأول على تذكرة غير مسندة يسندها له تلقائيًا؟
    قاعدة العمل: نعم لو يملك tickets.assign (نفس سلوك Zendesk: الرد يعني الاستلام).
    """
    return has_support_permission(actor, TICKETS_ASSIGN)


async def assign_on_reply(db: AsyncSession, ticket: Ticket, actor: User) -> list[StatusChange]:
    """
    الهدف: الإسناد التلقائي عند أول رد عام من الدعم على تذكرة غير مسندة.
    راجعي can_auto_assign_on_reply. التأثيرات الجانبية: نفس _assign.
    """
    return await _assign(db, ticket, actor, actor_id=actor.user_id)
