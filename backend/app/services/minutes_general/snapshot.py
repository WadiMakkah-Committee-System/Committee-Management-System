"""
الهدف:
جمع بيانات الاجتماع اللي يحتاجها "القالب العام" من قاعدة البيانات في
MeetingSnapshot واحد (أعضاء اللجنة بصفاتهم، الحضور، الضيوف، البنود، رقم
الاجتماع، وقت الانتهاء).

المسؤولية: قراءة فقط — لا يكتب شيئًا ولا يفحص صلاحيات (المستدعي في
meeting_minutes_service يفحص minutes.view/update قبله).

الاستعلامات (ثابتة العدد بغض النظر عن حجم اللجنة): أعضاء+أدوار (1)،
الحضور (1)، الضيوف (1)، البنود (1)، رقم الاجتماع (1) — 5 استعلامات.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.committee import Committee, committee_members
from app.models.meeting import Meeting, MeetingAgendaItem, MeetingMode, MeetingStatus
from app.models.meeting_attendance import MeetingAttendance
from app.models.role import Role
from app.models.user import User
from app.services.minutes_general import formatting
from app.services.minutes_general.sections import (
    CHAIR_ROLE_FALLBACK,
    AgendaInfo,
    GuestInfo,
    MeetingSnapshot,
    MemberInfo,
)

_FINISHED = (MeetingStatus.finished, MeetingStatus.recorded)


def _display_name(user: User | None, first: str = "", middle: str = "", last: str = "") -> str:
    """الاسم كما هو مسجّل (بدون لقب)، بلا مسافات زائدة لو الاسم الأوسط/الأخير فارغ."""
    parts = (user.first_name, user.middle_name, user.last_name) if user is not None else (first, middle, last)
    return " ".join(p.strip() for p in parts if p and p.strip())


async def _load_members(db: AsyncSession, committee: Committee) -> tuple[MemberInfo, ...]:
    """
    الهدف: أعضاء اللجنة بصفاتهم (اسم دور اللجنة) بالترتيب المعتمد للمحضر:
    الرئيس أولًا، ثم الأعضاء بترتيب إضافتهم، ثم أمين السر آخرًا (مثل الأصل).
    الرئيس لو مو مسجّل ضمن العضوية يُضاف بصفة "رئيس اللجنة".
    """
    result = await db.execute(
        select(
            committee_members.c.user_id,
            committee_members.c.added_at,
            User.first_name,
            User.middle_name,
            User.last_name,
            Role.name,
            Role.committee_role_slug,
        )
        .join(User, User.user_id == committee_members.c.user_id)
        .join(Role, Role.role_id == committee_members.c.committee_role_id)
        .where(committee_members.c.committee_id == committee.committee_id, User.deleted_at.is_(None))
    )
    rows = result.all()

    def rank(row) -> tuple[int, datetime]:
        is_chair = row.user_id == committee.chair_user_id or row.committee_role_slug == "chair"
        return (0 if is_chair else 2 if row.committee_role_slug == "secretary" else 1, row.added_at)

    members = [
        MemberInfo(
            user_id=str(row.user_id),
            name=_display_name(None, row.first_name, row.middle_name, row.last_name),
            role_label=row.name,
            is_chair=row.user_id == committee.chair_user_id or row.committee_role_slug == "chair",
        )
        for row in sorted(rows, key=rank)
    ]
    if committee.chair_user_id is not None and all(m.user_id != str(committee.chair_user_id) for m in members):
        chair = committee.chair
        if chair is not None and chair.deleted_at is None:
            members.insert(
                0,
                MemberInfo(
                    user_id=str(chair.user_id),
                    name=_display_name(chair),
                    role_label=CHAIR_ROLE_FALLBACK,
                    is_chair=True,
                ),
            )
    return tuple(members)


async def _load_attendance(db: AsyncSession, meeting: Meeting) -> tuple[frozenset[str], datetime | None]:
    """
    الهدف: من دخل الاجتماع فعلًا (الحضور التلقائي — اجتماعات عن بعد)، وآخر
    لحظة خروج مسجّلة (تُستخدم كوقت انتهاء فعلي).
    المخرجات: (معرّفات من حضر، آخر خروج أو None).
    """
    result = await db.execute(
        select(
            MeetingAttendance.user_id,
            func.max(func.coalesce(MeetingAttendance.left_at, MeetingAttendance.last_seen_at)),
        )
        .where(MeetingAttendance.meeting_id == meeting.meeting_id)
        .group_by(MeetingAttendance.user_id)
    )
    rows = result.all()
    attended = frozenset(str(row[0]) for row in rows)
    last_left = max((row[1] for row in rows if row[1] is not None), default=None)
    return attended, last_left


async def _load_guests(db: AsyncSession, meeting: Meeting) -> tuple[GuestInfo, ...]:
    """
    الضيوف الخارجيون المقبولون (حسابات ضيف مؤقتة مربوطة بالاجتماع — migration
    0047) بترتيب دخولهم. الاسم = الاسم اللي كتبه الضيف عند الدخول.
    """
    result = await db.execute(
        select(User.user_id, User.first_name, User.middle_name, User.last_name)
        .where(User.is_guest.is_(True), User.guest_meeting_id == meeting.meeting_id)
        .order_by(User.created_at)
    )
    return tuple(
        GuestInfo(user_id=str(row.user_id), name=_display_name(None, row.first_name, row.middle_name, row.last_name))
        for row in result.all()
    )


async def _load_agenda(db: AsyncSession, meeting: Meeting) -> tuple[AgendaInfo, ...]:
    """بنود جدول الأعمال الحالية بترتيبها."""
    result = await db.execute(
        select(MeetingAgendaItem.agenda_item_id, MeetingAgendaItem.title, MeetingAgendaItem.sort_order)
        .where(MeetingAgendaItem.meeting_id == meeting.meeting_id)
        .order_by(MeetingAgendaItem.sort_order, MeetingAgendaItem.created_at)
    )
    return tuple(
        AgendaInfo(agenda_item_id=str(row.agenda_item_id), title=row.title, sort_order=index)
        for index, row in enumerate(result.all())
    )


async def compute_meeting_number(db: AsyncSession, meeting: Meeting) -> tuple[int, int]:
    """
    الهدف: رقم الاجتماع داخل لجنته في السنة الميلادية (قرار صاحب المشروع).

    القاعدة: 1 + عدد اجتماعات نفس اللجنة غير المحذوفة اللي موعدها في نفس
    السنة (بتوقيت الرياض) وقبل هذا الاجتماع. يبدأ من 1 كل سنة. التعديل
    اليدوي في المحضر لا يغيّر ترقيم الاجتماعات الأخرى.

    المخرجات: (رقم الاجتماع، السنة).
    """
    local = formatting.to_riyadh(meeting.scheduled_at)
    year_start = datetime(local.year, 1, 1, tzinfo=formatting.RIYADH)
    result = await db.execute(
        select(func.count())
        .select_from(Meeting)
        .where(
            Meeting.committee_id == meeting.committee_id,
            Meeting.deleted_at.is_(None),
            Meeting.meeting_id != meeting.meeting_id,
            Meeting.scheduled_at >= year_start,
            (Meeting.scheduled_at < meeting.scheduled_at)
            | ((Meeting.scheduled_at == meeting.scheduled_at) & (Meeting.created_at < meeting.created_at)),
        )
    )
    return int(result.scalar_one()) + 1, local.year


async def load_snapshot(db: AsyncSession, meeting: Meeting, committee: Committee) -> MeetingSnapshot:
    """
    الهدف: بيانات الاجتماع الحالية للقالب العام.

    المدخلات: meeting (بحالة زمنية محدّثة — sync_meeting_status)، committee.
    المخرجات: MeetingSnapshot.

    وقت الانتهاء الفعلي (فقط بعد انتهاء الاجتماع):
    - ended_at لو مسجّل.
    - الاجتماع عن بعد: آخر خروج فعلي من الغرفة (الحضور التلقائي).
    - غير ذلك: موعد النهاية المحدد (بعد أي تمديد).
    """
    members = await _load_members(db, committee)
    attended, last_left = await _load_attendance(db, meeting)
    guests = await _load_guests(db, meeting)
    agenda = await _load_agenda(db, meeting)
    number, year = await compute_meeting_number(db, meeting)

    end_time: datetime | None = None
    if meeting.status in _FINISHED:
        if meeting.ended_at is not None:
            end_time = meeting.ended_at
        elif meeting.mode == MeetingMode.remote and last_left is not None:
            end_time = last_left
        else:
            end_time = meeting.scheduled_end_at
    started = meeting.status != MeetingStatus.upcoming or meeting.started_at is not None

    return MeetingSnapshot(
        committee_name=committee.name,
        meeting_title=meeting.title,
        mode=meeting.mode.value,
        location=meeting.location,
        scheduled_at=meeting.scheduled_at,
        end_time=end_time,
        started=started,
        meeting_number=number,
        meeting_year=year,
        members=members,
        attended_user_ids=attended,
        guests=guests,
        agenda=agenda,
    )
