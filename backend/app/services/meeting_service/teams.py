"""
الهدف:
ربط الاجتماعات عن بعد (mode='remote') بـMicrosoft Teams — قواعد العمل
المعتمدة (لاما 2026-11-02، راجعي رأس
db/migrations/0041_meetings_teams_integration.sql):

1) إنشاء اجتماع remote ⇒ يُنشأ اجتماع Teams باسم حساب المنظِّم
   (TEAMS_ORGANIZER_EMAIL)، رئيس اللجنة co-organizer وبقية الأعضاء attendees.
   فشل Teams ⇒ يُرفض إنشاء الاجتماع كاملًا.
2) تعديل الاجتماع ⇒ مزامنة Teams (تعديل/حذف/إنشاء حسب تغيّر النوع والموعد).
   فشل Teams ⇒ يُرفض التعديل.
3) تمديد الاجتماع أو حذفه ⇒ مزامنة Teams "بأفضل جهد": فشلها يُسجَّل
   تحذيرًا ولا يمنع العملية (تمديد اجتماع منعقد أو إلغاء اجتماع أهم من
   مزامنة ثانوية — رابط قديم لا يضر).
4) الانضمام ⇒ رابط Teams للمشاركين فقط (meetings.join) — يُفحص بالباك-إند.
5) المسودة لاجتماع remote مربوط بـTeams ⇒ من تفريغ Teams الرسمي بدل ملف صوتي.
6) تسجيلات Teams ⇒ تُعرض وتُبث عبر الباك-إند لأصحاب meetings.record_audio،
   بلا تخزين نسخة عندنا (قرار مؤقت حتى تحديد مدة الاحتفاظ مع الإدارة).

لو التكامل غير مهيّأ بالبيئة (teams_client.is_configured() = False) تُنشأ
الاجتماعات عن بعد بلا رابط Teams ويبقى مسار Agora القديم كما هو — بيئات
التطوير لا تتعطل بغياب المفاتيح.

الاعتماديات: app.core.teams_client (Graph)، app.core.teams_transcript،
app.core.gemini_client، وrecordings._begin_draft (تهيئة صف المسودة).
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import gemini_client, teams_client, teams_transcript
from app.models.committee import Committee
from app.models.meeting import Meeting, MeetingMode, MeetingStatus
from app.models.meeting_draft import MeetingDraft, MeetingDraftSource, MeetingDraftStatus
from app.models.user import User
from app.services import audit_service
from app.services.meeting_service.access import _require_access
from app.services.meeting_service.errors import MeetingInvalidStateError, MeetingValidationError
from app.services.meeting_service.loading import _all_committee_members, load_committee, load_meeting

logger = logging.getLogger(__name__)


# ============================== المشاركون ==============================


async def _teams_participants(committee: Committee, *, organizer_id: str) -> list[teams_client.TeamsParticipant]:
    """
    الهدف: تحويل أعضاء اللجنة إلى مشاركي اجتماع Teams.

    المدخلات:
    - committee: اللجنة محمّلة بأعضائها (load_committee(with_members=True)).
    - organizer_id: Object ID لحساب المنظِّم — يُستبعد من القائمة (هو المالك أصلًا).

    المخرجات: قائمة TeamsParticipant — رئيس اللجنة 'coorganizer' (يسجّل ويُدخل
    من الـLobby)، وبقية الأعضاء 'attendee'.

    قواعد:
    - العضو الذي لا يوجد بريده في Microsoft 365 للشركة يُتجاهل هنا (لا يُضاف
      كمشارك رسمي) — يبقى قادرًا على الدخول بالرابط كضيف عبر الـLobby.
    - البحث عن الأعضاء بالتوازي (asyncio.gather) لتقليل زمن الانتظار.

    التأثيرات الجانبية: استدعاءات Graph للقراءة فقط (User.Read.All).
    الأخطاء: TeamsError لو فشل الاتصال بـGraph.
    """
    members = _all_committee_members(committee)
    ids = await asyncio.gather(*(teams_client.get_user_id(member.email) for member in members))
    participants: list[teams_client.TeamsParticipant] = []
    for member, entra_id in zip(members, ids):
        if entra_id is None or entra_id == organizer_id:
            if entra_id is None:
                logger.info("Teams: committee member %s not found in Microsoft 365 — not added as participant", member.user_id)
            continue
        role = "coorganizer" if member.user_id == committee.chair_user_id else "attendee"
        participants.append(teams_client.TeamsParticipant(user_id=entra_id, upn=member.email, role=role))
    return participants


def _clear_teams_fields(meeting: Meeting) -> None:
    """يفرّغ أعمدة teams_* الثلاثة معًا (القيد chk_meetings_teams_fields_together
    يمنع تفريغ بعضها فقط) — بعد حذف اجتماع Teams عند التحويل لحضوري."""
    meeting.teams_meeting_id = None
    meeting.teams_join_url = None
    meeting.teams_organizer_id = None


async def _create_and_attach(meeting: Meeting, committee: Committee) -> None:
    """
    ينشئ اجتماع Teams ويعبّئ أعمدة teams_* بالكائن (بلا commit).
    المدخلات: meeting (العنوان/الموعد)، committee محمّلة بأعضائها.
    التأثيرات الجانبية: استدعاءات Graph (بحث المستخدمين + إنشاء الاجتماع).
    الأخطاء: TeamsError.
    """
    organizer_id = await teams_client.get_organizer_id()
    participants = await _teams_participants(committee, organizer_id=organizer_id)
    created = await teams_client.create_online_meeting(
        organizer_id=organizer_id,
        subject=meeting.title,
        start=meeting.scheduled_at,
        end=meeting.scheduled_end_at or meeting.scheduled_at,
        participants=participants,
    )
    meeting.teams_meeting_id = created.meeting_id
    meeting.teams_join_url = created.join_url
    meeting.teams_organizer_id = uuid.UUID(organizer_id)


# ============================== دورة حياة الاجتماع ==============================


async def attach_to_new_meeting(meeting: Meeting, committee: Committee) -> bool:
    """
    الهدف: إنشاء اجتماع Teams لاجتماع جديد قبل حفظه (قاعدة 1).

    المدخلات:
    - meeting: كائن الاجتماع الجديد (لم يُحفظ بعد) — يُقرأ منه العنوان/الموعد/النوع.
    - committee: اللجنة محمّلة بأعضائها.

    المخرجات: True لو أُنشئ اجتماع Teams (الطبقة المستدعية مسؤولة عن حذفه
    لو فشل حفظ الاجتماع بعدها — rollback_new_meeting)، False لو لا حاجة
    (اجتماع حضوري، أو التكامل غير مهيّأ).

    التأثيرات الجانبية: يعبّئ meeting.teams_* + ينشئ اجتماعًا فعليًا بـTeams.
    الأخطاء: TeamsError ⇒ الطبقة المستدعية ترفض إنشاء الاجتماع.
    """
    if meeting.mode != MeetingMode.remote or not teams_client.is_configured():
        return False
    await _create_and_attach(meeting, committee)
    return True


def teams_link_of(meeting: Meeting) -> tuple[str, str] | None:
    """(organizer_id, teams_meeting_id) الحاليان للاجتماع، أو None لو غير مربوط.
    تُلتقط القيم قبل أي commit/rollback قد يُنهي صلاحية كائن الجلسة."""
    if not meeting.teams_meeting_id or not meeting.teams_organizer_id:
        return None
    return str(meeting.teams_organizer_id), meeting.teams_meeting_id


async def rollback_new_meeting(link: tuple[str, str] | None) -> None:
    """
    الهدف: تنظيف "بأفضل جهد" لاجتماع Teams أُنشئ ثم فشل حفظ الاجتماع بقاعدتنا
    (حتى لا يبقى اجتماع Teams يتيم بلا سجل عندنا).
    المدخلات: link من teams_link_of (مُلتقط قبل محاولة الحفظ).
    الأخطاء: لا ترمي — الفشل يُسجَّل فقط (الخطأ الأصلي هو الأهم للمستخدم).
    """
    if link is None:
        return
    organizer_id, teams_meeting_id = link
    try:
        await teams_client.delete_online_meeting(organizer_id=organizer_id, meeting_id=teams_meeting_id)
    except teams_client.TeamsError:
        logger.warning("Teams: failed to clean up orphan online meeting %s", teams_meeting_id, exc_info=True)


async def sync_after_update(db: AsyncSession, meeting: Meeting, *, details_changed: bool) -> bool:
    """
    الهدف: مزامنة Teams بعد تعديل الاجتماع وقبل حفظه (قاعدة 2).

    المدخلات:
    - meeting: الاجتماع بعد تطبيق التعديلات عليه (قبل commit).
    - details_changed: هل تغيّر العنوان أو الموعد (يستدعي PATCH لـTeams).

    الحالات:
    - remote بلا Teams (تحوّل من حضوري، أو اجتماع قديم قبل التكامل) ⇒ إنشاء.
    - remote مربوط + تغيّرت التفاصيل ⇒ تعديل (ولو حُذف من Teams مباشرة ⇒ إنشاء جديد).
    - حضوري لا يزال مربوطًا (تحوّل من remote) ⇒ حذف من Teams وتفريغ الأعمدة.

    المخرجات: True لو أُنشئ اجتماع Teams جديد بهذه العملية (لتنظيفه لو فشل الحفظ).
    التأثيرات الجانبية: استدعاءات Graph + تعديل أعمدة teams_* بالكائن.
    الأخطاء: TeamsNotConfiguredError لو الاجتماع مربوط بـTeams والتكامل
    غير مهيّأ (لا نترك اجتماع Teams يتيمًا بصمت)، TeamsError لأي فشل آخر.
    """
    linked = meeting.teams_meeting_id is not None
    if meeting.mode == MeetingMode.in_person:
        if not linked:
            return False
        await teams_client.delete_online_meeting(
            organizer_id=str(meeting.teams_organizer_id), meeting_id=meeting.teams_meeting_id
        )
        _clear_teams_fields(meeting)
        return False

    if not teams_client.is_configured():
        if linked and details_changed:
            raise teams_client.TeamsNotConfiguredError(
                "هذا الاجتماع مربوط بـMicrosoft Teams لكن إعدادات التكامل غير مكتملة — لا يمكن مزامنة التعديل"
            )
        return False

    committee = await load_committee(db, meeting.committee_id, with_members=True)
    if not linked:
        await _create_and_attach(meeting, committee)
        return True
    if not details_changed:
        return False

    organizer_id = str(meeting.teams_organizer_id)
    participants = await _teams_participants(committee, organizer_id=organizer_id)
    try:
        await teams_client.update_online_meeting(
            organizer_id=organizer_id,
            meeting_id=meeting.teams_meeting_id,
            subject=meeting.title,
            start=meeting.scheduled_at,
            end=meeting.scheduled_end_at or meeting.scheduled_at,
            participants=participants,
        )
    except teams_client.TeamsNotFoundError:
        logger.warning("Teams: online meeting %s missing on update — recreating", meeting.teams_meeting_id)
        await _create_and_attach(meeting, committee)
        return True
    return False


async def sync_after_extend(meeting: Meeting) -> None:
    """
    الهدف: تحديث وقت نهاية اجتماع Teams بعد التمديد (قاعدة 3 — بأفضل جهد).
    ملاحظة: Teams لا يُنهي الاجتماع تلقائيًا عند endDateTime أصلًا، فالتحديث
    هنا لاتساق البيانات فقط — فشله لا يمنع التمديد.
    الأخطاء: لا ترمي.
    """
    if not meeting.teams_meeting_id or not teams_client.is_configured():
        return
    try:
        await teams_client.update_online_meeting(
            organizer_id=str(meeting.teams_organizer_id),
            meeting_id=meeting.teams_meeting_id,
            subject=meeting.title,
            start=meeting.scheduled_at,
            end=meeting.scheduled_end_at or meeting.scheduled_at,
            participants=None,  # التمديد لا يغيّر المشاركين — لا نرسل الحقل أصلًا
        )
    except teams_client.TeamsError:
        logger.warning("Teams: failed to sync extension for %s", meeting.teams_meeting_id, exc_info=True)


async def sync_after_delete(meeting: Meeting) -> None:
    """
    الهدف: حذف اجتماع Teams بعد حذف الاجتماع عندنا (قاعدة 3 — بأفضل جهد).
    أعمدة teams_* تبقى كما هي على السجل المحذوف (Soft Delete) للتدقيق.
    الأخطاء: لا ترمي.
    """
    if not meeting.teams_meeting_id or not teams_client.is_configured():
        return
    try:
        await teams_client.delete_online_meeting(
            organizer_id=str(meeting.teams_organizer_id), meeting_id=meeting.teams_meeting_id
        )
    except teams_client.TeamsError:
        logger.warning("Teams: failed to delete online meeting %s", meeting.teams_meeting_id, exc_info=True)


# ============================== الانضمام ==============================


def _require_linked(meeting: Meeting) -> None:
    """يرمي MeetingInvalidStateError (409) لو الاجتماع حضوري أو غير مربوط بـTeams."""
    if meeting.mode != MeetingMode.remote:
        raise MeetingInvalidStateError("هذا اجتماع حضوري، لا يملك اجتماع Teams")
    if not meeting.teams_meeting_id:
        raise MeetingInvalidStateError("هذا الاجتماع غير مربوط بـMicrosoft Teams")


async def get_join_url(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> str:
    """
    الهدف: رابط الانضمام لاجتماع Teams (قاعدة 4).

    المدخلات: actor (المستخدم الحالي)، meeting_id.
    المخرجات: رابط Teams.
    الصلاحيات: meetings.join (System Role أو Committee Role — نفس الانضمام عبر Agora).
    قواعد: اجتماع remote مربوط بـTeams، ولم ينتهِ بعد.
    التأثيرات الجانبية: يسجّل started_at أول مرة + سطر تدقيق join، ثم commit.
    الأخطاء: MeetingNotFoundError، MeetingForbiddenError، MeetingInvalidStateError.
    """
    meeting = await load_meeting(db, meeting_id)
    await _require_access(
        db, actor, meeting.committee, "meetings.join", "ليست لديك صلاحية الانضمام لهذا الاجتماع"
    )
    _require_linked(meeting)
    if meeting.status == MeetingStatus.finished:
        raise MeetingInvalidStateError("انتهى هذا الاجتماع بالفعل")

    if meeting.started_at is None:
        meeting.started_at = datetime.now(UTC)
    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="join",
        target_type="meeting",
        target_id=meeting.meeting_id,
        metadata={"provider": "teams"},
    )
    join_url = meeting.teams_join_url
    await db.commit()
    return join_url


# ============================== التسجيلات ==============================


async def _load_for_recordings(db: AsyncSession, actor: User, meeting_id: uuid.UUID) -> Meeting:
    """
    تحميل الاجتماع + فحص meetings.record_audio + التأكد من ربطه بـTeams —
    مشتركة بين list_recordings وopen_recording.
    الأخطاء: MeetingNotFoundError، MeetingForbiddenError، MeetingInvalidStateError.
    """
    meeting = await load_meeting(db, meeting_id)
    await _require_access(
        db, actor, meeting.committee, "meetings.record_audio", "ليست لديك صلاحية الوصول لتسجيل هذا الاجتماع"
    )
    _require_linked(meeting)
    return meeting


async def list_recordings(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID
) -> list[teams_client.TeamsArtifact]:
    """
    الهدف: قائمة تسجيلات Teams لهذا الاجتماع (قاعدة 6).
    الصلاحيات: meetings.record_audio (نفس صلاحية التسجيل الصوتي الحالية).
    المخرجات: قائمة (فارغة لو لم يُسجَّل، أو انتهت مدة احتفاظ Teams).
    الأخطاء: MeetingForbiddenError، MeetingInvalidStateError، TeamsError.
    """
    meeting = await _load_for_recordings(db, actor, meeting_id)
    return await teams_client.list_recordings(
        organizer_id=str(meeting.teams_organizer_id), meeting_id=meeting.teams_meeting_id
    )


async def open_recording(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, recording_id: str
) -> teams_client.RecordingStream:
    """
    الهدف: فتح تسجيل Teams للبث للمستخدم عبر الباك-إند (قاعدة 6).
    أمان: المسار بـGraph مبني من teams_meeting_id المخزّن عندنا لهذا الاجتماع
    (لا من مدخلات المستخدم)، فلا يمكن الوصول لتسجيل اجتماع آخر بتمرير
    recording_id لا ينتمي له — Graph يرجع 404.
    الأخطاء: MeetingForbiddenError، MeetingInvalidStateError، TeamsNotFoundError، TeamsError.
    """
    meeting = await _load_for_recordings(db, actor, meeting_id)
    return await teams_client.open_recording_stream(
        organizer_id=str(meeting.teams_organizer_id),
        meeting_id=meeting.teams_meeting_id,
        recording_id=recording_id,
    )


# ============================== المسودة من التفريغ ==============================


async def generate_draft_from_transcript(db: AsyncSession, *, actor: User, meeting: Meeting) -> MeetingDraft:
    """
    الهدف: توليد مسودة اجتماع remote مربوط بـTeams من تفريغه الرسمي (قاعدة 5).

    المدخلات: actor (فُحصت صلاحيته meetings.draft.summarize مسبقًا بـgenerate_draft)،
    meeting (محمّل).

    الخطوات:
    1) سحب كل تفريغات الاجتماع من Teams ودمجها بالترتيب الزمني.
    2) لا تفريغ ⇒ MeetingValidationError (قبل إنشاء/تعديل أي صف مسودة).
    3) صف المسودة ⇒ processing (source=teams_transcript، recording_id فارغ).
    4) full_transcript من التفريغ مباشرة، وبقية الحقول من Gemini.
    5) فشل Gemini ⇒ status='failed' + error_message (نفس سلوك مسار الصوت).

    المخرجات: المسودة بعد commit.
    التأثيرات الجانبية: استدعاءات Graph + Gemini + كتابة meeting_drafts.
    الأخطاء: MeetingValidationError (لا تفريغ)، TeamsError (فشل Graph).
    """
    from app.services.meeting_service.recordings import _begin_draft, _fill_draft

    organizer_id = str(meeting.teams_organizer_id)
    transcripts = await teams_client.list_transcripts(organizer_id=organizer_id, meeting_id=meeting.teams_meeting_id)
    entries: list[dict[str, str]] = []
    for transcript in transcripts:
        vtt = await teams_client.get_transcript_vtt(
            organizer_id=organizer_id, meeting_id=meeting.teams_meeting_id, transcript_id=transcript.artifact_id
        )
        entries.extend(teams_transcript.parse_vtt(vtt))
    if not entries:
        raise MeetingValidationError(
            "لا يوجد تفريغ لهذا الاجتماع في Teams بعد — تأكد من تشغيل التفريغ أثناء الاجتماع، "
            "وانتظر بضع دقائق بعد انتهائه ثم أعد المحاولة"
        )

    draft = await _begin_draft(
        db, meeting_id=meeting.meeting_id, actor=actor, source=MeetingDraftSource.teams_transcript, recording_id=None
    )

    committee_with_members = await load_committee(db, meeting.committee_id, with_members=True)
    participant_names = [member.full_name for member in _all_committee_members(committee_with_members)]
    try:
        generated = await gemini_client.generate_meeting_draft_from_transcript(
            meeting_title=meeting.title,
            participant_names=participant_names,
            transcript_text=teams_transcript.to_plain_text(entries),
        )
    except gemini_client.GeminiError as exc:
        draft.status = MeetingDraftStatus.failed
        draft.error_message = str(exc)
        await db.commit()
        await db.refresh(draft)
        return draft

    return await _fill_draft(db, draft, {**generated, "full_transcript": entries})
