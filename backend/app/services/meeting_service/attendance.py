"""
الهدف (الحضور التلقائي — migration 0043، قرار لاما 2026-11-03):
تسجيل حضور أعضاء اجتماع Teams المدمج تلقائيًا من غرفة الاجتماع بالمنصة، وتلخيصه
بجدول (الاسم، أول دخول، آخر خروج، إجمالي المدة، عدد مرات الدخول).

المسؤولية:
- start_session: جهاز العضو يبلّغ لحظة دخوله الفعلي (بعد القبول من الانتظار).
- heartbeat: نبضة كل دقيقة تقريبًا وهو داخل.
- end_session: خروجه (مغادرة/إغلاق الصفحة).
- attendance_summary: الجدول المجمّع لكل عضو.

قواعد:
- الصلاحية: meetings.join للتسجيل (نفس من يدخل الغرفة)، meetings.view للعرض.
- جلسة مفتوحة بدون نبضة لأكثر من STALE_AFTER ⇒ تُعتبر منتهية عند آخر نبضة
  (المتصفح انقفل فجأة) — تُقفل تلقائيًا عند أي دخول جديد لنفس العضو.
- العضو يقدر يحدّث جلساته هو فقط (attendance_id + user_id معًا بالشرط).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting import MeetingMode
from app.models.meeting_attendance import MeetingAttendance
from app.models.user import User
from app.services.meeting_service.access import _require_access
from app.services.meeting_service.errors import MeetingInvalidStateError
from app.services.meeting_service.loading import load_meeting

# الجلسة اللي ما وصلتها نبضة من 3 دقائق (النبضة كل دقيقة) ⇒ منقطعة.
STALE_AFTER = timedelta(minutes=3)


def _now() -> datetime:
    return datetime.now(UTC)


async def start_session(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> MeetingAttendance:
    """
    يبدأ جلسة حضور جديدة للعضو (يقفل أي جلسة مفتوحة سابقة له بنفس الاجتماع
    عند آخر نبضة — مثلًا لو حدّث الصفحة).
    الصلاحية: meetings.join. الأخطاء: MeetingForbiddenError، MeetingInvalidStateError.
    """
    meeting = await load_meeting(db, meeting_id)
    await _require_access(
        db, actor, meeting.committee, "meetings.join", "ليست لديك صلاحية الانضمام لهذا الاجتماع"
    )
    # إصلاح 2026-11-04 (بلاغ لاما — نسبة الحضور طلعت 0 وهي ولجين حضروا اجتماع Agora):
    # كان الشرط "Teams فقط" من قبل الرجوع لـAgora، فكل طلبات الحضور كانت ترجع 409.
    # الحين أي اجتماع عن بعد (Agora أو Teams). الحضوري ما له غرفة اتصال.
    if meeting.mode != MeetingMode.remote:
        raise MeetingInvalidStateError("الحضور التلقائي للاجتماعات عن بعد فقط")
    await db.execute(
        update(MeetingAttendance)
        .where(
            MeetingAttendance.meeting_id == meeting.meeting_id,
            MeetingAttendance.user_id == actor.user_id,
            MeetingAttendance.left_at.is_(None),
        )
        .values(left_at=MeetingAttendance.last_seen_at)
    )
    now = _now()
    session = MeetingAttendance(meeting_id=meeting.meeting_id, user_id=actor.user_id, joined_at=now, last_seen_at=now)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def _own_open_session(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, attendance_id: uuid.UUID
) -> MeetingAttendance | None:
    result = await db.execute(
        select(MeetingAttendance).where(
            MeetingAttendance.attendance_id == attendance_id,
            MeetingAttendance.meeting_id == meeting_id,
            MeetingAttendance.user_id == actor.user_id,
            MeetingAttendance.left_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def heartbeat(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, attendance_id: uuid.UUID) -> bool:
    """نبضة "لسا موجود". المخرجات: False لو الجلسة مو له أو مقفلة (الواجهة تبدأ جلسة جديدة)."""
    session = await _own_open_session(db, actor=actor, meeting_id=meeting_id, attendance_id=attendance_id)
    if session is None:
        return False
    session.last_seen_at = _now()
    await db.commit()
    return True


async def end_session(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, attendance_id: uuid.UUID) -> None:
    """خروج العضو — يقفل جلسته (لا شيء لو مقفلة أصلًا أو مو له)."""
    session = await _own_open_session(db, actor=actor, meeting_id=meeting_id, attendance_id=attendance_id)
    if session is None:
        return
    now = _now()
    session.last_seen_at = now
    session.left_at = now
    await db.commit()


@dataclass(frozen=True)
class AttendanceRow:
    """سطر جدول الحضور لعضو واحد."""

    user: User
    first_joined_at: datetime
    last_left_at: datetime | None  # None = لسا داخل الاجتماع الحين
    total_seconds: int
    sessions: int


async def attendance_summary(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> list[AttendanceRow]:
    """
    جدول الحضور المجمّع لكل عضو، مرتّب بأول دخول.
    الجلسة المفتوحة: لو نبضتها حديثة ⇒ "لسا داخل" (المدة حتى الحين)، ولو قديمة ⇒
    منتهية عند آخر نبضة.
    الصلاحية: meetings.view.
    """
    meeting = await load_meeting(db, meeting_id)
    await _require_access(db, actor, meeting.committee, "meetings.view", "ليست لديك صلاحية عرض هذا الاجتماع")
    return await summarize_attendance(db, meeting_id=meeting.meeting_id)


async def summarize_attendance(db: AsyncSession, *, meeting_id: uuid.UUID) -> list[AttendanceRow]:
    """
    نفس attendance_summary **بدون فحص صلاحية** — على المستدعي فحصها قبلها
    (مثلًا ملف PDF المحضر بعد فحص minutes.view).
    """
    result = await db.execute(
        select(MeetingAttendance)
        .where(MeetingAttendance.meeting_id == meeting_id)
        .order_by(MeetingAttendance.joined_at)
    )
    now = _now()
    grouped: dict[uuid.UUID, list[MeetingAttendance]] = {}
    for row in result.scalars().all():
        grouped.setdefault(row.user_id, []).append(row)

    rows: list[AttendanceRow] = []
    for sessions in grouped.values():
        total = 0.0
        last_left: datetime | None = None
        still_here = False
        for s in sessions:
            if s.left_at is not None:
                end = s.left_at
            elif now - s.last_seen_at <= STALE_AFTER:
                end = now
                still_here = True
            else:
                end = s.last_seen_at
            total += max(0.0, (end - s.joined_at).total_seconds())
            if s.left_at is not None or end != now:
                last_left = end if last_left is None or end > last_left else last_left
        rows.append(
            AttendanceRow(
                user=sessions[0].user,
                first_joined_at=sessions[0].joined_at,
                last_left_at=None if still_here else last_left,
                total_seconds=int(total),
                sessions=len(sessions),
            )
        )
    rows.sort(key=lambda r: r.first_joined_at)
    return rows
