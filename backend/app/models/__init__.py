"""
الهدف:
تجميع كل نماذج ORM في مكان واحد يسهل استيراده (import) منه، ولضمان أن
SQLAlchemy يكتشف كل النماذج والعلاقات بينها عند تحميل app.db.base.Base.
"""

from app.models.audit_log import AuditAction, AuditLog
from app.models.department import Department
from app.models.password_reset_token import PasswordResetToken
from app.models.role import Permission, Role
from app.models.user import User, UserStatus

__all__ = [
    "AuditAction",
    "AuditLog",
    "Department",
    "PasswordResetToken",
    "Permission",
    "Role",
    "User",
    "UserStatus",
]
