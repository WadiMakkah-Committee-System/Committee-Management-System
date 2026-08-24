"""
الهدف:
نموذج SQLAlchemy ORM لطلب تشكيل اللجنة (Committee Formation Request) —
يطابق بنية db/migrations/0008_committee_formation.sql. هذا هو Phase 1
(تحليل + Database Schema + Models) من وحدة "إدارة اللجان" فقط — لا يوجد
هنا أي منطق عمل (Business Logic) أو راوتات API؛ تلك مسؤولية Phase 2.

المسؤولية:
تمثيل دورة حياة طلب تشكيل اللجنة (مسودة → إرسال → مراجعة → إعادة/رفع
للاعتماد → موافقة/رفض)، والأعضاء المقترحين بالطلب قبل اعتماده.

ملاحظات تصميم مهمة:
- الحالات (CommitteeRequestStatus) تطابق حرفيًا committee_request_status
  في قاعدة البيانات — أي تعديل عليها يتطلب migration جديد بالاثنين معًا.
- لا يوجد جدول Status History مستقل هنا عمدًا — audit_logs (الموجود
  مسبقًا) يُستخدم لتسجيل كل انتقال حالة (target_type =
  'committee_formation_request')، تفاديًا لتكرار نفس الغرض بجدول جديد.
  هذا يُنفَّذ في طبقة الخدمة بـ Phase 2، وليس في هذا الملف.
- الأعضاء المقترحون (proposed_members) منفصلون تمامًا عن أعضاء اللجنة
  المعتمدة (committee_members في committee.py) — عضوية اللجنة تُقفل
  نهائيًا عند الاعتماد ولا تُشتق أو تُزامَن تلقائيًا مع هذه القائمة بعد
  ذلك؛ تُنسَخ مرة واحدة فقط لحظة الموافقة (Phase 2).
- التحقق من صلاحية المستخدم (committees.request.create/view/update/
  escalate/approve) مسؤولية RBAC في core/dependencies.py عبر
  require_permission(...) الموجودة أصلًا — لا علاقة لهذا الملف بذلك.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, String, Table, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CommitteeRequestStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    under_review = "under_review"
    returned = "returned"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"


# الأعضاء المقترحون بالطلب — جدول وسيط بسيط (request_id, user_id)، بنفس
# نمط role_permissions في role.py. قابل للتعديل فقط أثناء draft/returned
# (تُفرض هذه القاعدة في الخدمة، Phase 2 — ليست قيدًا بقاعدة البيانات).
committee_formation_request_members = Table(
    "committee_formation_request_members",
    Base.metadata,
    Column(
        "request_id",
        UUID(as_uuid=True),
        ForeignKey("committee_formation_requests.request_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.user_id"), primary_key=True),
    Column("added_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


class CommitteeFormationRequest(Base):
    __tablename__ = "committee_formation_requests"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    committee_name: Mapped[str] = mapped_column(String(200), nullable=False)
    statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[CommitteeRequestStatus] = mapped_column(
        SAEnum(CommitteeRequestStatus, name="committee_request_status", native_enum=True),
        nullable=False,
        server_default=CommitteeRequestStatus.draft.value,
    )

    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    return_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    requester: Mapped["User"] = relationship(foreign_keys=[requested_by], lazy="selectin")  # noqa: F821
    proposed_members: Mapped[list["User"]] = relationship(  # noqa: F821
        secondary=committee_formation_request_members, lazy="selectin"
    )
    committee: Mapped["Committee | None"] = relationship(  # noqa: F821
        back_populates="source_request", uselist=False
    )

    @property
    def is_editable(self) -> bool:
        """مسودة أو معادة للتعديل فقط — تُستخدم لاحقًا في Phase 2 كتحقق سريع."""
        return self.status in (CommitteeRequestStatus.draft, CommitteeRequestStatus.returned)

    @property
    def is_final(self) -> bool:
        """حالة نهائية لا يوجد بعدها أي انتقال (Approved/Rejected)."""
        return self.status in (CommitteeRequestStatus.approved, CommitteeRequestStatus.rejected)
