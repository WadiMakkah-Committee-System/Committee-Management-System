"""
الانضمام/المغادرة لاجتماع عن بعد (Agora) — راجعي التعليق أعلى join_meeting.
"""

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import agora_client
from app.models.meeting import Meeting, MeetingAttendance, MeetingMode, MeetingStatus
from app.models.user import User
from app.services import audit_service
from app.services.meeting_service.access import _require_access
from app.services.meeting_service.errors import MeetingInvalidStateError
from app.services.meeting_service.loading import load_meeting


class MeetingJoinToken:
    """معلومات الانضمام لجلسة Agora — تُبنى بطبقة الخدمة وتُعاد للـAPI كما
    هي (نفس نمط MeetingAttachmentUpload أدناه، لكن بالاتجاه المعاكس: خرج
    لا دخل)."""

    __slots__ = ("app_id", "channel", "token", "uid", "expires_at")

    def __init__(self, *, app_id: str, channel: str, token: str, uid: int, expires_at: int) -> None:
        self.app_id = app_id
        self.channel = channel
        self.token = token
        self.uid = uid
        self.expires_at = expires_at


# ============================== الانضمام لاجتماع عن بعد (Agora) ==============================
# غرفة الفيديو نفسها لا تُدار هنا — Agora فقط تصدر Token قصير العمر
# (app.core.agora_client)، والقناة (channel) هي meeting_id نصًا مباشرة (فريد
# أصلًا، بلا حاجة لعمود إضافي). meeting_attendance سطر تدقيقي منفصل عن
# meeting_participants (المدعوّون المخطّط لهم) — راجعي رأس
# db/migrations/0022_meetings_agora_video.sql للتفصيل الكامل، خصوصًا قرار عدم
# تعديل meetings.status من هذين الإجراءين.


async def join_meeting(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID
) -> tuple[Meeting, MeetingJoinToken]:
    """الانضمام لاجتماع عن بعد — يتطلب meetings.join (نفس نمط الوصول المزدوج
    System Role/Committee Role في كل عمليات هذا الملف). يصدر Token عبر
    app.core.agora_client، ويسجّل سطر حضور جديد بـmeeting_attendance."""
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_access(
        db, actor, committee, "meetings.join", "ليست لديك صلاحية الانضمام لهذا الاجتماع"
    )

    if meeting.mode != MeetingMode.remote:
        raise MeetingInvalidStateError("هذا اجتماع حضوري، لا يملك غرفة اتصال مرئي")
    if meeting.status == MeetingStatus.finished:
        raise MeetingInvalidStateError("انتهى هذا الاجتماع بالفعل")

    uid = secrets.randbelow(900_000) + 100_000  # uid عشوائي لكل جلسة انضمام (32-bit آمن)
    token, expires_at = agora_client.generate_rtc_token(channel_name=str(meeting.meeting_id), uid=uid)

    db.add(MeetingAttendance(meeting_id=meeting.meeting_id, user_id=actor.user_id, agora_uid=uid))
    if meeting.started_at is None:
        meeting.started_at = datetime.now(UTC)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="join",
        target_type="meeting",
        target_id=meeting.meeting_id,
    )
    await db.flush()

    return meeting, MeetingJoinToken(
        app_id=agora_client.get_app_id(),
        channel=str(meeting.meeting_id),
        token=token,
        uid=uid,
        expires_at=expires_at,
    )


async def leave_meeting(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, agora_uid: int | None
) -> Meeting:
    """مغادرة اجتماع عن بعد — يقفل سطر الحضور المفتوح لهذا المستخدم (وuid
    الجلسة تحديدًا لو أُرسل، لتفادي إقفال جلسة أخرى مفتوحة لنفس المستخدم من
    تبويب/جهاز ثاني بالخطأ). فلترة user_id == actor.user_id بالتحديث أدناه
    تمنع إقفال حضور غيره أصلًا، بصرف النظر عن أي فحص صلاحية إضافي."""
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_access(
        db, actor, committee, "meetings.join", "ليست لديك صلاحية مغادرة هذا الاجتماع"
    )

    stmt = (
        update(MeetingAttendance)
        .where(
            MeetingAttendance.meeting_id == meeting.meeting_id,
            MeetingAttendance.user_id == actor.user_id,
            MeetingAttendance.left_at.is_(None),
        )
        .values(left_at=datetime.now(UTC))
    )
    if agora_uid is not None:
        stmt = stmt.where(MeetingAttendance.agora_uid == agora_uid)
    await db.execute(stmt)

    remaining = await db.scalar(
        select(func.count())
        .select_from(MeetingAttendance)
        .where(
            MeetingAttendance.meeting_id == meeting.meeting_id,
            MeetingAttendance.left_at.is_(None),
        )
    )
    if not remaining:
        meeting.ended_at = datetime.now(UTC)

    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="leave",
        target_type="meeting",
        target_id=meeting.meeting_id,
    )
    await db.flush()
    return meeting

