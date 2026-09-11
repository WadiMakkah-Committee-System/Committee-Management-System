"""
الهدف:
تجميع كل نماذج ORM في مكان واحد يسهل استيراده (import) منه، ولضمان أن
SQLAlchemy يكتشف كل النماذج والعلاقات بينها عند تحميل app.db.base.Base.
"""

from app.models.audit_log import AuditAction, AuditLog
from app.models.committee import Committee
from app.models.committee_request import CommitteeFormationRequest, CommitteeRequestStatus
from app.models.decision import (
    Decision,
    DecisionClassification,
    DecisionStatus,
    DecisionVote,
    DecisionVoteOption,
)
from app.models.department import Department
from app.models.job_title import JobTitle
from app.models.meeting import Meeting, MeetingAgendaItem, MeetingMode, MeetingStatus
from app.models.meeting_chat import MeetingChatMessage
from app.models.document_chat import DocumentChatConversation, DocumentChatMessage
from app.models.meeting_draft import MeetingDraft, MeetingDraftStatus, MeetingRecording
from app.models.meeting_extracted_item import MeetingExtractedItem, MeetingExtractedItemStatus
from app.models.meeting_minutes import (
    MeetingMinutes,
    MeetingMinutesReviewer,
    MeetingMinutesReviewStatus,
    MeetingMinutesSignature,
    MeetingMinutesStage,
)
from app.models.notification import Notification
from app.models.password_reset_token import PasswordResetToken
from app.models.role import Permission, Role
from app.models.task import Task, TaskAssignmentHistory, TaskStatus
from app.models.user import User, UserStatus

__all__ = [
    "AuditAction",
    "AuditLog",
    "Committee",
    "CommitteeFormationRequest",
    "CommitteeRequestStatus",
    "Decision",
    "DecisionClassification",
    "DecisionStatus",
    "DecisionVote",
    "DecisionVoteOption",
    "Department",
    "JobTitle",
    "Meeting",
    "MeetingAgendaItem",
    "MeetingChatMessage",
    "DocumentChatConversation",
    "DocumentChatMessage",
    "MeetingDraft",
    "MeetingDraftStatus",
    "MeetingExtractedItem",
    "MeetingExtractedItemStatus",
    "MeetingMinutes",
    "MeetingMinutesReviewer",
    "MeetingMinutesReviewStatus",
    "MeetingMinutesSignature",
    "MeetingMinutesStage",
    "MeetingMode",
    "MeetingRecording",
    "MeetingStatus",
    "Notification",
    "PasswordResetToken",
    "Permission",
    "Role",
    "Task",
    "TaskAssignmentHistory",
    "TaskStatus",
    "User",
    "UserStatus",
]
