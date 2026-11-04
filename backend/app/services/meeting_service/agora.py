"""
الهدف (الرجوع لـAgora — قرار لاما 2026-11-04):
الانضمام لغرفة Agora لاجتماع عن بعد غير مربوط بـTeams.

القواعد:
- الصلاحية: meetings.join على لجنة الاجتماع (نفس من يدخل الغرفة).
- الاجتماع لازم يكون remote، وغير مربوط بـTeams (المربوط القديم يفتح بـTeams
  — راجعي teams.py)، وما انتهى.
- القناة = رقم الاجتماع، والحساب = user_id بالمنصة (راجعي agora_client) —
  فكل جهاز يعرف هوية كل صوت/فيديو مباشرة.
- الحضور يُسجَّل بمسار الحضور العام (attendance.start_session) من الواجهة
  لحظة الاتصال الفعلي — مو هنا (طلب التوكن ≠ دخول فعلي).

الأخطاء: MeetingForbiddenError، MeetingInvalidStateError، AgoraNotConfiguredError.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import agora_client
from app.models.meeting import MeetingMode, MeetingStatus
from app.models.user import User
from app.services import audit_service
from app.services.meeting_service.access import _require_access
from app.services.meeting_service.errors import MeetingInvalidStateError
from app.services.meeting_service.loading import load_meeting


@dataclass(frozen=True)
class AgoraJoinInfo:
    """كل ما تحتاجه الواجهة لـclient.join(app_id, channel, token, account)."""

    app_id: str
    channel: str
    token: str
    account: str
    expires_at: int


async def join_agora(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> AgoraJoinInfo:
    """
    الهدف: توكن دخول غرفة Agora للمستخدم الحالي.
    المدخلات: actor (المسجّل دخوله)، meeting_id.
    المخرجات: AgoraJoinInfo.
    التأثيرات الجانبية: started_at للاجتماع (أول دخول) + سطر تدقيق join + commit.
    """
    meeting = await load_meeting(db, meeting_id)
    await _require_access(
        db, actor, meeting.committee, "meetings.join", "ليست لديك صلاحية الانضمام لهذا الاجتماع"
    )
    if meeting.mode != MeetingMode.remote:
        raise MeetingInvalidStateError("هذا اجتماع حضوري، لا يملك غرفة اتصال")
    if meeting.teams_meeting_id:
        raise MeetingInvalidStateError("هذا الاجتماع مربوط بـMicrosoft Teams — يُفتح من Teams")
    if meeting.status in (MeetingStatus.finished, MeetingStatus.recorded):
        raise MeetingInvalidStateError("انتهى هذا الاجتماع بالفعل")

    channel = str(meeting.meeting_id)
    account = str(actor.user_id)
    token, expires_at = agora_client.generate_rtc_token(channel_name=channel, account=account)

    if meeting.started_at is None:
        meeting.started_at = datetime.now(UTC)
    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="join",
        target_type="meeting",
        target_id=meeting.meeting_id,
    )
    await db.commit()
    return AgoraJoinInfo(
        app_id=agora_client.get_app_id(),
        channel=channel,
        token=token,
        account=account,
        expires_at=expires_at,
    )
