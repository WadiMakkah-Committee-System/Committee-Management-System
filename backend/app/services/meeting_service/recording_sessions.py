"""
الهدف (migration 0045 — الرجوع لـAgora، قرار لاما 2026-11-04):
تسجيل صوتي لكل أعضاء الاجتماع يُرفع على دفعات أثناء الاجتماع.

كيف يشتغل:
1) رئيس اللجنة يضغط "تسجيل" ⇒ start_session (جلسة جارية وحدة لكل اجتماع).
2) متصفح الرئيس يدمج صوته + صوت كل الأعضاء (Web Audio) ويسجّلها بـMediaRecorder،
   ويرفع قطعة كل ~30 ثانية ⇒ upload_chunk (مرقّمة 0، 1، 2...).
3) "إيقاف" ⇒ stop_session: القطع تُدمج بملف واحد يدخل meeting_recordings —
   نفس مسار المسودة الحالي (generate_draft يجمع كل تسجيلات الاجتماع).
4) "ما أبي أي سلبيات" (لاما): لو صفحة الرئيس انقفلت أو انقطع النت بدون إيقاف،
   المجدوِل (finalize_stale_sessions) يدمج الجلسة تلقائيًا بعد دقائق من آخر
   قطعة — فما يضيع شي سُجّل (أقصى خسارة: آخر قطعة ما لحقت ترتفع).

لماذا دمج القطع بالبايتات صحيح: كل القطع من نفس MediaRecorder (نفس الجلسة)،
والقطعة الأولى فيها ترويسة الملف (WebM/Ogg/MP4) والباقي تكملة — ربطها بالترتيب
يعطي ملف صوتي سليم (موثّق بمواصفة MediaRecorder: timeslice).

الأمان:
- البدء/الإيقاف: meetings.record_audio (رئيس اللجنة).
- رفع القطع: صاحب الجلسة نفسه فقط (started_by) — حتى لو أحد ثاني عنده الصلاحية.
- القطع بلا ترتيب (فجوة) تُرفض — الواجهة ترفع بالتسلسل وتعيد المحاولة.
- حدود حجم: القطعة ≤ 10MB، والجلسة ≤ 500MB.
"""

import asyncio
import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage_client
from app.core.redis_client import redis_client
from app.models.meeting_draft import MeetingRecording
from app.models.meeting_recording_session import (
    RECORDING_SESSION_ACTIVE,
    RECORDING_SESSION_FAILED,
    RECORDING_SESSION_FINALIZED,
    MeetingRecordingSession,
)
from app.models.user import User
from app.services.meeting_service.access import _require_access
from app.services.meeting_service.errors import (
    MeetingForbiddenError,
    MeetingInvalidStateError,
    MeetingNotFoundError,
    MeetingValidationError,
)
from app.services.meeting_service.loading import load_meeting

logger = logging.getLogger(__name__)

MAX_CHUNK_BYTES = 10 * 1024 * 1024
MAX_SESSION_BYTES = 500 * 1024 * 1024
# جلسة بلا قطع جديدة لهالمدة = صفحة الرئيس انقفلت ⇒ تُدمج تلقائيًا.
STALE_AFTER = timedelta(minutes=3)
# جلسة بدأت وما وصلها ولا قطعة لهالمدة ⇒ تُغلق كفاشلة (ما فيه صوت).
EMPTY_STALE_AFTER = timedelta(minutes=10)
_ALLOWED_MIME_PREFIXES = ("audio/webm", "audio/ogg", "audio/mp4")
_EXTENSIONS = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a"}
_STATE_TTL_SECONDS = 24 * 60 * 60


def recording_state_key(meeting_id: uuid.UUID | str) -> str:
    """مفتاح Redis لحالة التسجيل الظاهرة لكل الحضور (يقرأه room.state بالسوكِت)."""
    return f"meeting:{meeting_id}:recording"


@dataclass(frozen=True)
class RecordingState:
    """حالة التسجيل للبث لغرفة الاجتماع (مؤشر "جاري التسجيل" عند الكل)."""

    active: bool
    session_id: str | None = None
    started_by: str | None = None
    started_by_name: str | None = None
    started_at: str | None = None

    def as_dict(self) -> dict:
        return {
            "active": self.active,
            "session_id": self.session_id,
            "started_by": self.started_by,
            "started_by_name": self.started_by_name,
            "started_at": self.started_at,
        }


_REMUX_TIMEOUT_SECONDS = 120


async def _remux_with_duration(content: bytes, extension: str) -> bytes:
    """
    الهدف (بلاغ لاما 2026-11-04 — "سجّلنا 10 دقايق وطلع التسجيل قصير"):
    ملف MediaRecorder يطلع **بدون مدة مكتوبة بترويسته** (يُكتب وهو يسجّل)، فمشغّلات
    الصوت تعرض مدة غلط/قصيرة وما تقدر تقدّم فيه. نعيد تغليفه بـffmpeg (`-c copy`:
    بدون إعادة ترميز — ثواني حتى لاجتماع طويل) فتنكتب المدة الصحيحة.
    أي فشل (ffmpeg غير موجود بالبيئة/ملف غريب) ⇒ نرجع الملف الأصلي كما هو (ما نخسر التسجيل).
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning("ffmpeg غير موجود — التسجيل ينحفظ بدون إصلاح المدة")
        return content
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in.{extension}"
        dst = Path(tmp) / f"out.{extension}"
        src.write_bytes(content)
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-c", "copy", str(dst),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=_REMUX_TIMEOUT_SECONDS)
        except TimeoutError:
            proc.kill()
            logger.warning("ffmpeg تجاوز المهلة — التسجيل ينحفظ بدون إصلاح المدة")
            return content
        if proc.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
            logger.warning("ffmpeg فشل بإصلاح مدة التسجيل: %s", (stderr or b"")[:300])
            return content
        return dst.read_bytes()


def _chunk_path(session: MeetingRecordingSession, seq: int) -> str:
    return f"meeting-recordings/{session.meeting_id}/sessions/{session.session_id}/{seq:06d}.part"


def _base_mime(mime_type: str) -> str:
    return mime_type.split(";")[0].strip().lower()


async def _publish_state(meeting_id: uuid.UUID, state: RecordingState) -> None:
    """يحفظ الحالة بـRedis (للي يدخل متأخر). best-effort — البث نفسه بطبقة الـAPI."""
    import json

    try:
        if state.active:
            await redis_client.set(recording_state_key(meeting_id), json.dumps(state.as_dict()), ex=_STATE_TTL_SECONDS)
        else:
            await redis_client.delete(recording_state_key(meeting_id))
    except Exception:  # noqa: BLE001 — مؤشر مساعد فقط
        logger.warning("تعذّر حفظ حالة التسجيل بـRedis (meeting=%s)", meeting_id, exc_info=True)


def _state_of(session: MeetingRecordingSession) -> RecordingState:
    return RecordingState(
        active=session.status == RECORDING_SESSION_ACTIVE,
        session_id=str(session.session_id),
        started_by=str(session.started_by),
        started_by_name=session.starter.full_name if session.starter else None,
        started_at=session.started_at.isoformat() if session.started_at else None,
    )


async def _active_session(db: AsyncSession, meeting_id: uuid.UUID, *, lock: bool = False) -> MeetingRecordingSession | None:
    stmt = select(MeetingRecordingSession).where(
        MeetingRecordingSession.meeting_id == meeting_id,
        MeetingRecordingSession.status == RECORDING_SESSION_ACTIVE,
    )
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _load_session(db: AsyncSession, meeting_id: uuid.UUID, session_id: uuid.UUID) -> MeetingRecordingSession:
    session = (
        await db.execute(
            select(MeetingRecordingSession)
            .where(
                MeetingRecordingSession.session_id == session_id,
                MeetingRecordingSession.meeting_id == meeting_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if session is None:
        raise MeetingNotFoundError("جلسة التسجيل غير موجودة")
    return session


async def _finalize(db: AsyncSession, session: MeetingRecordingSession) -> MeetingRecordingSession:
    """
    الهدف: دمج قطع الجلسة بملف واحد + سجل meeting_recordings + إغلاق الجلسة.
    - بلا قطع ⇒ failed ("ما وصل صوت").
    - فشل التخزين ⇒ يرمي StorageError والجلسة تبقى "جارية" (المجدوِل يعيد المحاولة).
    التأثيرات: commit.
    """
    now = datetime.now(UTC)
    if session.last_seq < 0:
        session.status = RECORDING_SESSION_FAILED
        session.error_message = "ما وصل أي صوت من جهاز المسجِّل"
        session.finalized_at = now
        await db.commit()
        return session

    parts = [await storage_client.download_object(_chunk_path(session, seq)) for seq in range(session.last_seq + 1)]
    base_mime = _base_mime(session.mime_type)
    extension = _EXTENSIONS.get(base_mime, "webm")
    content = await _remux_with_duration(b"".join(parts), extension)
    recording_id = uuid.uuid4()
    local_started = session.started_at.astimezone(UTC).strftime("%Y%m%d-%H%M")
    file_name = f"meeting-recording-{local_started}.{extension}"
    storage_path = f"meeting-recordings/{session.meeting_id}/{recording_id}_{file_name}"
    await storage_client.upload_object(storage_path, content, content_type=base_mime)

    end = session.last_chunk_at or now
    duration = max(int((end - session.started_at).total_seconds()), 0) if session.started_at else None
    db.add(
        MeetingRecording(
            recording_id=recording_id,
            meeting_id=session.meeting_id,
            storage_path=storage_path,
            file_name=file_name,
            mime_type=base_mime,
            file_size_bytes=len(content),
            duration_seconds=duration,
            recorded_by=session.started_by,
        )
    )
    await db.flush()
    session.recording_id = recording_id
    session.status = RECORDING_SESSION_FINALIZED
    session.finalized_at = now
    await db.commit()

    # تنظيف القطع بعد نجاح الدمج (best-effort — بقاؤها ما يضر غير المساحة).
    for seq in range(session.last_seq + 1):
        try:
            await storage_client.delete_object(_chunk_path(session, seq))
        except Exception:  # noqa: BLE001
            logger.warning("تعذّر حذف قطعة تسجيل بعد الدمج (session=%s seq=%s)", session.session_id, seq)
    return session


async def start_session(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, mime_type: str
) -> tuple[MeetingRecordingSession, RecordingState]:
    """
    الهدف: بدء تسجيل جديد (زر "تسجيل" عند الرئيس).
    لو فيه جلسة جارية (مثلًا الرئيس رجع بعد انقطاع) تُدمج أولًا ثم تبدأ جديدة —
    المقطعين يدخلون نفس المسودة.
    الأخطاء: MeetingForbiddenError، MeetingValidationError (صيغة غير مدعومة).
    """
    meeting = await load_meeting(db, meeting_id)
    await _require_access(
        db, actor, meeting.committee, "meetings.record_audio", "تشغيل التسجيل لرئيس اللجنة فقط"
    )
    mime = (mime_type or "").strip()[:100]
    if not mime.lower().startswith(_ALLOWED_MIME_PREFIXES):
        raise MeetingValidationError("صيغة التسجيل غير مدعومة — جرّب متصفح Chrome أو Edge أو Safari حديث")

    previous = await _active_session(db, meeting.meeting_id, lock=True)
    if previous is not None:
        await _finalize(db, previous)

    session = MeetingRecordingSession(meeting_id=meeting.meeting_id, started_by=actor.user_id, mime_type=mime)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    state = _state_of(session)
    await _publish_state(meeting.meeting_id, state)
    return session, state


async def upload_chunk(
    db: AsyncSession,
    *,
    actor: User,
    meeting_id: uuid.UUID,
    session_id: uuid.UUID,
    seq: int,
    content: bytes,
) -> MeetingRecordingSession:
    """
    الهدف: حفظ قطعة رقم seq من التسجيل.
    - seq = last_seq + 1 ⇒ قطعة جديدة. seq ≤ last_seq ⇒ إعادة إرسال (تُستبدل، idempotent).
    - seq > last_seq + 1 ⇒ فجوة ⇒ MeetingValidationError (الواجهة تعيد بالترتيب).
    الأخطاء: MeetingForbiddenError (مو صاحب الجلسة)، MeetingInvalidStateError (الجلسة مقفلة)،
    MeetingValidationError (حجم/ترتيب).
    """
    session = await _load_session(db, meeting_id, session_id)
    if session.started_by != actor.user_id:
        raise MeetingForbiddenError("رفع التسجيل لصاحب الجلسة فقط")
    if session.status != RECORDING_SESSION_ACTIVE:
        raise MeetingInvalidStateError("جلسة التسجيل هذه انتهت")
    if not content:
        raise MeetingValidationError("القطعة فارغة")
    if len(content) > MAX_CHUNK_BYTES:
        raise MeetingValidationError("حجم القطعة أكبر من المسموح")
    if seq < 0 or seq > session.last_seq + 1:
        raise MeetingValidationError(f"ترتيب القطع غير صحيح — المتوقع {session.last_seq + 1}")
    is_new = seq == session.last_seq + 1
    if is_new and session.total_bytes + len(content) > MAX_SESSION_BYTES:
        raise MeetingValidationError("التسجيل تجاوز الحجم الأقصى — أوقفه وابدأ تسجيلًا جديدًا")

    await storage_client.upload_object(_chunk_path(session, seq), content, content_type="application/octet-stream")
    if is_new:
        session.last_seq = seq
        session.total_bytes += len(content)
    session.last_chunk_at = datetime.now(UTC)
    await db.commit()
    return session


async def stop_session(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, session_id: uuid.UUID
) -> tuple[MeetingRecordingSession, RecordingState]:
    """
    الهدف: إيقاف التسجيل ودمجه (زر "إيقاف").
    الصلاحية: meetings.record_audio. لو الجلسة منتهية أصلًا (دمجها المجدوِل) ترجع كما هي.
    """
    meeting = await load_meeting(db, meeting_id)
    await _require_access(
        db, actor, meeting.committee, "meetings.record_audio", "إيقاف التسجيل لرئيس اللجنة فقط"
    )
    session = await _load_session(db, meeting.meeting_id, session_id)
    if session.status == RECORDING_SESSION_ACTIVE:
        session = await _finalize(db, session)
    state = RecordingState(active=False)
    await _publish_state(meeting.meeting_id, state)
    return session, state


async def get_state(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> RecordingState:
    """حالة التسجيل الحالية (لمؤشر "جاري التسجيل") — meetings.join."""
    meeting = await load_meeting(db, meeting_id)
    await _require_access(
        db, actor, meeting.committee, "meetings.join", "ليست لديك صلاحية الوصول لهذا الاجتماع"
    )
    session = await _active_session(db, meeting.meeting_id)
    return _state_of(session) if session else RecordingState(active=False)


async def finalize_stale_sessions(db: AsyncSession) -> list[uuid.UUID]:
    """
    الهدف (المجدوِل): دمج الجلسات "اليتيمة" — صفحة الرئيس انقفلت/انقطع النت بدون إيقاف.
    المخرجات: أرقام الاجتماعات اللي انقفل تسجيلها (للبث).
    الأخطاء: لا ترمي — فشل جلسة يُسجَّل وتُعاد المحاولة بالدورة الجاية.
    """
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(MeetingRecordingSession).where(MeetingRecordingSession.status == RECORDING_SESSION_ACTIVE)
        )
    ).scalars().all()
    closed: list[uuid.UUID] = []
    for session in rows:
        last = session.last_chunk_at
        stale = (last is not None and now - last > STALE_AFTER) or (
            last is None and now - session.started_at > EMPTY_STALE_AFTER
        )
        if not stale:
            continue
        try:
            await _finalize(db, session)
            await _publish_state(session.meeting_id, RecordingState(active=False))
            closed.append(session.meeting_id)
        except Exception:  # noqa: BLE001 — نعيد المحاولة بالدورة الجاية
            await db.rollback()
            logger.exception("تعذّر دمج جلسة تسجيل يتيمة (session=%s)", session.session_id)
    return closed
