"""
الهدف:
نموذج SQLAlchemy ORM لجدول password_reset_tokens — يطابق تمامًا بنية الجدول
الحقيقي في db/migrations/0005_create_password_reset_tokens.sql.

المسؤولية:
تمثيل رمز OTP واحد لاسترجاع كلمة المرور (FR-UM-018) — لا يُخزَّن الرمز
كنص صريح أبدًا، فقط hash له (نفس منطق كلمة المرور: bcrypt عبر
core.security).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    otp_code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    @property
    def is_expired(self) -> bool:
        from datetime import timezone as _tz

        return self.expires_at < datetime.now(_tz.utc)
