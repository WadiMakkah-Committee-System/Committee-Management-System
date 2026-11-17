"""
الهدف:
نماذج ORM لوحدة "التذاكر" (الدعم الفني) — تطابق db/migrations/0051_tickets.sql
حرفيًا. المتطلبات الكاملة: مواصفات نظام التذاكر (tickets_spec.md بمشروع
"ادارة اللجان").

المسؤولية:
- Ticket: التذكرة (الرقم، النوع، الوحدة، الأولوية، الحالة، الإسناد، التواريخ).
- TicketMessage: رسالة بالمحادثة (رد عام أو ملاحظة داخلية) — الوصف أول رسالة.
- TicketAttachment: مرفق رسالة.

ملاحظات مهمة:
- قيم يولّدها الخادم (trigger أو عمود محسوب): number_year، number_seq،
  ticket_number، last_public_activity_at، updated_at. مُعلَّمة FetchedValue/
  Computed مع eager_defaults=True، فـSQLAlchemy يقرأها بـRETURNING بعد
  INSERT/UPDATE — كائن الـORM ما يصير قديمًا (expire_on_commit=False بهذا
  المشروع، راجعي app/db/session.py).
- العلاقات lazy="raise" عمدًا: كل استعلام بطبقة الخدمة يحدد ما يحمّله
  صراحةً (أسماء المستخدمين فقط)، بدل تحميل User كامل بأدواره وصلاحياته لكل
  رسالة.
- لا علاقة عكسية من User — التذاكر لا تُحمَّل مع المستخدم أبدًا.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    FetchedValue,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TicketStatus(str, enum.Enum):
    """
    الهدف: حالات التذكرة (القسم 4 بالمواصفات). القيم نصية بقاعدة البيانات
    (VARCHAR + CHECK)، فالـEnum هنا للكود فقط.
    """

    new = "new"
    in_progress = "in_progress"
    waiting_on_requester = "waiting_on_requester"
    resolved = "resolved"
    closed = "closed"
    cancelled = "cancelled"


#: الحالات النهائية — للقراءة فقط، وما ينرد عليها (يفرضها trigger بالقاعدة أيضًا).
FINAL_STATUSES = frozenset({TicketStatus.closed, TicketStatus.cancelled})


class TicketType(str, enum.Enum):
    """الهدف: نوع التذكرة (القسم 5 بالمواصفات)."""

    change_request = "change_request"
    bug = "bug"
    inquiry = "inquiry"
    account_access = "account_access"


class TicketModule(str, enum.Enum):
    """الهدف: الوحدة المتأثرة بالمنصة (القسم 5 بالمواصفات)."""

    users_departments = "users_departments"
    committees = "committees"
    meetings = "meetings"
    tasks = "tasks"
    decisions = "decisions"
    documents = "documents"
    minutes = "minutes"
    dashboard = "dashboard"
    other = "other"


class TicketPriority(str, enum.Enum):
    """الهدف: أولوية التذكرة — يحددها الدعم فقط (الافتراضي medium)."""

    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class TicketAuthorSide(str, enum.Enum):
    """الهدف: الصفة اللي كُتبت بها الرسالة — صاحب التذكرة أو الدعم."""

    requester = "requester"
    support = "support"


class Ticket(Base):
    """
    الهدف: صف تذكرة واحدة بجدول tickets.

    الحقول المولَّدة بالخادم (لا تُضبط من الكود):
    - number_year / number_seq: يولّدهما trigger الإدراج من عدّاد السنة.
    - ticket_number: عمود محسوب (TKT-2026-0042).
    - last_public_activity_at: "آخر تحديث" لمقدّم الطلب (رسالة عامة أو تغيير حالة).
    - updated_at: يحدّثه trigger set_updated_at.

    قواعد العمل المفروضة بالقاعدة نفسها (راجعي رأس migration 0051):
    جدول الانتقالات، وربط كل حالة بتاريخها، وقفل المغلقة والملغاة، وثبات
    مقدّم الطلب والرقم والعنوان.
    """

    __tablename__ = "tickets"
    __mapper_args__ = {"eager_defaults": True}

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    number_year: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=FetchedValue())
    number_seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default=FetchedValue())
    ticket_number: Mapped[str] = mapped_column(
        String(20),
        Computed(
            "'TKT-' || number_year::text || '-' "
            "|| lpad(number_seq::text, GREATEST(4, length(number_seq::text)), '0')",
            persisted=True,
        ),
    )

    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    ticket_type: Mapped[str] = mapped_column(String(20), nullable=False)
    module: Mapped[str] = mapped_column(String(30), nullable=False)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, server_default="medium")
    status: Mapped[str] = mapped_column(String(25), nullable=False, server_default="new")
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True
    )

    last_public_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        server_onupdate=FetchedValue(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        server_onupdate=FetchedValue(),
    )

    requester: Mapped["User"] = relationship(foreign_keys=[requester_id], lazy="raise")  # noqa: F821
    assignee: Mapped["User | None"] = relationship(foreign_keys=[assignee_id], lazy="raise")  # noqa: F821


class TicketMessage(Base):
    """
    الهدف: رسالة واحدة بمحادثة التذكرة (لا تُعدَّل ولا تُحذف — trigger بالقاعدة).

    الحقول:
    - author_side: requester (صاحب التذكرة) أو support (عضو الدعم).
    - is_internal: ملاحظة داخلية للدعم فقط — لا تُرجَع أبدًا لغير الدعم.
    - is_description: الوصف (أول رسالة) — واحد بالضبط لكل تذكرة.
    - body_json: محتوى TipTap (يُتحقق منه بالقائمة البيضاء قبل الحفظ).
    - body_text: النص المجرّد من body_json (للطول والبحث والإشعار).
    - client_message_id: معرّف من المتصفح لمنع التكرار عند إعادة المحاولة.
    """

    __tablename__ = "ticket_messages"
    __mapper_args__ = {"eager_defaults": True}

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.ticket_id"), nullable=False
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    author_side: Mapped[str] = mapped_column(String(10), nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_description: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    body_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    client_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    author: Mapped["User"] = relationship(foreign_keys=[author_id], lazy="raise")  # noqa: F821
    attachments: Mapped[list["TicketAttachment"]] = relationship(
        back_populates="message", lazy="raise", order_by="TicketAttachment.created_at"
    )


class TicketAttachment(Base):
    """
    الهدف: مرفق رسالة (PNG/JPG/PDF/DOCX/XLSX، 5 كحد أقصى لكل رسالة).

    ملاحظات:
    - الرافع = كاتب الرسالة (ما فيه عمود منفصل).
    - الظهور يتبع الرسالة: مرفق ملاحظة داخلية للدعم فقط.
    - التنزيل دائمًا عبر الباك إند بعد فحص الصلاحية (لا روابط تخزين مباشرة).
    """

    __tablename__ = "ticket_attachments"
    __mapper_args__ = {"eager_defaults": True}

    attachment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ticket_messages.message_id"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    message: Mapped[TicketMessage] = relationship(back_populates="attachments", lazy="raise")
