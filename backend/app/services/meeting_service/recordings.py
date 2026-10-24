"""
التسجيل الصوتي للاجتماع + مسودة المحضر المولَّدة بالذكاء الاصطناعي.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import gemini_client, storage_client
from app.models.meeting_draft import MeetingDraft, MeetingDraftStatus, MeetingRecording
from app.models.user import User
from app.services.meeting_service.access import (
    _access_flags,
    _require_access,
    _require_any_access,
)
from app.services.meeting_service.errors import (
    DraftNotFoundError,
    MeetingForbiddenError,
    MeetingValidationError,
    RecordingNotFoundError,
)
from app.services.meeting_service.loading import _all_committee_members, load_committee, load_meeting


# ============================== التسجيل الصوتي + المسودة (AI) ==============================
# راجعي رأس db/migrations/0025_meeting_recordings_and_drafts.sql للتصميم
# الكامل الموثّق (صلاحيات meetings.record_audio/draft.summarize/draft.view
# مزروعة أصلًا بكتالوج الصلاحيات منذ 0006).
#
# تحديث صلاحيات 2026-09-21 (بلاغ المستخدمة): meetings.summary.view —
# كانت محجوزة "لعرض ملخّص مبسّط لعموم الأعضاء بمرحلة لاحقة" فقط بدون أي
# إنفاذ فعلي — صارت الآن مفعَّلة فعليًا (راجعي get_latest_recording/
# get_draft أدناه): من يملكها (عادة دور "عضو اللجنة") يقدر يعرض التسجيل
# الصوتي والمسودة كاملة (بما فيها التفريغ الصوتي full_transcript) تمامًا
# مثل من يملك meetings.draft.view (عادة دور "رئيس اللجنة"). الاستثناء
# الوحيد المتعمَّد: قسم "البنود المستخرجة" (list_extracted_items) يبقى
# يتطلب meetings.draft.view حصرًا — عضو اللجنة العادي لا يراه، رئيس
# اللجنة فقط (ومن يملك صلاحية نظامية معادلة).



async def upload_recording(
    db: AsyncSession,
    *,
    actor: User,
    meeting_id: uuid.UUID,
    file_name: str,
    mime_type: str,
    content: bytes,
    duration_seconds: int | None = None,
) -> MeetingRecording:
    """يتطلب meetings.record_audio. لا يمنع تكرار الرفع لنفس الاجتماع عمدًا
    (راجعي تعليق الجدول بالـmigration) — أحدث تسجيل هو المعتمَد ضمنيًا
    عند توليد المسودة (get_latest_recording أدناه)."""
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_access(
        db,
        actor,
        committee,
        "meetings.record_audio",
        "ليست لديك صلاحية تسجيل هذا الاجتماع صوتيًا",
    )

    recording_id = uuid.uuid4()
    storage_path = f"meeting-recordings/{meeting_id}/{recording_id}_{file_name}"
    await storage_client.upload_object(storage_path, content, content_type=mime_type)

    recording = MeetingRecording(
        recording_id=recording_id,
        meeting_id=meeting_id,
        storage_path=storage_path,
        file_name=file_name,
        mime_type=mime_type,
        file_size_bytes=len(content),
        duration_seconds=duration_seconds,
        recorded_by=actor.user_id,
    )
    db.add(recording)
    await db.commit()
    await db.refresh(recording)
    return recording


async def get_latest_recording(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> MeetingRecording:
    """يتطلب meetings.record_audio أو meetings.draft.view أو
    meetings.summary.view.

    توسعة 2026-09-21 (بلاغ المستخدمة): أعضاء اللجنة العاديون — وليس
    رئيسها فقط — يجب أن يقدروا يستمعون لتسجيل اجتماعات لجنتهم ويحمّلونه،
    تمامًا مثل الرئيس. meetings.summary.view كانت محجوزة "لمرحلة لاحقة"
    منذ 0006_roles_permissions.sql بدون أي إنفاذ فعلي — هذه هي تلك
    المرحلة: تُمنح لدور "عضو اللجنة" (بخلاف meetings.record_audio/
    draft.view اللي تبقى لدور "رئيس اللجنة" كالسابق). راجعي get_draft
    أدناه لنفس التوسعة على المسودة/التفريغ الصوتي — قسم البنود المستخرجة
    (list_extracted_items) عمدًا لم يُدرَج هنا، يبقى رئيس اللجنة حصرًا."""
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_any_access(
        db,
        actor,
        committee,
        ["meetings.record_audio", "meetings.draft.view", "meetings.summary.view"],
        "ليست لديك صلاحية الوصول لتسجيل هذا الاجتماع",
    )

    result = await db.execute(
        select(MeetingRecording)
        .where(MeetingRecording.meeting_id == meeting_id, MeetingRecording.deleted_at.is_(None))
        .order_by(MeetingRecording.recorded_at.desc())
        .limit(1)
    )
    recording = result.scalar_one_or_none()
    if recording is None:
        raise RecordingNotFoundError("لا يوجد تسجيل صوتي لهذا الاجتماع بعد")
    return recording


async def download_recording(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> tuple[MeetingRecording, bytes]:
    """يتطلب meetings.record_audio — يرجع محتوى الملف الصوتي الفعلي (أحدث تسجيل)."""
    recording = await get_latest_recording(db, actor=actor, meeting_id=meeting_id)
    content = await storage_client.download_object(recording.storage_path)
    return recording, content


async def _all_recordings(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> list[MeetingRecording]:
    """
    تحديث 2026-09-16 (طلب لاما — "بحال الرئيس شغّل التسجيل وطفّاه أكثر من
    مرة بنفس الاجتماع، تجمع كل الكلام؟"): كل تسجيلات الاجتماع بترتيبها
    الزمني الصاعد (وليس آخر واحد فقط كـget_latest_recording أعلاه) —
    تُستخدَم حصرًا من generate_draft أدناه لتوليد مسودة تغطي كل المقاطع
    معًا بدل أحدثها فقط. نفس صلاحية get_latest_recording بالضبط
    (meetings.record_audio) — من يقدر يسجّل يقدر يراجع كل مقاطعه.
    """
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_access(
        db, actor, committee, "meetings.record_audio", "ليست لديك صلاحية الوصول لتسجيل هذا الاجتماع"
    )

    result = await db.execute(
        select(MeetingRecording)
        .where(MeetingRecording.meeting_id == meeting_id, MeetingRecording.deleted_at.is_(None))
        .order_by(MeetingRecording.recorded_at.asc())
    )
    recordings = list(result.scalars().unique().all())
    if not recordings:
        raise RecordingNotFoundError("لا يوجد تسجيل صوتي لهذا الاجتماع بعد")
    return recordings


async def generate_draft(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> MeetingDraft:
    """يتطلب meetings.draft.summarize (FR-AI-001) — بشرط وجود تسجيل صوتي
    فعلي مسبقًا (MeetingValidationError إن لم يوجد، مطابقةً لنص المتطلب
    حرفيًا: "بشرط أن يكون التسجيل الصوتي متاح"). العملية مزامنة حاليًا
    (await مباشر لـgemini_client، بدون Background Job/Queue) — قرار
    مقصود لتبسيط هذي المرحلة الأولى؛ قابل للتحويل لاحقًا لو صارت مدة
    الانتظار مزعجة بالواجهة لاجتماعات طويلة جدًا."""
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    await _require_access(
        db,
        actor,
        committee,
        "meetings.draft.summarize",
        "ليست لديك صلاحية تحويل تسجيل هذا الاجتماع إلى مسودة",
    )

    try:
        recordings = await _all_recordings(db, actor=actor, meeting_id=meeting_id)
    except RecordingNotFoundError as exc:
        raise MeetingValidationError(
            "لا يمكن توليد مسودة بدون تسجيل صوتي — يجب رفع تسجيل الاجتماع أولًا"
        ) from exc

    # تحديث 2026-09-16 (طلب لاما): recording_id يبقى عمود مرجعي واحد
    # (أحدث مقطع) — التوليد الفعلي أدناه يستخدم كل مقاطع recordings معًا
    # بغض النظر عن هذا المرجع (راجعي gemini_client.generate_meeting_draft).
    latest_recording = recordings[-1]
    result = await db.execute(select(MeetingDraft).where(MeetingDraft.meeting_id == meeting_id))
    draft = result.scalar_one_or_none()
    if draft is None:
        draft = MeetingDraft(
            meeting_id=meeting_id,
            recording_id=latest_recording.recording_id,
            generated_by=actor.user_id,
        )
        db.add(draft)
    else:
        draft.recording_id = latest_recording.recording_id
        draft.generated_by = actor.user_id
    draft.status = MeetingDraftStatus.processing
    draft.error_message = None
    await db.commit()
    await db.refresh(draft)

    # أعضاء اللجنة يُحمَّلون هنا صراحةً (وليس مع الاجتماع) — هذا المسار
    # الوحيد بالملف الذي يحتاجهم.
    committee_with_members = await load_committee(db, meeting.committee_id, with_members=True)
    participant_names = [member.full_name for member in _all_committee_members(committee_with_members)]
    audio_segments = [
        gemini_client.AudioSegment(
            content=await storage_client.download_object(r.storage_path),
            mime_type=r.mime_type,
            file_name=r.file_name,
        )
        for r in recordings
    ]

    try:
        generated = await gemini_client.generate_meeting_draft(
            meeting_title=meeting.title,
            participant_names=participant_names,
            audio_segments=audio_segments,
        )
    except gemini_client.GeminiError as exc:
        draft.status = MeetingDraftStatus.failed
        draft.error_message = str(exc)
        await db.commit()
        await db.refresh(draft)
        return draft

    draft.full_transcript = generated["full_transcript"]
    draft.summary = generated["summary"]
    draft.decisions = generated["decisions"]
    draft.action_items = generated["action_items"]
    draft.key_points = generated["key_points"]
    draft.recommendations = generated["recommendations"]
    draft.open_items = generated["open_items"]
    draft.compliance_notes = generated["compliance_notes"]
    draft.status = MeetingDraftStatus.completed
    draft.error_message = None
    draft.generated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(draft)
    return draft


async def get_draft(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID
) -> tuple[MeetingDraft, bool, bool, bool]:
    """
    تحديث 2026-09-16 (طلب لاما — تفصيل صلاحيات عرض المسودة إلى ثلاث):
    كانت meetings.draft.view وحدها تتحكم بعرض المسودة كلها دفعة واحدة —
    الآن يكفي امتلاك meetings.draft.view (وصول كامل، رئيس اللجنة عادةً)
    **أو** إحدى الصلاحيتين الجزئيتين (meetings.transcript.view لحقل
    full_transcript، meetings.summary.view لحقل summary) للوصول أصلًا —
    403 فقط إن لم يملك أيًّا من الثلاث. الحقول التي لا يملك صلاحيتها
    تحديدًا تُخفى (redact) بمستوى الـAPI (راجعي app/api/v1/meetings.py::
    _draft_out) بالاعتماد على القيم الثلاث المُعادة هنا — بقية حقول
    المسودة (القرارات/المهام/نقاط مهمة...المستخرَجة آليًا) تبقى حصرًا لمن
    يملك meetings.draft.view الكاملة تحديدًا (القيمة الرابعة can_full —
    لم تطلب لاما توسيع هذه الحقول تحديدًا لعضو اللجنة، فمنح
    meetings.transcript.view/meetings.summary.view وحدهما لا يكفي
    لرؤيتها، تفاديًا لتسريب بيانات لم تُطلَب).

    ملاحظة دمج 2026-09-21: هذا منطق لاما بالكامل (أدق من محاولتي الأولى
    بفرع feat/committee-member-recording-draft-access اللي كانت تمنح
    الوصول الكامل لأي حامل meetings.summary.view) — استُبدلت به عند حل
    تعارض الدمج مع main، وطلب get_latest_recording أعلاه (توسعة منفصلة
    لملف التسجيل الصوتي الخام نفسه، لم تلمسه لاما) ظل كما هو.
    """
    meeting = await load_meeting(db, meeting_id)
    committee = meeting.committee
    # نفس منطق الصلاحيات الثلاث بالضبط، لكن أكواد دور اللجنة تُجلب مرة
    # واحدة بدل استعلام لكل كود (راجعي access._access_flags).
    flags = await _access_flags(
        db, actor, committee, ["meetings.draft.view", "meetings.transcript.view", "meetings.summary.view"]
    )
    can_full = flags["meetings.draft.view"]
    can_transcript = can_full or flags["meetings.transcript.view"]
    can_summary = can_full or flags["meetings.summary.view"]
    if not (can_full or can_transcript or can_summary):
        raise MeetingForbiddenError("ليست لديك صلاحية عرض مسودة هذا الاجتماع")

    result = await db.execute(select(MeetingDraft).where(MeetingDraft.meeting_id == meeting_id))
    draft = result.scalar_one_or_none()
    if draft is None:
        raise DraftNotFoundError("لا توجد مسودة مولَّدة لهذا الاجتماع بعد")
    return draft, can_transcript, can_summary, can_full

