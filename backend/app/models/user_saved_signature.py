"""
الهدف:
نموذج ORM لجدول user_saved_signatures (migration 0049) — التوقيع المحفوظ لكل
مستخدم، يُستخدم للتوقيع على المحاضر بدل رسمه كل مرة (القالب العام للمحاضر —
راجعي docs/minutes-official-template.md).

ملاحظات:
- جدول مستقل (وليس عمودًا في users) لأن الصورة كبيرة وصفوف users تُحمَّل
  تلقائيًا في أغلب المسارات — هذا الجدول لا يُقرأ إلا عند الحاجة.
- لا توجد علاقة (relationship) من User إليه عمدًا، حتى لا يُحمَّل مع المستخدم.
- القراءة والكتابة لصاحب التوقيع فقط — تُفرض في user_signature_service.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserSavedSignature(Base):
    """
    الهدف: صف التوقيع المحفوظ لمستخدم واحد (صف واحد كحد أقصى لكل مستخدم).

    الحقول:
    - user_id: صاحب التوقيع (المفتاح الأساسي نفسه — يضمن صفًا واحدًا فقط).
    - signature_image: صورة PNG بصيغة data URL (نفس صيغة توقيع المحضر).
    - created_at / updated_at: updated_at يتحدّث بـtrigger في القاعدة.
    """

    __tablename__ = "user_saved_signatures"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    signature_image: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
