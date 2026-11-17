"""
الهدف:
محادثة التذكرة: حفظ الرسائل ومرفقاتها، الرد (مقدّم الطلب/الدعم)، الملاحظات
الداخلية، عرض الرسائل، وتنزيل المرفقات (القسم 7 بالمواصفات).

قواعد العمل:
- الملاحظة الداخلية للدعم فقط (tickets.internal_notes) ولا تُرجع أبدًا لغير الدعم.
- رد مقدّم الطلب: "بانتظار رد المستخدم" ← "قيد المعالجة"، و"تم الحل" ←
  "قيد المعالجة" (إعادة فتح لنفس المسند إليه).
- رد الدعم (tickets.reply) يحدد الحالة بعده بنفس الخطوة (TKT-FR-013)، وأول
  رد على تذكرة غير مسندة يسندها للراد لو يملك tickets.assign. رد الدعم على
  تذكرة "تم الحل" يبقيها محلولة — إعادة الفتح لمقدّم الطلب فقط.
- الرسائل ما تنعدّل ولا تنحذف (trigger بالقاعدة).
- منع التكرار: client_message_id لكل مرسل — إعادة المحاولة بنفس المعرّف
  ترجع الرسالة المحفوظة بدل إنشاء ثانية (العرض المتفائل، TKT-FR-025).

التخزين: المرفق يُرفع لنفس التخزين المستخدم بالمنصة (storage_client) بمسار
tickets/{ticket_id}/{attachment_id} — بدون اسم الملف (UUID فقط)، ويُحذف لو
فشل الحفظ بالقاعدة بعد الرفع.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage_client
from app.models.ticket import (
    FINAL_STATUSES,
    Ticket,
    TicketAttachment,
    TicketAuthorSide,
    TicketMessage,
    TicketStatus,
)
from app.models.user import User
from app.services.ticket_service.access import (
    Viewer,
    can_request,
    has_support_permission,
    resolve_viewer,
)
from app.services.ticket_service.codes import TICKETS_INTERNAL_NOTES, TICKETS_REPLY
from app.services.ticket_service.content import (
    IncomingFile,
    ValidatedFile,
    parse_body,
    validate_body,
    validate_files,
)
from app.services.ticket_service.errors import (
    TicketForbiddenError,
    TicketInvalidStateError,
    TicketNotFoundError,
    TicketStorageError,
    TicketValidationError,
)
from app.services.ticket_service.loading import MESSAGE_OPTIONS, load_message, load_ticket
from app.services.ticket_service.workflow import (
    StatusChange,
    assign_on_reply,
    audit,
    can_auto_assign_on_reply,
    flush_or_conflict,
    move_for_reply,
    set_status,
)

_IN_PROGRESS = TicketStatus.in_progress.value
_WAITING = TicketStatus.waiting_on_requester.value
_RESOLVED = TicketStatus.resolved.value


@dataclass
class MessagePostResult:
    """
    الهدف: نتيجة إرسال رسالة — يحتاجها الراوت للإشعارات والبث اللحظي.

    الحقول:
    - message / ticket: بعد الحفظ (محمَّلة بالأسماء والمرفقات).
    - created: False لو كانت إعادة محاولة لرسالة محفوظة مسبقًا (لا إشعارات).
    - side: صفة الكاتب (requester/support).
    - status_changes: خطوات الحالة اللي صارت مع الرسالة.
    - reopened: رد مقدّم الطلب أعاد فتح تذكرة "تم الحل".
    - assigned_to: الإسناد التلقائي عند أول رد من الدعم.
    """

    message: TicketMessage
    ticket: Ticket
    created: bool
    side: str
    status_changes: list[StatusChange] = field(default_factory=list)
    reopened: bool = False
    assigned_to: uuid.UUID | None = None


async def find_by_client_id(
    db: AsyncSession, *, author_id: uuid.UUID, client_message_id: uuid.UUID | None
) -> TicketMessage | None:
    """
    الهدف: رسالة محفوظة مسبقًا بنفس معرّف المتصفح لنفس الكاتب (منع التكرار).
    المخرجات: الرسالة أو None.
    """
    if client_message_id is None:
        return None
    stmt = select(TicketMessage).where(
        TicketMessage.author_id == author_id, TicketMessage.client_message_id == client_message_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def insert_message(
    db: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    author: User,
    side: str,
    is_internal: bool,
    is_description: bool,
    body: dict,
    text: str,
    client_message_id: uuid.UUID | None,
    files: list[ValidatedFile],
) -> tuple[TicketMessage, list[str]]:
    """
    الهدف: حفظ رسالة ومرفقاتها ورفع الملفات للتخزين (بدون commit).

    المدخلات: التذكرة، الكاتب وصفته، نوع الرسالة، المحتوى بعد التحقق، الملفات المقبولة.
    المخرجات: (الرسالة، مسارات التخزين المرفوعة — لحذفها لو فشل الـcommit).

    التأثيرات الجانبية: INSERT للرسالة والمرفقات + رفع الملفات + صف تدقيق.
    الأخطاء: TicketStorageError (503) لو فشل الرفع — بعد حذف ما رُفع منها.
    """
    message = TicketMessage(
        ticket_id=ticket_id,
        author_id=author.user_id,
        author_side=side,
        is_internal=is_internal,
        is_description=is_description,
        body_json=body,
        body_text=text,
        client_message_id=client_message_id,
    )
    db.add(message)
    await db.flush()

    attachments: list[tuple[TicketAttachment, bytes]] = []
    for incoming in files:
        attachment_id = uuid.uuid4()
        attachment = TicketAttachment(
            attachment_id=attachment_id,
            message_id=message.message_id,
            file_name=incoming.file_name,
            storage_path=f"tickets/{ticket_id}/{attachment_id}",
            mime_type=incoming.mime_type,
            file_size_bytes=len(incoming.content),
        )
        db.add(attachment)
        attachments.append((attachment, incoming.content))
    if attachments:
        await db.flush()

    uploaded: list[str] = []
    try:
        for attachment, content in attachments:
            await storage_client.upload_object(attachment.storage_path, content, content_type=attachment.mime_type)
            uploaded.append(attachment.storage_path)
    except storage_client.StorageError as exc:
        await remove_uploaded(uploaded)
        raise TicketStorageError("تعذّر حفظ المرفق — حاول مرة ثانية") from exc

    await audit(
        db,
        actor_id=author.user_id,
        ticket_id=ticket_id,
        event="message_added",
        action="create",
        message_id=str(message.message_id),
        is_internal=is_internal,
        side=side,
        attachments=len(attachments),
    )
    return message, uploaded


async def remove_uploaded(paths: list[str]) -> None:
    """
    الهدف: حذف ملفات رُفعت لكن رسالتها ما انحفظت (تنظيف بعد فشل).
    لا يرفع استثناء — الفشل هنا ما يغيّر نتيجة العملية الأصلية.
    """
    for path in paths:
        try:
            await storage_client.delete_object(path)
        except Exception:  # noqa: BLE001 — تنظيف بأفضل جهد
            continue


async def _duplicate_result(db: AsyncSession, existing: TicketMessage, ticket_id: uuid.UUID) -> MessagePostResult:
    """
    الهدف: نتيجة إعادة محاولة لرسالة محفوظة مسبقًا — بدون أي تغيير ولا إشعارات.
    commit فاضي يفك قفل التذكرة بدون rollback (اللي يُبطل كائنات الجلسة).
    """
    await db.commit()
    return MessagePostResult(
        message=await load_message(db, existing.message_id),
        ticket=await load_ticket(db, ticket_id),
        created=False,
        side=existing.author_side,
    )


def _resolve_side(actor: User, ticket: Ticket, *, is_internal: bool) -> str:
    """
    الهدف: بأي صفة يكتب المستخدم هذه الرسالة؟

    قواعد العمل:
    - ملاحظة داخلية → support، وتتطلب tickets.internal_notes.
    - صاحب التذكرة (مع tickets.create) → requester، حتى لو كان عضو دعم.
    - غيره → support، ويتطلب tickets.reply.
    - غير ذلك: 404 لمن ما له علاقة بالتذكرة، و403 لمن يشوفها بدون صلاحية الرد.
    """
    if is_internal:
        if not has_support_permission(actor, TICKETS_INTERNAL_NOTES):
            resolve_viewer(actor, ticket)  # 404 لمن ما يشوف التذكرة أصلًا
            raise TicketForbiddenError("ليست لديك صلاحية كتابة الملاحظات الداخلية")
        return TicketAuthorSide.support.value
    if ticket.requester_id == actor.user_id and can_request(actor):
        return TicketAuthorSide.requester.value
    if has_support_permission(actor, TICKETS_REPLY):
        return TicketAuthorSide.support.value
    resolve_viewer(actor, ticket)
    raise TicketForbiddenError("ليست لديك صلاحية الرد على هذه التذكرة")


async def post_message(
    db: AsyncSession,
    *,
    actor: User,
    ticket_id: uuid.UUID,
    body_raw: str | None,
    is_internal: bool,
    status_after: str | None,
    client_message_id: uuid.UUID | None,
    files: list[IncomingFile],
) -> MessagePostResult:
    """
    الهدف: إرسال رد أو ملاحظة داخلية على تذكرة (TKT-FR-004/013/014، و006 لإعادة الفتح).

    المدخلات:
    - body_raw: نص TipTap كـJSON (يصير فاضي لو فيه مرفق).
    - is_internal: ملاحظة داخلية (دعم فقط).
    - status_after: الحالة بعد رد الدعم (in_progress/waiting_on_requester/resolved)
      — مرفوض لمقدّم الطلب وللملاحظة الداخلية.
    - client_message_id: لمنع التكرار عند إعادة المحاولة.
    - files: المرفقات (5 كحد أقصى).

    المخرجات: MessagePostResult.

    التأثيرات الجانبية: INSERT رسالة ومرفقات، رفع ملفات، UPDATE الحالة/الإسناد،
    صفوف تدقيق، ثم commit. (الإشعارات والبث بالراوت بعد النجاح.)

    الأخطاء: 400 (محتوى/مرفقات/حالة غير مناسبة للصفة)، 403، 404، 409 (مغلقة/
    تعارض)، 503 (التخزين).
    """
    ticket = await load_ticket(db, ticket_id, for_update=True)
    side = _resolve_side(actor, ticket, is_internal=is_internal)
    if status_after is not None and (is_internal or side == TicketAuthorSide.requester.value):
        raise TicketValidationError("تحديد الحالة مع الرسالة متاح لرد الدعم فقط")
    if TicketStatus(ticket.status) in FINAL_STATUSES:
        raise TicketInvalidStateError("لا يمكن الرد على تذكرة مغلقة أو ملغاة")

    existing = await find_by_client_id(db, author_id=actor.user_id, client_message_id=client_message_id)
    if existing is not None:
        if existing.ticket_id != ticket_id:
            raise TicketInvalidStateError("معرّف الرسالة مستخدم لتذكرة أخرى")
        return await _duplicate_result(db, existing, ticket_id)

    validated_files = validate_files(files)
    doc, text = validate_body(parse_body(body_raw), is_description=False, has_attachments=bool(validated_files))

    # الكتابة داخل savepoint: لو تعارض شيء (مثل إعادة محاولة متزامنة بنفس
    # client_message_id) يُلغى الـsavepoint فقط، وتبقى الجلسة وقفل التذكرة
    # والمستخدم الحالي سليمين — rollback الكامل يُبطل كل كائنات الجلسة.
    uploaded: list[str] = []
    try:
        async with db.begin_nested():
            message, uploaded = await insert_message(
                db,
                ticket_id=ticket_id,
                author=actor,
                side=side,
                is_internal=is_internal,
                is_description=False,
                body=doc,
                text=text,
                client_message_id=client_message_id,
                files=validated_files,
            )
            result = MessagePostResult(message=message, ticket=ticket, created=True, side=side)
            if not is_internal and side == TicketAuthorSide.requester.value:
                if ticket.status == _WAITING:
                    result.status_changes.append(await set_status(db, ticket, _IN_PROGRESS, actor_id=actor.user_id))
                elif ticket.status == _RESOLVED:
                    result.status_changes.append(await set_status(db, ticket, _IN_PROGRESS, actor_id=actor.user_id))
                    result.reopened = True
            elif not is_internal:
                if ticket.assignee_id is None and can_auto_assign_on_reply(actor):
                    result.status_changes.extend(await assign_on_reply(db, ticket, actor))
                    result.assigned_to = actor.user_id
                # الافتراضي "بانتظار رد المستخدم"، إلا المحلولة تبقى محلولة.
                target = status_after or (_RESOLVED if ticket.status == _RESOLVED else _WAITING)
                result.status_changes.extend(await move_for_reply(db, ticket, target, actor_id=actor.user_id))
            await flush_or_conflict(db)
    except IntegrityError as exc:
        await remove_uploaded(uploaded)
        duplicate = await find_by_client_id(db, author_id=actor.user_id, client_message_id=client_message_id)
        if duplicate is not None and duplicate.ticket_id == ticket_id:
            return await _duplicate_result(db, duplicate, ticket_id)
        raise TicketInvalidStateError("تغيّرت التذكرة من مكان ثاني — حدّث الصفحة وحاول مرة ثانية") from exc
    except Exception:
        await remove_uploaded(uploaded)
        raise

    try:
        await db.commit()
    except IntegrityError as exc:
        await remove_uploaded(uploaded)
        raise TicketInvalidStateError("تعذّر حفظ الرسالة — حدّث الصفحة وحاول مرة ثانية") from exc

    result.message = await load_message(db, message.message_id)
    result.ticket = await load_ticket(db, ticket_id)
    return result


async def list_messages(
    db: AsyncSession, *, actor: User, ticket_id: uuid.UUID
) -> tuple[Viewer, list[TicketMessage]]:
    """
    الهدف: رسائل التذكرة بالترتيب (TKT-FR-003).

    قواعد العمل: مقدّم الطلب يشوف الردود العامة فقط — الملاحظات الداخلية
    تُستبعد بالاستعلام نفسه (ما تطلع من القاعدة أصلًا).
    المخرجات: (صفة المشاهد، الرسائل).
    الأخطاء: 403/404 حسب resolve_viewer.
    """
    ticket = await load_ticket(db, ticket_id)
    viewer = resolve_viewer(actor, ticket)
    stmt = (
        select(TicketMessage)
        .where(TicketMessage.ticket_id == ticket_id)
        .options(*MESSAGE_OPTIONS)
        .order_by(TicketMessage.created_at.asc(), TicketMessage.message_id.asc())
    )
    if viewer != "support":
        stmt = stmt.where(TicketMessage.is_internal.is_(False))
    return viewer, list((await db.execute(stmt)).scalars().all())


async def get_attachment_download(
    db: AsyncSession, *, actor: User, ticket_id: uuid.UUID, attachment_id: uuid.UUID
) -> tuple[TicketAttachment, bytes]:
    """
    الهدف: تنزيل مرفق بعد فحص الصلاحية (القسم 9: لا روابط تخزين مباشرة).

    قواعد العمل: المرفق لازم يتبع رسالة بنفس التذكرة، ومرفق الملاحظة
    الداخلية للدعم فقط (404 لغيره).
    المخرجات: (المرفق، محتوى الملف).
    الأخطاء: 403/404، وTicketStorageError لو تعذّر القراءة من التخزين.
    """
    ticket = await load_ticket(db, ticket_id)
    viewer = resolve_viewer(actor, ticket)
    stmt = (
        select(TicketAttachment, TicketMessage)
        .join(TicketMessage, TicketMessage.message_id == TicketAttachment.message_id)
        .where(TicketAttachment.attachment_id == attachment_id, TicketMessage.ticket_id == ticket_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise TicketNotFoundError("المرفق غير موجود")
    attachment, message = row
    if message.is_internal and viewer != "support":
        raise TicketNotFoundError("المرفق غير موجود")
    try:
        content = await storage_client.download_object(attachment.storage_path)
    except storage_client.StorageError as exc:
        raise TicketStorageError("تعذّر قراءة المرفق — حاول مرة ثانية") from exc
    return attachment, content
