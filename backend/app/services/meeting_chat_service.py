"""
الهدف:
منطق العمل لـ"محادثة الاجتماع" — راجعي رأس
db/migrations/0026_meeting_realtime.sql للتصميم الكامل. التفويض: نفس
صلاحية الانضمام للاجتماع (meetings.join) بالضبط — لا صلاحية منفصلة
للمحادثة (قرار مقصود: من يقدر يدخل الغرفة يقدر يكتب فيها). نفس نمط
التحقق الهجين (System Role scope أو Committee Role) المكرَّر بكل وحدة
بهذا المشروع (meeting_service.py وdecision_service.py) — مكرَّر هنا
عمدًا بدل استيراد دوال خاصة (_underscore) من meeting_service، اتساقًا مع
قرار decision_service.py نفسه بعدم فعل ذلك.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.committee import Committee
from app.models.meeting import Meeting
from app.models.meeting_chat import MeetingChatMessage
from app.models.user import User
from app.services import committee_service


class MeetingChatNotFoundError(Exception):
    """الاجتماع غير موجود — تُترجَم إلى 404."""


class MeetingChatForbiddenError(Exception):
    """لا صلاحية للوصول لمحادثة هذا الاجتماع — تُترجَم إلى 403."""


def _system_scope_allows(actor: User, committee: Committee, code: str) -> bool:
    scope = actor.scope_for(code)
    if scope == "all":
        return True
    if scope == "department":
        committee_dep_id = committee.chair.dep_id if committee.chair else None
        return actor.dep_id is not None and actor.dep_id == committee_dep_id
    return False


async def _has_access(db: AsyncSession, actor: User, committee: Committee, code: str) -> bool:
    if _system_scope_allows(actor, committee, code):
        return True
    committee_role_codes = await committee_service.get_committee_role_permission_codes(
        db, user_id=actor.user_id, committee_id=committee.committee_id
    )
    return code in committee_role_codes


async def _load_meeting_and_committee(
    db: AsyncSession, meeting_id: uuid.UUID
) -> tuple[Meeting, Committee]:
    result = await db.execute(select(Meeting).where(Meeting.meeting_id == meeting_id))
    meeting = result.scalar_one_or_none()
    if meeting is None or meeting.is_deleted:
        raise MeetingChatNotFoundError("الاجتماع غير موجود")

    committee_result = await db.execute(
        select(Committee).where(Committee.committee_id == meeting.committee_id)
    )
    committee = committee_result.scalar_one_or_none()
    if committee is None or committee.is_deleted:
        raise MeetingChatNotFoundError("اللجنة المرتبطة غير موجودة")
    return meeting, committee


async def require_realtime_access(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> Meeting:
    """يستخدمها أيضًا راوت WebSocket (meeting_live_socket) قبل قبول الاتصال —
    نفس التحقق بالضبط المستخدَم لإرسال رسالة أو رفع اليد."""
    meeting, committee = await _load_meeting_and_committee(db, meeting_id)
    if not await _has_access(db, actor, committee, "meetings.join"):
        raise MeetingChatForbiddenError("ليست لديك صلاحية الوصول لهذا الاجتماع")
    return meeting


async def list_messages(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, limit: int = 100
) -> list[MeetingChatMessage]:
    await require_realtime_access(db, actor=actor, meeting_id=meeting_id)
    result = await db.execute(
        select(MeetingChatMessage)
        .where(MeetingChatMessage.meeting_id == meeting_id)
        .order_by(MeetingChatMessage.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def send_message(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, body: str
) -> MeetingChatMessage:
    """يُستدعى من داخل راوت WebSocket (meeting_live_socket) عند type=chat.send —
    وليس عبر REST. يحفظ الرسالة ويُرجعها؛ البث لبقية المشاركين مسؤولية
    الراوت نفسه (عبر app.core.meeting_realtime.connection_manager) بعد
    نجاح هذا الاستدعاء."""
    await require_realtime_access(db, actor=actor, meeting_id=meeting_id)

    trimmed = body.strip()
    if not trimmed:
        raise ValueError("نص الرسالة لا يمكن أن يكون فارغًا")

    message = MeetingChatMessage(meeting_id=meeting_id, sender_id=actor.user_id, body=trimmed[:2000])
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message
