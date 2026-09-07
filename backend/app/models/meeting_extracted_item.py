"""
الهدف:
نموذج SQLAlchemy ORM لـ"البنود المستخرجة من الاجتماع" (FR-TASK-005 إلى
FR-TASK-012 + FR-DEC-001 إلى FR-DEC-004، §4.2/§5.2 SRS) — قائمة بنود
عامة (نص فقط، بدون تصنيف مسبق) يستخرجها الذكاء الاصطناعي من ملخص
الاجتماع بناءً على طلب رئيس اللجنة، ثم يقوم رئيس اللجنة يدويًا إما
بحذف كل بند أو "تعيينه" كـ"مهمة" (ينشئ Task حقيقي عبر task_service)
أو "قرار" (ينشئ Decision حقيقي عبر decision_service، مربوطًا بالاجتماع
المصدر). راجعي db/migrations/0028_meeting_extracted_items.sql ورأس
app/services/meeting_service.py (extract_meeting_items وما حولها)
للتصميم الكامل.

قرار تصميم: الجدول لا يخزّن بيانات المهمة/القرار نفسها (تاريخ/مسؤول/
تصنيف) — فقط نص البند + حالته + مرجع (linked_task_id/linked_decision_id)
للسجل الفعلي بعد "التعيين". هذا يطابق SRS حرفيًا (UC8/FR-DEC-005: بيانات
المهمة/القرار تُدخَل يدويًا برئيس اللجنة بنفس نموذج الإنشاء العادي، الذكاء
الاصطناعي يقترح فقط نص العنوان)، ويتفادى ازدواج منطق التحقق (تواريخ/
عضوية) الموجود أصلًا بـtask_service/decision_service.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MeetingExtractedItemStatus(str, enum.Enum):
    pending = "pending"                    # بانتظار قرار رئيس اللجنة (تعيين/حذف)
    assigned_task = "assigned_task"        # حُوِّل إلى مهمة فعلية (linked_task_id)
    assigned_decision = "assigned_decision"  # حُوِّل إلى قرار فعلي (linked_decision_id)


class MeetingExtractedItem(Base):
    __tablename__ = "meeting_extracted_items"

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.meeting_id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # 'ai' (مستخرج بالذكاء الاصطناعي، FR-TASK-005/UC2) أو 'manual' (أضافه
    # رئيس اللجنة يدويًا، FR-TASK-007/UC4) — قيمة نصية بسيطة، بدون Enum
    # مخصّص (قيمتان ثابتتان فقط، لا حاجة موثّقة لتوسّعها).
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="ai")

    status: Mapped[MeetingExtractedItemStatus] = mapped_column(
        SAEnum(MeetingExtractedItemStatus, name="meeting_extracted_item_status", native_enum=True),
        nullable=False,
        server_default=MeetingExtractedItemStatus.pending.value,
    )

    linked_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.task_id", ondelete="SET NULL"), nullable=True
    )
    linked_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.decision_id", ondelete="SET NULL"), nullable=True
    )

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    creator: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821
