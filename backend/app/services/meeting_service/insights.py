"""
الهدف (الدفعة 3 من تحسينات الاجتماع — migration 0044، قرار لاما 2026-11-03):
- save_transcript_segments: حفظ جمل الترجمة النصية الحية (جهاز الرئيس بـTeams، أو
  كل عضو كلامه هو بـAgora — own_speech).
- catch_up: "وش فاتني؟" — ملخص Gemini لآخر دقائق من النص.
- meeting_insights: إحصائيات الاجتماع (الحضور، مدة كلام كل عضو، وقت البنود).
- open_agenda_session / close_agenda_sessions: فترات مناقشة البنود (من Socket.IO).

قواعد:
- حفظ النص: رئيس اللجنة فقط (meetings.agenda.item.update — نفس من يدير الأجندة
  ويشغّل الترجمة) — مصدر واحد بدون تكرار.
- "وش فاتني؟": meetings.join (من يحضر الاجتماع). الإحصائيات: meetings.view.
- مدة الكلام **تقديرية** من عدد الكلمات (لا توجد مدة دقيقة لكل جملة من Microsoft).
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import gemini_client
from app.core.redis_client import redis_client
from app.models.meeting import MeetingAgendaItem
from app.models.meeting_insights import MeetingAgendaSession, MeetingTranscriptSegment
from app.models.user import User
from app.services.meeting_service.access import _require_access
from app.services.meeting_service.attendance import summarize_attendance
from app.services.meeting_service.errors import MeetingValidationError
from app.services.meeting_service.loading import _all_committee_members, load_committee, load_meeting

logger = logging.getLogger(__name__)

# متوسط سرعة الكلام بالعربي تقريبًا (كلمة/ثانية) — لتقدير مدة الكلام من النص.
_WORDS_PER_SECOND = 2.2
_MAX_SEGMENTS_PER_BATCH = 200
_CATCH_UP_MAX_MINUTES = 30
_CATCH_UP_CACHE_SECONDS = 60


@dataclass(frozen=True)
class SegmentIn:
    """جملة مكتملة من الترجمة النصية (من جهاز الرئيس)."""

    client_key: str
    speaker_raw_id: str | None
    speaker_name: str
    text: str
    spoken_at: datetime
    language: str | None
    agenda_item_id: uuid.UUID | None


async def _resolve_speakers(db: AsyncSession, meeting_id: uuid.UUID, raw_ids: set[str]) -> dict[str, uuid.UUID]:
    """
    يربط معرّف المتحدث بـTeams بمستخدم المنصة:
    - موظف بحساب Microsoft: "8:orgid:{oid}" ⇒ users.microsoft_object_id.
    - ضيف دخل من المنصة: "8:acs:..." ⇒ ربط هويات الضيوف المحفوظ (Redis).
    غير المعروفين (دخلوا برابط Teams من برا المنصة) يبقون بالاسم فقط.
    """
    resolved: dict[str, uuid.UUID] = {}
    oids: dict[uuid.UUID, str] = {}
    for raw in raw_ids:
        tail = raw.split(":")[-1]
        if ":orgid:" in raw:
            try:
                oids[uuid.UUID(tail)] = raw
            except ValueError:
                continue
    if oids:
        rows = await db.execute(select(User.user_id, User.microsoft_object_id).where(User.microsoft_object_id.in_(oids)))
        for user_id, oid in rows.all():
            resolved[oids[oid]] = user_id
    acs_ids = [r for r in raw_ids if ":acs:" in r and r not in resolved]
    if acs_ids:
        try:
            known = await redis_client.hgetall(f"meeting:{meeting_id}:acs-guests")
        except Exception:  # noqa: BLE001
            known = {}
        normalized = {k.split(":")[-1].split("_")[-1].lower(): v for k, v in known.items()}
        for raw in acs_ids:
            value = normalized.get(raw.split(":")[-1].split("_")[-1].lower())
            if value:
                try:
                    resolved[raw] = uuid.UUID(json.loads(value)["user_id"])
                except (ValueError, KeyError, TypeError):
                    continue
    return resolved


async def save_transcript_segments(
    db: AsyncSession,
    *,
    actor: User,
    meeting_id: uuid.UUID,
    segments: list[SegmentIn],
    own_speech: bool = False,
) -> int:
    """
    يحفظ دفعة جمل مكتملة (تُتجاهل المكررة بنفس client_key).

    وضعين:
    - own_speech=False (اجتماعات Teams القديمة): جهاز الرئيس يرسل جمل الكل —
      الصلاحية meetings.agenda.item.update، والمتحدث يُستنتج من معرّف Teams.
    - own_speech=True (Agora — قرار لاما 2026-11-04، التعرف على الكلام المجاني
      بالمتصفح): كل عضو يرسل **كلامه هو فقط** — الصلاحية meetings.join، والمتحدث
      يُفرض بالباك-إند = المستخدم نفسه (أي speaker_* من الواجهة يُتجاهل)، فما
      يقدر أحد ينسب كلام لغيره.
    المخرجات: عدد الجديد.
    """
    meeting = await load_meeting(db, meeting_id)
    if own_speech:
        await _require_access(
            db, actor, meeting.committee, "meetings.join", "ليست لديك صلاحية الوصول لهذا الاجتماع"
        )
    else:
        await _require_access(
            db, actor, meeting.committee, "meetings.agenda.item.update", "حفظ الترجمة النصية لرئيس اللجنة فقط"
        )
    clean = [s for s in segments[:_MAX_SEGMENTS_PER_BATCH] if s.text.strip() and s.client_key.strip()]
    if not clean:
        return 0
    item_ids = {i.agenda_item_id for i in meeting.agenda_items} if "agenda_items" in meeting.__dict__ else None
    if item_ids is None:
        rows = await db.execute(
            select(MeetingAgendaItem.agenda_item_id).where(MeetingAgendaItem.meeting_id == meeting.meeting_id)
        )
        item_ids = set(rows.scalars().all())
    if own_speech:
        speakers: dict[str, uuid.UUID] = {}
    else:
        speakers = await _resolve_speakers(
            db, meeting.meeting_id, {s.speaker_raw_id for s in clean if s.speaker_raw_id}
        )
    values = [
        {
            "meeting_id": meeting.meeting_id,
            # own_speech: المفتاح يُربط بالمستخدم — جملتين من شخصين بنفس اللحظة ما يتعارضون.
            "client_key": (f"{actor.user_id}:{s.client_key.strip()}" if own_speech else s.client_key.strip())[:200],
            "speaker_user_id": actor.user_id if own_speech else speakers.get(s.speaker_raw_id or ""),
            "speaker_name": (actor.full_name if own_speech else s.speaker_name.strip())[:200],
            "text": s.text.strip()[:4000],
            "spoken_at": s.spoken_at,
            "language": (s.language or None) and s.language[:20],
            "agenda_item_id": s.agenda_item_id if s.agenda_item_id in item_ids else None,
        }
        for s in clean
    ]
    result = await db.execute(
        insert(MeetingTranscriptSegment)
        .values(values)
        .on_conflict_do_nothing(constraint="uq_transcript_segments_client_key")
        .returning(MeetingTranscriptSegment.segment_id)
    )
    inserted = len(result.scalars().all())
    await db.commit()
    return inserted


async def catch_up(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, minutes: int) -> tuple[str | None, int]:
    """
    "وش فاتني؟": ملخص Gemini لآخر `minutes` دقيقة من الترجمة النصية.
    المخرجات: (الملخص أو None لو ما فيه نص، عدد الجمل). يُخزَّن الملخص دقيقة
    (Redis) لنفس الاجتماع والمدة — ما نكرر استدعاء Gemini لكل ضغطة.
    الصلاحية: meetings.join. الأخطاء: GeminiError (502 بالراوت).
    """
    meeting = await load_meeting(db, meeting_id)
    await _require_access(
        db, actor, meeting.committee, "meetings.join", "ليست لديك صلاحية الانضمام لهذا الاجتماع"
    )
    minutes = max(1, min(minutes, _CATCH_UP_MAX_MINUTES))
    cache_key = f"meeting:{meeting.meeting_id}:catchup:{minutes}"
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            data = json.loads(cached)
            return data["summary"], data["count"]
    except Exception:  # noqa: BLE001
        cached = None
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    rows = (
        await db.execute(
            select(MeetingTranscriptSegment)
            .where(MeetingTranscriptSegment.meeting_id == meeting.meeting_id, MeetingTranscriptSegment.spoken_at >= since)
            .order_by(MeetingTranscriptSegment.spoken_at)
        )
    ).scalars().all()
    if not rows:
        return None, 0
    transcript = "\n".join(f"{r.speaker_name or 'مشارك'}: {r.text}" for r in rows)
    summary = await gemini_client.summarize_catch_up(meeting_title=meeting.title, minutes=minutes, transcript=transcript)
    try:
        await redis_client.set(
            cache_key, json.dumps({"summary": summary, "count": len(rows)}, ensure_ascii=False), ex=_CATCH_UP_CACHE_SECONDS
        )
    except Exception:  # noqa: BLE001
        pass
    return summary, len(rows)


@dataclass(frozen=True)
class SpeakerStat:
    user_id: uuid.UUID | None
    name: str
    estimated_seconds: int
    segments: int


@dataclass(frozen=True)
class AgendaStat:
    agenda_item_id: uuid.UUID
    title: str
    actual_seconds: int
    planned_seconds: int | None


@dataclass(frozen=True)
class MeetingInsights:
    duration_seconds: int | None
    attended_members: int
    total_members: int
    speakers: list[SpeakerStat]
    agenda: list[AgendaStat]
    has_transcript: bool


async def meeting_insights(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> MeetingInsights:
    """
    إحصائيات الاجتماع (قرار لاما 2026-11-03، البند 15). الصلاحية: meetings.view.
    - المدة: من أول دخول إلى آخر خروج (الحضور التلقائي)، أو None لو ما فيه حضور.
    - نسبة الحضور: أعضاء اللجنة اللي حضروا ÷ كل أعضائها.
    - مدة كلام كل متحدث: تقديرية من عدد كلمات جمله بالترجمة النصية.
    - البنود: الوقت الفعلي (مجموع فترات المناقشة) مقابل آخر مؤقت اختاره الرئيس.
    """
    meeting = await load_meeting(db, meeting_id)
    await _require_access(db, actor, meeting.committee, "meetings.view", "ليست لديك صلاحية عرض هذا الاجتماع")
    committee = await load_committee(db, meeting.committee_id, with_members=True)
    member_ids = {m.user_id for m in _all_committee_members(committee)}

    attendance = await summarize_attendance(db, meeting_id=meeting.meeting_id)
    duration: int | None = None
    if attendance:
        start = min(r.first_joined_at for r in attendance)
        ends = [r.last_left_at or datetime.now(UTC) for r in attendance]
        duration = int((max(ends) - start).total_seconds())
    attended = len({r.user.user_id for r in attendance} & member_ids)

    segments = (
        await db.execute(select(MeetingTranscriptSegment).where(MeetingTranscriptSegment.meeting_id == meeting.meeting_id))
    ).scalars().all()
    per_speaker: dict[str, dict] = {}
    for seg in segments:
        key = str(seg.speaker_user_id) if seg.speaker_user_id else f"name:{seg.speaker_name}"
        entry = per_speaker.setdefault(key, {"user_id": seg.speaker_user_id, "name": seg.speaker_name, "words": 0, "count": 0})
        entry["words"] += len(seg.text.split())
        entry["count"] += 1
    speakers = sorted(
        (
            SpeakerStat(
                user_id=e["user_id"],
                name=e["name"] or "مشارك",
                estimated_seconds=int(e["words"] / _WORDS_PER_SECOND),
                segments=e["count"],
            )
            for e in per_speaker.values()
        ),
        key=lambda s: s.estimated_seconds,
        reverse=True,
    )

    sessions = (
        await db.execute(
            select(MeetingAgendaSession)
            .where(MeetingAgendaSession.meeting_id == meeting.meeting_id)
            .order_by(MeetingAgendaSession.started_at)
        )
    ).scalars().all()
    now = datetime.now(UTC)
    titles = {i.agenda_item_id: i.title for i in meeting.agenda_items} if "agenda_items" in meeting.__dict__ else {}
    if not titles:
        rows = await db.execute(
            select(MeetingAgendaItem.agenda_item_id, MeetingAgendaItem.title).where(
                MeetingAgendaItem.meeting_id == meeting.meeting_id
            )
        )
        titles = dict(rows.all())
    agenda: dict[uuid.UUID, dict] = {}
    for s in sessions:
        entry = agenda.setdefault(s.agenda_item_id, {"seconds": 0.0, "planned": None})
        entry["seconds"] += max(0.0, ((s.ended_at or now) - s.started_at).total_seconds())
        if s.planned_seconds:
            entry["planned"] = s.planned_seconds
    agenda_stats = [
        AgendaStat(
            agenda_item_id=item_id,
            title=titles.get(item_id, "بند"),
            actual_seconds=int(e["seconds"]),
            planned_seconds=e["planned"],
        )
        for item_id, e in agenda.items()
    ]

    return MeetingInsights(
        duration_seconds=duration,
        attended_members=attended,
        total_members=len(member_ids),
        speakers=speakers,
        agenda=agenda_stats,
        has_transcript=bool(segments),
    )


# ============================== فترات مناقشة البنود (من Socket.IO) ==============================


async def open_agenda_session(
    db: AsyncSession, *, meeting_id: uuid.UUID, agenda_item_id: str, planned_seconds: int | None
) -> None:
    """
    يقفل أي فترة مناقشة مفتوحة بالاجتماع ويفتح فترة للبند الجديد (للإحصائيات).
    بدون فحص صلاحية — المستدعي (agenda.discussing) فحص إدارة الأجندة قبلها.
    بند غير تابع للاجتماع ⇒ MeetingValidationError.
    """
    try:
        item_uuid = uuid.UUID(str(agenda_item_id))
    except ValueError as exc:
        raise MeetingValidationError("بند غير صالح") from exc
    exists = await db.scalar(
        select(MeetingAgendaItem.agenda_item_id).where(
            MeetingAgendaItem.agenda_item_id == item_uuid, MeetingAgendaItem.meeting_id == meeting_id
        )
    )
    if exists is None:
        raise MeetingValidationError("البند لا يتبع هذا الاجتماع")
    await close_agenda_sessions(db, meeting_id=meeting_id, commit=False)
    db.add(MeetingAgendaSession(meeting_id=meeting_id, agenda_item_id=item_uuid, planned_seconds=planned_seconds))
    await db.commit()


async def close_agenda_sessions(db: AsyncSession, *, meeting_id: uuid.UUID, commit: bool = True) -> None:
    """يقفل فترات المناقشة المفتوحة بالاجتماع (إيقاف المناقشة/بدء بند آخر)."""
    await db.execute(
        update(MeetingAgendaSession)
        .where(MeetingAgendaSession.meeting_id == meeting_id, MeetingAgendaSession.ended_at.is_(None))
        .values(ended_at=datetime.now(UTC))
    )
    if commit:
        await db.commit()


__all__ = [
    "AgendaStat",
    "MeetingInsights",
    "SegmentIn",
    "SpeakerStat",
    "catch_up",
    "close_agenda_sessions",
    "meeting_insights",
    "open_agenda_session",
    "save_transcript_segments",
]
