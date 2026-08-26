"""
الهدف:
نموذج SQLAlchemy ORM لجدول job_titles — يطابق بنية
db/migrations/0011_job_titles.sql.

المسؤولية:
تمثيل صف واحد من جدول المسميات الوظيفية. وحدة مستقلة تمامًا عن جدول
roles (قرار عمل موثّق: المسمى الوظيفي ليس إعادة استخدام لاسم الدور).

ملاحظات:
- لا يوجد Soft Delete هنا (بعكس departments) — الحذف فعلي (DELETE)، مع
  حارس بمستوى الخدمة (job_title_service) يمنع حذف مسمى قيد الاستخدام.
- التفرد على name (case-insensitive) مفروض عبر uq_job_titles_name
  بقاعدة البيانات، وليس عبر SQLAlchemy.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JobTitle(Base):
    __tablename__ = "job_titles"

    job_title_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
