"""
الهدف:
نموذج SQLAlchemy ORM لجدول users — يطابق تمامًا بنية الجدول الحقيقي في
db/migrations/0003_create_users.sql (تم التحقق عبر Supabase MCP list_tables
على القاعدة الفعلية).

المسؤولية:
تمثيل صف واحد من جدول users، بما في ذلك الأدوار العامة (user_role)، حالة
الحساب (user_status)، وحقول الأمان (failed_login_attempts, locked_until,
must_change_password).

ملاحظات أمنية:
- password_hash يُخزَّن كـ bcrypt hash فقط — لا يوجد أي حقل لكلمة مرور نصية.
- الأدوار هنا (user_role) هي الأدوار العامة على مستوى النظام فقط. أدوار
  اللجان (رئيس/عضو/مطلع/بديل) Scoped لكل لجنة وتُصمَّم لاحقًا مع جدول
  اللجان — لا علاقة لها بهذا الحقل.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(str, enum.Enum):
    super_admin = "super_admin"
    admin = "admin"
    executive_president = "executive_president"
    executive_office_manager = "executive_office_manager"
    executive_office_secretary = "executive_office_secretary"


class UserStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    username: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", native_enum=True), nullable=False
    )
    dep_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.dep_id"), nullable=True
    )

    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, name="user_status", native_enum=True),
        nullable=False,
        server_default=UserStatus.active.value,
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    failed_login_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    department: Mapped["Department | None"] = relationship(back_populates="users")  # noqa: F821

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.middle_name} {self.last_name}"

    @property
    def is_locked(self) -> bool:
        """هل الحساب مقفل حاليًا بسبب محاولات دخول فاشلة (FR-UM-019)؟"""
        return self.locked_until is not None and self.locked_until > datetime.now(
            self.locked_until.tzinfo
        )
