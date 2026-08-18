"""
الهدف:
توفير القاعدة المشتركة (Declarative Base) لكل نماذج SQLAlchemy ORM في
المشروع، عشان Alembic/الأدوات المستقبلية تقدر تكتشف كل النماذج من مكان واحد.

المسؤولية:
تعريف Base فقط — لا يحتوي أي منطق آخر عمدًا.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """القاعدة المشتركة لكل نماذج ORM (departments, users, audit_logs, ...)."""

    pass
