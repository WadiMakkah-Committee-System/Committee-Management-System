"""
الهدف:
راوتات REST لوحدة "التذاكر" (الدعم الفني). منطق العمل والصلاحيات كاملة
بـapp/services/ticket_service — الراوت يقرأ المدخلات، يترجم الأخطاء، ويطلق
الإشعارات والبث اللحظي بعد نجاح الحفظ فقط.

المسارات (كلها تتطلب تسجيل الدخول؛ الضيوف ممنوعون من get_current_user نفسه):
مقدّم الطلب (tickets.create):
- POST   /tickets                       إرسال تذكرة (multipart: وصف + مرفقات)
- GET    /tickets/mine                  تذاكري
- POST   /tickets/{id}/cancel           إلغاء تذكرتي وهي "جديدة"
الدعم (tickets.view_all + الخانة المطلوبة، بنطاق "all"):
- GET    /tickets                       قائمة الدعم (unassigned/mine/all + فلاتر + بحث)
- GET    /tickets/support-members       أعضاء الدعم للإسناد (tickets.assign)
- POST   /tickets/{id}/claim            استلام (tickets.assign)
- POST   /tickets/{id}/assign           إعادة إسناد (tickets.assign)
- POST   /tickets/{id}/status           تغيير الحالة (tickets.manage)
- PATCH  /tickets/{id}                  الأولوية/النوع/الوحدة (tickets.manage)
- GET    /tickets/{id}/history          سجل التذكرة (tickets.view_all)
الطرفين (حسب صفة المشاهد):
- GET    /tickets/{id}                  التفاصيل
- GET    /tickets/{id}/messages         المحادثة (بدون الملاحظات الداخلية لمقدّم الطلب)
- POST   /tickets/{id}/messages         رد / ملاحظة داخلية (multipart)
- GET    /tickets/{id}/attachments/{attachment_id}/download

ترجمة الأخطاء: 404 غير موجودة أو لا علاقة للمستخدم بها، 403 بدون صلاحية،
409 حالة غير مناسبة أو تعارض، 400 مدخلات غير صالحة، 503 التخزين.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.documents import _content_disposition
from app.core import ticket_realtime
from app.core.background import run_detached
from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.models.ticket import TicketModule, TicketPriority, TicketStatus, TicketType
from app.models.user import User
from app.schemas.ticket import (
    SupportSettableStatus,
    TicketAssign,
    TicketFieldsUpdate,
    TicketHistoryEntryOut,
    TicketMessageOut,
    TicketMessagePostOut,
    TicketOut,
    TicketPageOut,
    TicketStatusUpdate,
    TicketSupportMemberOut,
)
from app.services import notification_service, ticket_service
from app.services.ticket_service import (
    IncomingFile,
    TicketForbiddenError,
    TicketInvalidStateError,
    TicketNotFoundError,
    TicketStorageError,
    TicketValidationError,
)
from app.services.ticket_service.content import MAX_ATTACHMENTS_PER_MESSAGE

router = APIRouter(prefix="/tickets", tags=["tickets"])

_SERVICE_ERRORS = (
    TicketNotFoundError,
    TicketForbiddenError,
    TicketInvalidStateError,
    TicketValidationError,
    TicketStorageError,
)


def _handle_errors(exc: Exception) -> HTTPException:
    """
    الهدف: ترجمة أخطاء خدمة التذاكر لاستجابات HTTP (بدون كشف أي تفاصيل داخلية).
    المدخلات: استثناء من _SERVICE_ERRORS. المخرجات: HTTPException مناسبة.
    """
    if isinstance(exc, TicketNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, TicketForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, TicketInvalidStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, TicketStorageError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


async def _read_files(files: list[UploadFile]) -> list[IncomingFile]:
    """
    الهدف: قراءة الملفات المرفوعة (بعد رفض أي طلب فيه أكثر من 5 قبل القراءة).
    المخرجات: الملفات كبايتات — التحقق من النوع والحجم بطبقة الخدمة.
    الأخطاء: HTTPException 400 لو العدد أكبر من الحد.
    """
    if len(files) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"الحد الأقصى {MAX_ATTACHMENTS_PER_MESSAGE} مرفقات لكل رسالة",
        )
    return [IncomingFile(file_name=f.filename or "", content=await f.read()) for f in files]


async def _ticket_out(db: AsyncSession, ticket, *, actor: User, viewer: str) -> TicketOut:
    """الهدف: بناء TicketOut (مع أعضاء الدعم المؤهلين لو المشاهد دعم)."""
    support_ids = await ticket_service.eligible_support_ids(db) if viewer == "support" else None
    return ticket_service.ticket_out(ticket, actor=actor, viewer=viewer, support_ids=support_ids)


@router.post("", response_model=TicketMessagePostOut, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    current_user: CurrentUser,
    title: str = Form(...),
    ticket_type: TicketType = Form(...),
    module: TicketModule = Form(...),
    body: str = Form(...),
    client_message_id: uuid.UUID | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
) -> TicketMessagePostOut:
    """
    الهدف: إرسال تذكرة جديدة (TKT-FR-001) — multipart/form-data.

    المدخلات: title، ticket_type، module، body (وصف TipTap كـJSON)،
    client_message_id (اختياري لمنع التكرار)، files (حتى 5).
    المخرجات: التذكرة + رسالة الوصف. إعادة المحاولة بنفس client_message_id
    ترجع نفس التذكرة بدون إشعارات مكررة.
    الصلاحيات: tickets.create.
    """
    incoming = await _read_files(files)
    try:
        ticket, created = await ticket_service.create_ticket(
            db,
            actor=current_user,
            title=title,
            ticket_type=ticket_type.value,
            module=module.value,
            body_raw=body,
            client_message_id=client_message_id,
            files=incoming,
        )
        description = await ticket_service.get_description(db, ticket_id=ticket.ticket_id)
        viewer = ticket_service.resolve_viewer(current_user, ticket)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    if created:
        run_detached(notification_service.notify_ticket_created(ticket, actor_user_id=current_user.user_id))
    return TicketMessagePostOut(
        message=ticket_service.message_out(description, viewer=viewer),
        ticket=await _ticket_out(db, ticket, actor=current_user, viewer=viewer),
    )


@router.get("/mine", response_model=TicketPageOut)
async def list_my_tickets(
    current_user: CurrentUser,
    status_filter: list[TicketStatus] | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> TicketPageOut:
    """
    الهدف: "تذاكري" (TKT-FR-002) — تذاكر المستخدم الحالي فقط (من التوكن).
    الصلاحيات: tickets.create.
    """
    try:
        tickets, total = await ticket_service.list_my_tickets(
            db,
            actor=current_user,
            statuses=[s.value for s in status_filter] if status_filter else None,
            limit=limit,
            offset=offset,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    support_ids = await ticket_service.eligible_support_ids(db) if ticket_service.is_support(current_user) else None
    items = [
        ticket_service.ticket_out(
            t, actor=current_user, viewer=ticket_service.resolve_viewer(current_user, t), support_ids=support_ids
        )
        for t in tickets
    ]
    return TicketPageOut(items=items, total=total, limit=limit, offset=offset)


@router.get("", response_model=TicketPageOut)
async def list_support_tickets(
    current_user: CurrentUser,
    tab: Literal["unassigned", "mine", "all"] = Query(default="all"),
    status_filter: list[TicketStatus] | None = Query(default=None, alias="status"),
    ticket_type: TicketType | None = Query(default=None),
    module: TicketModule | None = Query(default=None),
    priority: TicketPriority | None = Query(default=None),
    q: str | None = Query(default=None, max_length=150),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> TicketPageOut:
    """
    الهدف: قائمة الدعم (TKT-FR-010) بالتبويبات والفلاتر والبحث بالرقم أو العنوان.
    الصلاحيات: tickets.view_all بنطاق all.
    """
    try:
        tickets, total = await ticket_service.list_support_tickets(
            db,
            actor=current_user,
            tab=tab,
            statuses=[s.value for s in status_filter] if status_filter else None,
            ticket_type=ticket_type.value if ticket_type else None,
            module=module.value if module else None,
            priority=priority.value if priority else None,
            query=q,
            limit=limit,
            offset=offset,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    support_ids = await ticket_service.eligible_support_ids(db)
    items = [
        ticket_service.ticket_out(t, actor=current_user, viewer="support", support_ids=support_ids) for t in tickets
    ]
    return TicketPageOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/support-members", response_model=list[TicketSupportMemberOut])
async def list_support_members(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[TicketSupportMemberOut]:
    """الهدف: أعضاء الدعم المؤهلين لقائمة إعادة الإسناد. الصلاحيات: tickets.assign."""
    try:
        return await ticket_service.list_support_members(db, actor=current_user)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc


@router.get("/{ticket_id}", response_model=TicketOut)
async def get_ticket(ticket_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)) -> TicketOut:
    """
    الهدف: تفاصيل تذكرة حسب صفة المشاهد.
    الأخطاء: 404 لمن ما له علاقة بها (ما ينكشف وجودها)، 403 لصاحبها بدون tickets.create.
    """
    try:
        ticket, viewer = await ticket_service.get_ticket(db, actor=current_user, ticket_id=ticket_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return await _ticket_out(db, ticket, actor=current_user, viewer=viewer)


@router.get("/{ticket_id}/messages", response_model=list[TicketMessageOut])
async def list_messages(
    ticket_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[TicketMessageOut]:
    """
    الهدف: محادثة التذكرة بالترتيب (TKT-FR-003) — الملاحظات الداخلية للدعم فقط
    (تُستبعد من الاستعلام نفسه لمقدّم الطلب).
    """
    try:
        viewer, messages = await ticket_service.list_messages(db, actor=current_user, ticket_id=ticket_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return [ticket_service.message_out(m, viewer=viewer) for m in messages]


@router.post("/{ticket_id}/messages", response_model=TicketMessagePostOut, status_code=status.HTTP_201_CREATED)
async def post_message(
    ticket_id: uuid.UUID,
    current_user: CurrentUser,
    body: str = Form(default=""),
    is_internal: bool = Form(default=False),
    status_after: SupportSettableStatus | None = Form(default=None),
    client_message_id: uuid.UUID | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
) -> TicketMessagePostOut:
    """
    الهدف: رد أو ملاحظة داخلية (TKT-FR-004/006/013/014) — multipart/form-data.

    المدخلات:
    - body: نص TipTap كـJSON (يصير فاضي لو فيه مرفق).
    - is_internal: ملاحظة داخلية (tickets.internal_notes).
    - status_after: لرد الدعم فقط — الحالة بعد الرد (الافتراضي بانتظار رد المستخدم).
    - client_message_id: إعادة المحاولة بنفس المعرّف ترجع نفس الرسالة.
    - files: حتى 5 مرفقات.

    المخرجات: الرسالة + التذكرة بعد أي تغيير حالة.
    التأثيرات الجانبية بعد النجاح: إشعار واحد للطرف الثاني (ما عدا الملاحظة
    الداخلية) وبث لحظي.
    """
    incoming = await _read_files(files)
    try:
        result = await ticket_service.post_message(
            db,
            actor=current_user,
            ticket_id=ticket_id,
            body_raw=body,
            is_internal=is_internal,
            status_after=status_after,
            client_message_id=client_message_id,
            files=incoming,
        )
        viewer = ticket_service.resolve_viewer(current_user, result.ticket)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc

    if result.created:
        ticket = result.ticket
        message = result.message
        run_detached(ticket_realtime.emit_ticket_message(ticket.ticket_id, message.message_id, is_internal=message.is_internal))
        if result.status_changes:
            run_detached(ticket_realtime.emit_ticket_updated(ticket.ticket_id, support_only=False))
        if not message.is_internal:
            if result.side == "requester":
                run_detached(
                    notification_service.notify_ticket_requester_replied(
                        ticket, actor_user_id=current_user.user_id, reopened=result.reopened
                    )
                )
            else:
                run_detached(notification_service.notify_ticket_support_replied(ticket, actor_user_id=current_user.user_id))

    return TicketMessagePostOut(
        message=ticket_service.message_out(result.message, viewer=viewer),
        ticket=await _ticket_out(db, result.ticket, actor=current_user, viewer=viewer),
    )


@router.post("/{ticket_id}/cancel", response_model=TicketOut)
async def cancel_ticket(
    ticket_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> TicketOut:
    """الهدف: إلغاء صاحب التذكرة لها وهي "جديدة" (TKT-FR-005). الصلاحيات: tickets.create."""
    try:
        result = await ticket_service.cancel_ticket(db, actor=current_user, ticket_id=ticket_id)
        viewer = ticket_service.resolve_viewer(current_user, result.ticket)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    run_detached(ticket_realtime.emit_ticket_updated(ticket_id, support_only=False))
    return await _ticket_out(db, result.ticket, actor=current_user, viewer=viewer)


@router.post("/{ticket_id}/claim", response_model=TicketOut)
async def claim_ticket(
    ticket_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> TicketOut:
    """
    الهدف: استلام التذكرة (TKT-FR-011). لو استلمها عضو ثاني قبله بلحظة → 409
    برسالة "التذكرة استلمها فلان". الصلاحيات: tickets.assign.
    """
    try:
        result = await ticket_service.claim_ticket(db, actor=current_user, ticket_id=ticket_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    if result.assigned_to is not None:
        run_detached(ticket_realtime.emit_ticket_updated(ticket_id, support_only=not result.status_changes))
    return await _ticket_out(db, result.ticket, actor=current_user, viewer="support")


@router.post("/{ticket_id}/assign", response_model=TicketOut)
async def assign_ticket(
    ticket_id: uuid.UUID,
    payload: TicketAssign,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TicketOut:
    """
    الهدف: إعادة إسناد التذكرة لعضو دعم آخر (TKT-FR-012) — يُشعَر المسند إليه.
    الصلاحيات: tickets.assign. الأخطاء: 400 لو المختار ليس عضو دعم فعّال.
    """
    try:
        result = await ticket_service.assign_ticket(
            db, actor=current_user, ticket_id=ticket_id, assignee_id=payload.assignee_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    if result.assigned_to is not None:
        run_detached(ticket_realtime.emit_ticket_updated(ticket_id, support_only=not result.status_changes))
        run_detached(notification_service.notify_ticket_assigned(result.ticket, actor_user_id=current_user.user_id))
    return await _ticket_out(db, result.ticket, actor=current_user, viewer="support")


@router.post("/{ticket_id}/status", response_model=TicketOut)
async def change_status(
    ticket_id: uuid.UUID,
    payload: TicketStatusUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TicketOut:
    """
    الهدف: تغيير الحالة يدويًا (TKT-FR-015). "تم الحل" بدون رد يُشعر مقدّم الطلب.
    الصلاحيات: tickets.manage.
    """
    try:
        result = await ticket_service.change_status(db, actor=current_user, ticket_id=ticket_id, target=payload.status)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    if result.status_changes:
        run_detached(ticket_realtime.emit_ticket_updated(ticket_id, support_only=False))
        if result.ticket.status == TicketStatus.resolved.value:
            run_detached(notification_service.notify_ticket_resolved(result.ticket, actor_user_id=current_user.user_id))
    return await _ticket_out(db, result.ticket, actor=current_user, viewer="support")


@router.patch("/{ticket_id}", response_model=TicketOut)
async def update_ticket_fields(
    ticket_id: uuid.UUID,
    payload: TicketFieldsUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TicketOut:
    """
    الهدف: تعديل الأولوية والنوع والوحدة (TKT-FR-016) — العنوان ثابت.
    الصلاحيات: tickets.manage.
    """
    try:
        result = await ticket_service.update_fields(
            db,
            actor=current_user,
            ticket_id=ticket_id,
            priority=payload.priority.value if payload.priority else None,
            ticket_type=payload.ticket_type.value if payload.ticket_type else None,
            module=payload.module.value if payload.module else None,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    run_detached(ticket_realtime.emit_ticket_updated(ticket_id, support_only=False))
    return await _ticket_out(db, result.ticket, actor=current_user, viewer="support")


@router.get("/{ticket_id}/history", response_model=list[TicketHistoryEntryOut])
async def get_history(
    ticket_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[TicketHistoryEntryOut]:
    """الهدف: سجل التذكرة (TKT-FR-017) من audit_logs. الصلاحيات: tickets.view_all."""
    try:
        return await ticket_service.get_history(db, actor=current_user, ticket_id=ticket_id)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc


@router.get("/{ticket_id}/attachments/{attachment_id}/download")
async def download_attachment(
    ticket_id: uuid.UUID,
    attachment_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    الهدف: تنزيل مرفق بعد فحص الصلاحية (مرفقات الملاحظات الداخلية للدعم فقط).
    المخرجات: الملف نفسه مع اسمه الأصلي (RFC 5987 للأسماء العربية).
    """
    try:
        attachment, content = await ticket_service.get_attachment_download(
            db, actor=current_user, ticket_id=ticket_id, attachment_id=attachment_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return Response(
        content=content,
        media_type=attachment.mime_type,
        headers={
            "Content-Disposition": _content_disposition(attachment.file_name),
            "X-Content-Type-Options": "nosniff",
        },
    )
