"""
الهدف:
سجل تغييرات اللجنة الدائمة (migration 0050 — طلب لاما 2026-11-16): كل إضافة
أو حذف عضو، أو تغيير الرئيس/الأمين، أو تمديد فترة اللجنة بعد اعتمادها.

المسؤولية:
تخزين "من غيّر وش ومتى" بشكل دائم، يُعرض داخل صفحة اللجنة كسجل زمني.
الكتابة فقط عبر app/services/committee_membership_service.py.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CommitteeChangeType(str, enum.Enum):
    """أنواع التغيير — تطابق قيد chk_committee_changes_type بقاعدة البيانات."""

    member_added = "member_added"
    member_removed = "member_removed"
    chair_changed = "chair_changed"
    secretary_changed = "secretary_changed"
    period_extended = "period_extended"


class CommitteeChange(Base):
    """
    صف واحد بسجل تغييرات لجنة.

    - subject_user_id: العضو المعني (المُضاف/المحذوف/الرئيس أو الأمين الجديد).
    - previous_user_id: الرئيس/الأمين السابق عند التبديل.
    - details: تفاصيل إضافية (مثال: الفترة قبل وبعد التمديد).
    """

    __tablename__ = "committee_changes"

    change_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    committee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("committees.committee_id", ondelete="CASCADE"), nullable=False
    )
    change_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True
    )
    previous_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True
    )
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # lazy="raise_on_sql": تُحمَّل صراحةً فقط عند عرض السجل (selectinload).
    subject_user: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[subject_user_id], lazy="raise_on_sql"
    )
    previous_user: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[previous_user_id], lazy="raise_on_sql"
    )
    changed_by_user: Mapped["User"] = relationship(  # noqa: F821
        foreign_keys=[changed_by], lazy="raise_on_sql"
    )
