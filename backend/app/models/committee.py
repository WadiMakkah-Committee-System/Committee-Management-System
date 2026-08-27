"""
الهدف:
نموذج SQLAlchemy ORM للجنة المعتمدة (Committee) — يطابق بنية
db/migrations/0008_committee_formation.sql. جزء من Phase 1 (Database
Schema + Models فقط) لوحدة "إدارة اللجان" — بدون أي منطق عمل أو API.

المسؤولية:
تمثيل اللجنة الرسمية الناتجة عن اعتماد طلب تشكيل (CommitteeFormationRequest)،
وأعضائها المعتمدين.

ملاحظات تصميم مهمة:
- source_request_id فريد (UNIQUE) — كل طلب ينتج لجنة واحدة على الأكثر،
  وهذا هو مسار التتبّع الوحيد من اللجنة إلى الطلب الأصلي (ولا يوجد عمود
  عكسي على committee_formation_requests تفاديًا لتكرار نفس العلاقة
  باتجاهين — الاستعلام العكسي عبر committee.source_request كافٍ).
- committee_members جدول مستقل تمامًا عن committee_formation_request_members
  (الأعضاء المقترحون بالطلب) — يُملأ مرة واحدة فقط لحظة الاعتماد (Phase 2)
  ولا يُعدَّل بعد ذلك عبر هذه الوحدة؛ عضوية اللجنة المعتمدة نهائية.
- deleted_at (Soft Delete) اتساقًا مع بقية الكيانات الجوهرية بالمشروع
  (departments، users) — لا توجد وظيفة حذف مطلوبة في Phase 1 نفسه، لكن
  العمود مُضاف الآن تفاديًا لـmigration لاحق لمجرد إضافته.
- "الجارية/المنتهية/القادمة" حالة محسوبة من start_date/end_date وقت
  الاستعلام (Phase 2) — لا يوجد عمود status مخزَّن هنا تفاديًا لتكرار
  بيانات قد تصبح غير متزامنة مع التاريخ الفعلي.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, String, Table, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# أعضاء اللجنة المعتمدة — نسخة مقفلة عند الاعتماد، منفصلة عن الأعضاء
# المقترحين بالطلب (committee_formation_request_members في committee_request.py).
committee_members = Table(
    "committee_members",
    Base.metadata,
    Column(
        "committee_id",
        UUID(as_uuid=True),
        ForeignKey("committees.committee_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.user_id"), primary_key=True),
    Column("added_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


class Committee(Base):
    __tablename__ = "committees"

    committee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    source_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("committee_formation_requests.request_id"),
        nullable=False,
        unique=True,
    )

    # رئيس اللجنة المعتمدة — يُنسَخ من committee_formation_requests.chair_user_id
    # لحظة الاعتماد (approve_request)، ولا يُعدَّل بعد ذلك (عضوية اللجنة
    # المعتمدة نهائية، بنفس منطق members أدناه).
    chair_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source_request: Mapped["CommitteeFormationRequest"] = relationship(  # noqa: F821
        back_populates="committee", foreign_keys=[source_request_id]
    )
    chair: Mapped["User | None"] = relationship(foreign_keys=[chair_user_id], lazy="selectin")  # noqa: F821
    members: Mapped[list["User"]] = relationship(secondary=committee_members, lazy="selectin")  # noqa: F821

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def lifecycle_state(self, *, today: date) -> str:
        """
        الحالة الزمنية المحسوبة (upcoming/ongoing/ended) بدل عمود مخزَّن —
        تُستخدم لاحقًا في Phase 2 للتصفية (اللجان الجارية/المنتهية/القادمة).
        """
        if today < self.start_date:
            return "upcoming"
        if today > self.end_date:
            return "ended"
        return "ongoing"
