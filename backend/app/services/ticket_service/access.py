"""
الهدف:
فحوصات الصلاحية الخاصة بالتذاكر — نقطة واحدة لكل قواعد "مين يقدر يسوي وش"
بدل تكرارها بكل عملية (القسم 6 بالمواصفات).

قواعد العمل:
- tickets.create: مقدّم الطلب — دائمًا على تذاكره هو فقط، مهما كان النطاق
  المحفوظ للدور (own أو all، الشاشة تحفظ all افتراضيًا).
- خانات الدعم (view_all/reply/internal_notes/manage/assign): تشتغل بنطاق
  "all" فقط، وكل وحدة منها تحتاج معها tickets.view_all. أي نطاق ثاني =
  كأنه غير ممنوح (القسم 6.2).
- الصلاحيات من الدور الحالي فقط (User.scope_for → user.role) — مطابق
  لمبدّل الأدوار (migration 0046).
- ضيوف الاجتماعات خارج التذاكر تمامًا (والقاعدة ترفضهم أيضًا).

الاعتماديات: User.scope_for (app/models/user.py)، وجداول الأدوار للاستعلام
عن أعضاء الدعم المؤهلين.
"""

import uuid
from typing import Literal

from sqlalchemy import Select, select

from app.models.role import Permission, RolePermission
from app.models.ticket import FINAL_STATUSES, Ticket, TicketStatus
from app.models.user import User, UserStatus
from app.models.user_role import UserRole
from app.services.ticket_service.codes import (
    TICKETS_ASSIGN,
    TICKETS_CREATE,
    TICKETS_INTERNAL_NOTES,
    TICKETS_MANAGE,
    TICKETS_REPLY,
    TICKETS_VIEW_ALL,
)
from app.services.ticket_service.errors import TicketForbiddenError, TicketNotFoundError

Viewer = Literal["requester", "support"]

#: نطاق الدعم الوحيد المقبول (القسم 6.2 بالمواصفات).
_SUPPORT_SCOPE = "all"


def can_request(actor: User) -> bool:
    """
    الهدف: هل المستخدم يقدر يرسل تذاكر ويتابع تذاكره (tickets.create)؟

    المدخلات: actor — المستخدم الحالي (دوره الحالي محمَّل مع صلاحياته).
    المخرجات: True لو دوره الحالي يملك tickets.create بأي نطاق، وليس ضيفًا.
    بلا تأثيرات جانبية.
    """
    return not actor.is_guest and actor.scope_for(TICKETS_CREATE) is not None


def is_support(actor: User) -> bool:
    """
    الهدف: هل المستخدم عضو دعم فعّال الآن (tickets.view_all بنطاق "all")؟
    المخرجات: bool. بلا تأثيرات جانبية.
    """
    return not actor.is_guest and actor.scope_for(TICKETS_VIEW_ALL) == _SUPPORT_SCOPE


def has_support_permission(actor: User, code: str) -> bool:
    """
    الهدف: هل عضو الدعم يملك خانة دعم معيّنة (رد/ملاحظات/إدارة/إسناد)؟

    المدخلات:
    - actor: المستخدم الحالي.
    - code: كود الخانة (مثال: tickets.reply).

    المخرجات: True فقط لو يملك الخانة بنطاق "all" ومعها tickets.view_all
    بنطاق "all" (القسم 6.2 — بدون عرض الكل، الخانات ما تشتغل).
    """
    return is_support(actor) and actor.scope_for(code) == _SUPPORT_SCOPE


def require_requester(actor: User) -> None:
    """
    الهدف: إيقاف أي عملية مقدّم طلب لمن ما يملك tickets.create.
    الأخطاء: TicketForbiddenError (403).
    """
    if not can_request(actor):
        raise TicketForbiddenError("ليست لديك صلاحية إرسال التذاكر ومتابعتها")


def require_support(actor: User, code: str = TICKETS_VIEW_ALL) -> None:
    """
    الهدف: إيقاف أي عملية دعم لمن ما يملك الخانة المطلوبة (بنطاق "all").

    المدخلات: actor، وcode (الافتراضي tickets.view_all).
    الأخطاء: TicketForbiddenError (403).
    """
    if not has_support_permission(actor, code):
        raise TicketForbiddenError("ليست لديك صلاحية لهذا الإجراء على التذاكر")


def resolve_viewer(actor: User, ticket: Ticket) -> Viewer:
    """
    الهدف: بأي صفة يشوف المستخدم هذه التذكرة؟

    قواعد العمل:
    - عضو الدعم (view_all بنطاق all) → "support"، حتى لو كان هو صاحب التذكرة
      (حالة خاصة موثقة بالقسم 10: يشوف الملاحظات الداخلية عليها).
    - صاحب التذكرة اللي يملك tickets.create → "requester".
    - صاحب التذكرة بدون tickets.create (انسحبت منه أو بدّل دوره) → 403.
    - أي أحد ثاني → 404 (ما ينكشف وجود التذكرة).

    المخرجات: "support" أو "requester".
    الأخطاء: TicketForbiddenError (403)، TicketNotFoundError (404).
    """
    if is_support(actor):
        return "support"
    if ticket.requester_id == actor.user_id:
        if can_request(actor):
            return "requester"
        raise TicketForbiddenError("ليست لديك صلاحية متابعة التذاكر بدورك الحالي")
    raise TicketNotFoundError("التذكرة غير موجودة")


def viewer_actions(actor: User, ticket: Ticket, viewer: Viewer) -> dict[str, bool]:
    """
    الهدف: الأزرار المتاحة للمشاهد الحالي على التذكرة (تُرجع مع كل تذكرة).

    قواعد العمل:
    - المغلقة والملغاة: لا شيء متاح.
    - الإلغاء لصاحب التذكرة فقط وهي "جديدة".
    - الرد: لصاحب التذكرة، أو لعضو دعم يملك tickets.reply.

    المخرجات: قاموس يطابق TicketViewerActionsOut. بلا تأثيرات جانبية.
    """
    is_open = TicketStatus(ticket.status) not in FINAL_STATUSES
    is_owner = ticket.requester_id == actor.user_id and can_request(actor)
    support = viewer == "support"
    return {
        "can_reply": is_open and (is_owner or (support and has_support_permission(actor, TICKETS_REPLY))),
        "can_add_internal_note": is_open and support and has_support_permission(actor, TICKETS_INTERNAL_NOTES),
        "can_cancel": is_owner and ticket.status == TicketStatus.new.value,
        "can_manage": is_open and support and has_support_permission(actor, TICKETS_MANAGE),
        "can_assign": is_open and support and has_support_permission(actor, TICKETS_ASSIGN),
    }


def eligible_support_user_ids_query() -> Select[tuple[uuid.UUID]]:
    """
    الهدف: استعلام معرّفات أعضاء الدعم المؤهلين (للإسناد والإشعارات).

    قواعد العمل:
    - يملك tickets.view_all بنطاق "all" عبر **أي** من أدواره المسندة
      (user_roles) — نفس منطق الإشعارات الجماعية الحالية (migration 0046):
      الإشعار يوصله حتى لو دوره الحالي غير "دعم فني".
    - مستخدم نشِط، غير محذوف، وليس ضيفًا.

    المخرجات: Select يرجع user_id (DISTINCT) — يُستخدم كاستعلام فرعي أو يُنفَّذ.
    بلا تأثيرات جانبية (لا ينفّذ شيئًا بنفسه).
    """
    return (
        select(User.user_id)
        .join(UserRole, UserRole.user_id == User.user_id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(
            Permission.code == TICKETS_VIEW_ALL,
            RolePermission.scope == _SUPPORT_SCOPE,
            User.deleted_at.is_(None),
            User.status == UserStatus.active,
            User.is_guest.is_(False),
        )
        .distinct()
    )
