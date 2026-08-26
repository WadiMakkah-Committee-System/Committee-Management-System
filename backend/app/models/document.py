"""
الهدف:
نماذج SQLAlchemy ORM لوحدة "إدارة الوثائق" - تطابق بنية الجداول الفعلية
في db/migrations/0012_documents_schema.sql (تم التحقق عبر Supabase MCP
list_tables على القاعدة الفعلية).

المسؤولية:
- DocumentCategory: تصنيفات الوثائق (عامة على مستوى الشركة، أو خاصة
  بإدارة معينة).
- Document: الوثيقة نفسها - بيانات وصفية فقط؛ الملف الفعلي يُخزَّن خارج
  قاعدة البيانات (Supabase Storage) ويُشار إليه عبر storage_path.
- DocumentLink: جدول ربط عام (Polymorphic) لربط الوثائق مستقبلًا بأي
  كيان آخر (لجنة/اجتماع/مهمة/قرار) دون الحاجة لتعديل المخطط لاحقًا -
  جاهز في القاعدة، غير مُستخدم من أي API في هذه المرحلة.
- جداول ربط (Many-to-Many) لتحديد ظهور الوثيقة: إدارات محددة / لجان
  محددة / مستخدمون محددون - قابلة للدمج مع is_public في نفس الوقت.

ملاحظات تصميم مهمة:
- content_tsv عمود GENERATED (tsvector) محسوب داخل قاعدة البيانات فقط
  ولا يُكتب إليه من كود بايثون أبدًا - لذلك غير معيَّن هنا عمدًا.
- embedding (pgvector) مُجهَّز في قاعدة البيانات لمرحلة البحث الدلالي
  القادمة عبر Gemini API - غير معيَّن هنا عمدًا لتفادي إضافة حزمة
  بايثون (pgvector) غير مستخدمة في هذه المرحلة. سيُضاف عند البدء الفعلي
  بمرحلة البحث الذكي.
- Soft Delete عبر deleted_at (NULLABLE) اتساقًا مع بقية الكيانات
  الجوهرية بالمشروع (departments, users, committees).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DocumentStatus(str, enum.Enum):
    active = "active"
    archived = "archived"


class DocumentCategoryScope(str, enum.Enum):
    global_ = "global"
    department = "department"


# ظهور الوثيقة لإدارات محددة (قابل للدمج مع is_public واللجان والمستخدمين)
document_visibility_departments = Table(
    "document_visibility_departments",
    Base.metadata,
    Column(
        "document_id",
        UUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "department_id",
        UUID(as_uuid=True),
        ForeignKey("departments.dep_id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

# ظهور الوثيقة للجان محددة
document_visibility_committees = Table(
    "document_visibility_committees",
    Base.metadata,
    Column(
        "document_id",
        UUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "committee_id",
        UUID(as_uuid=True),
        ForeignKey("committees.committee_id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

# ظهور الوثيقة لمستخدمين محددين
document_visibility_users = Table(
    "document_visibility_users",
    Base.metadata,
    Column(
        "document_id",
        UUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class DocumentCategory(Base):
    __tablename__ = "document_categories"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'global' AND department_id IS NULL) OR "
            "(scope = 'department' AND department_id IS NOT NULL)",
            name="document_categories_scope_department_check",
        ),
    )

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    scope: Mapped[DocumentCategoryScope] = mapped_column(
        SAEnum(DocumentCategoryScope, name="document_category_scope", native_enum=True),
        nullable=False,
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.dep_id"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    department: Mapped["Department | None"] = relationship(lazy="selectin")  # noqa: F821
    creator: Mapped["User"] = relationship(foreign_keys=[created_by], lazy="selectin")  # noqa: F821
    documents: Mapped[list["Document"]] = relationship(back_populates="category")

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class Document(Base):
    __tablename__ = "documents"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_categories.category_id"), nullable=True
    )
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus, name="document_status", native_enum=True),
        nullable=False,
        server_default=DocumentStatus.active.value,
    )
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # content_tsv (tsvector, GENERATED) و embedding (vector) غير معيَّنين
    # هنا عمدًا - راجع docstring أعلى الملف.

    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    category: Mapped["DocumentCategory | None"] = relationship(
        back_populates="documents", lazy="selectin"
    )
    uploader: Mapped["User"] = relationship(foreign_keys=[uploaded_by], lazy="selectin")  # noqa: F821

    visible_departments: Mapped[list["Department"]] = relationship(  # noqa: F821
        secondary=document_visibility_departments, lazy="selectin"
    )
    visible_committees: Mapped[list["Committee"]] = relationship(  # noqa: F821
        secondary=document_visibility_committees, lazy="selectin"
    )
    visible_users: Mapped[list["User"]] = relationship(  # noqa: F821
        secondary=document_visibility_users, lazy="selectin"
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class DocumentLink(Base):
    """
    جدول ربط عام (Polymorphic) - جاهز في القاعدة لربط الوثائق مستقبلًا
    بأي كيان (لجنة/اجتماع/مهمة/قرار) دون الحاجة لتعديل المخطط لاحقًا.
    غير مُستخدم من أي API في هذه المرحلة.
    """

    __tablename__ = "document_links"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    linked_entity_type: Mapped[str] = mapped_column(String(50), primary_key=True)
    linked_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    linked_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped["Document"] = relationship()
