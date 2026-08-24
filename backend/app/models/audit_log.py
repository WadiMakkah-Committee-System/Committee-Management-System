"""
الهدف:
نموذج SQLAlchemy ORM لجدول audit_logs — يطابق تمامًا بنية الجدول الحقيقي في
db/migrations/0004_create_audit_logs.sql.

المسؤولية:
تمثيل سجل تدقيق واحد (من نفّذ العملية، نوعها، على أي كيان، ومتى) — جدول
Append-only بالكامل، لا يوجد أي منطق تعديل أو حذف عليه في التطبيق.

ملاحظات:
- target_type + target_id بشكل عام (نص + UUID) وليس Foreign Key مباشر،
  عشان يصلح لتسجيل أي كيان مستقبلي (لجان، اجتماعات، قرارات...) بدون تعديل
  بنية الجدول لاحقًا.
- actor_user_id قابل لأن يكون NULL (مثلًا: عمليات نظامية تلقائية).
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AuditAction(str, enum.Enum):
    create = "create"
    update = "update"
    delete = "delete"
    suspend = "suspend"
    reactivate = "reactivate"
    # انتقالات حالة طلب تشكيل اللجنة (Phase 2 — committee_service.py) —
    # أُضيفت بدل إعادة استخدام "update" العام، لأن لكل منها دلالة عمل
    # مختلفة يهم تتبعها في سجل التدقيق (من أرسل/رفع/اعتمد/رفض الطلب).
    # مطابقة تمامًا لقيم enum "audit_action" بعد db/migrations/0009.
    submit = "submit"
    escalate = "escalate"
    approve = "approve"
    reject = "reject"
    returned = "returned"  # ليس "return" (كلمة محجوزة بلغة Python) — راجعي db/migrations/0010


class AuditLog(Base):
    __tablename__ = "audit_logs"

    log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True
    )
    action_type: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, name="audit_action", native_enum=True), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # علاقة أحادية الاتجاه فقط للقراءة (اسم من نفّذ العملية) — بدون
    # back_populates لأن User لا يحتاج قائمة سجلات التدقيق الخاصة به.
    actor: Mapped["User | None"] = relationship(lazy="selectin", foreign_keys=[actor_user_id])  # noqa: F821
