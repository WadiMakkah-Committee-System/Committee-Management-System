"""
الهدف:
خدمة "التذاكر" (الدعم الفني) — منطق العمل كاملًا، والراوت (app/api/v1/tickets.py)
يترجم المدخلات والأخطاء فقط. المتطلبات: tickets_spec.md، وقاعدة البيانات:
db/migrations/0051_tickets.sql.

الوحدات:
- access: الصلاحيات وصفة المشاهد وأعضاء الدعم المؤهلين.
- content: التحقق من نص TipTap والمرفقات.
- loading: التحميل بالأسماء فقط وبناء المخرجات حسب المشاهد.
- workflow: الحالات والاستلام والإسناد والتعديل والإلغاء والإغلاق التلقائي.
- messages: الرسائل والملاحظات الداخلية والمرفقات.
- crud: الإنشاء والقوائم والتفاصيل والسجل.
"""

from app.services.ticket_service.access import (
    can_request,
    eligible_support_user_ids_query,
    has_support_permission,
    is_support,
    resolve_viewer,
)
from app.services.ticket_service.content import IncomingFile
from app.services.ticket_service.crud import (
    create_ticket,
    get_description,
    get_history,
    get_ticket,
    list_my_tickets,
    list_support_members,
    list_support_tickets,
)
from app.services.ticket_service.errors import (
    TicketForbiddenError,
    TicketInvalidStateError,
    TicketNotFoundError,
    TicketStorageError,
    TicketValidationError,
)
from app.services.ticket_service.loading import eligible_support_ids, message_out, ticket_out
from app.services.ticket_service.messages import (
    MessagePostResult,
    get_attachment_download,
    list_messages,
    post_message,
)
from app.services.ticket_service.workflow import (
    AUTO_CLOSE_AFTER,
    AutoClosedTicket,
    WorkflowResult,
    assign_ticket,
    auto_close_resolved,
    cancel_ticket,
    change_status,
    claim_ticket,
    update_fields,
)

__all__ = [
    "AUTO_CLOSE_AFTER",
    "AutoClosedTicket",
    "IncomingFile",
    "MessagePostResult",
    "TicketForbiddenError",
    "TicketInvalidStateError",
    "TicketNotFoundError",
    "TicketStorageError",
    "TicketValidationError",
    "WorkflowResult",
    "assign_ticket",
    "auto_close_resolved",
    "can_request",
    "cancel_ticket",
    "change_status",
    "claim_ticket",
    "create_ticket",
    "eligible_support_ids",
    "eligible_support_user_ids_query",
    "get_attachment_download",
    "get_description",
    "get_history",
    "get_ticket",
    "has_support_permission",
    "is_support",
    "list_messages",
    "list_my_tickets",
    "list_support_members",
    "list_support_tickets",
    "message_out",
    "post_message",
    "resolve_viewer",
    "ticket_out",
    "update_fields",
]
