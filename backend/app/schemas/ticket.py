"""
الهدف:
Pydantic Schemas لوحدة "التذاكر" (الدعم الفني). راجعي رأس
db/migrations/0051_tickets.sql ومواصفات tickets_spec.md.

ملاحظات:
- مخرجات التذكرة واحدة (TicketOut) للطرفين، لكن الحقول الخاصة بالدعم
  (الأولوية، بريد مقدّم الطلب، حالة عضو الدعم المسند) تُرجع None لمقدّم
  الطلب — تبنيها طبقة الخدمة حسب صفة المشاهد (viewer).
- إنشاء التذكرة والرد عليها multipart/form-data (بسبب المرفقات)، فمدخلاتهما
  تُقرأ كحقول Form بالراوت، وليست Schemas هنا.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.ticket import TicketModule, TicketPriority, TicketType

#: الحالات اللي يقدر الدعم يحدّدها يدويًا أو بعد الرد (القسم 4 بالمواصفات).
#: new يتغير تلقائيًا بالاستلام، وclosed بالمجدول، وcancelled لمقدّم الطلب.
SupportSettableStatus = Literal["in_progress", "waiting_on_requester", "resolved"]


class TicketPersonOut(BaseModel):
    """
    الهدف: اسم مستخدم مختصر داخل التذكرة (مقدّم الطلب، المسند إليه، كاتب الرسالة).
    email يظهر للدعم فقط (None لمقدّم الطلب).
    """

    user_id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None = None


class TicketViewerActionsOut(BaseModel):
    """
    الهدف: وش يقدر المشاهد الحالي يسوي على هذه التذكرة الآن — تحسبها طبقة
    الخدمة من الصلاحيات والحالة، فالواجهة تعرض الأزرار الصحيحة بدون تكرار
    قواعد العمل. الأمان نفسه يبقى بالباك إند لكل عملية.
    """

    can_reply: bool
    can_add_internal_note: bool
    can_cancel: bool
    can_manage: bool
    can_assign: bool


class TicketOut(BaseModel):
    """
    الهدف: تمثيل تذكرة للقائمة والتفاصيل.

    viewer: "requester" أو "support" — صفة المشاهد اللي بُنيت عليها الاستجابة.
    الحقول الخاصة بالدعم None لمقدّم الطلب: priority، assignee_is_active_support.
    """

    ticket_id: uuid.UUID
    ticket_number: str
    title: str
    ticket_type: TicketType
    module: TicketModule
    status: str
    priority: TicketPriority | None
    requester: TicketPersonOut
    assignee: TicketPersonOut | None
    assignee_is_active_support: bool | None
    created_at: datetime
    updated_at: datetime
    last_public_activity_at: datetime
    resolved_at: datetime | None
    closed_at: datetime | None
    cancelled_at: datetime | None
    viewer: Literal["requester", "support"]
    actions: TicketViewerActionsOut


class TicketPageOut(BaseModel):
    """الهدف: صفحة من قائمة تذاكر (نفس نمط AuditLogPageOut)."""

    items: list[TicketOut]
    total: int
    limit: int
    offset: int


class TicketAttachmentOut(BaseModel):
    """الهدف: بيانات مرفق رسالة (التنزيل عبر مسار منفصل يتحقق من الصلاحية)."""

    model_config = ConfigDict(from_attributes=True)

    attachment_id: uuid.UUID
    file_name: str
    mime_type: str
    file_size_bytes: int


class TicketMessageOut(BaseModel):
    """
    الهدف: رسالة بمحادثة التذكرة.
    body_json: محتوى TipTap (تعرضه الواجهة بـTipTap للقراءة، بدون HTML خام).
    """

    message_id: uuid.UUID
    ticket_id: uuid.UUID
    author: TicketPersonOut
    author_side: Literal["requester", "support"]
    is_internal: bool
    is_description: bool
    body_json: dict[str, Any]
    client_message_id: uuid.UUID | None
    created_at: datetime
    attachments: list[TicketAttachmentOut]


class TicketMessagePostOut(BaseModel):
    """
    الهدف: نتيجة إرسال رسالة — الرسالة نفسها + التذكرة بعد أي تغيير حالة
    (إعادة فتح، أو الحالة اللي اختارها الدعم مع الرد).
    """

    message: TicketMessageOut
    ticket: TicketOut


class TicketStatusUpdate(BaseModel):
    """الهدف: تغيير الحالة يدويًا من الدعم (tickets.manage)."""

    status: SupportSettableStatus


class TicketAssign(BaseModel):
    """الهدف: إسناد التذكرة لعضو دعم آخر (tickets.assign)."""

    assignee_id: uuid.UUID


class TicketFieldsUpdate(BaseModel):
    """
    الهدف: تعديل الأولوية والنوع والوحدة (tickets.manage).
    العنوان ما يتعدّل بعد الإرسال (قرار 2026-11-17) — فما هو هنا أصلًا.
    """

    priority: TicketPriority | None = None
    ticket_type: TicketType | None = None
    module: TicketModule | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "TicketFieldsUpdate":
        if self.priority is None and self.ticket_type is None and self.module is None:
            raise ValueError("حدّد حقلًا واحدًا على الأقل للتعديل")
        return self


class TicketHistoryEntryOut(BaseModel):
    """
    الهدف: حدث واحد بسجل التذكرة (TKT-FR-017) — مقروء من audit_logs.

    event: created | status_changed | assigned | priority_changed |
    type_changed | module_changed. الإلغاء وإعادة الفتح والإغلاق التلقائي
    تظهر كـstatus_changed (من/إلى).
    actor: None للعمليات التلقائية (الإغلاق بالمجدول).
    """

    event: str
    from_value: str | None
    to_value: str | None
    actor: TicketPersonOut | None
    created_at: datetime


class TicketSupportMemberOut(BaseModel):
    """الهدف: عضو دعم يقدر يُسند له (يملك tickets.view_all بنطاق "الكل")."""

    user_id: uuid.UUID
    first_name: str
    last_name: str
    email: str
