"""
الهدف:
تجميع كل نماذج ORM في مكان واحد يسهل استيراده (import) منه، ولضمان أن
SQLAlchemy يكتشف كل النماذج والعلاقات بينها عند تحميل app.db.base.Base.
"""

from app.models.audit_log import AuditAction, AuditLog
from app.models.committee import Committee
from app.models.committee_request import CommitteeFormationRequest, CommitteeRequestStatus
from app.models.department import Department
from app.models.password_reset_token import PasswordResetToken
from app.models.role import Permission, Role
from app.models.user import User, UserStatus

__all__ = [
    "AuditAction",
    "AuditLog",
    "Committee",
    "CommitteeFormationRequest",
    "CommitteeRequestStatus",
    "Department",
    "PasswordResetToken",
    "Permission",
    "Role",
    "User",
    "UserStatus",
]
