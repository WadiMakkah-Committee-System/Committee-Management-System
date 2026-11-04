"""
اختبارات الرجوع لـAgora (قرار لاما 2026-11-04):
- الانضمام لغرفة Agora: الصلاحيات، الحالات المرفوضة، والتوكن مربوط بالمستخدم.
- الاجتماعات الجديدة ما تُنشأ بـTeams إلا لو MEETING_PROVIDER=teams.
- التسجيل الصوتي على دفعات: البدء/الرفع/الإيقاف، الترتيب، الصلاحيات، الدمج،
  ودمج الجلسات اليتيمة تلقائيًا (صفحة الرئيس انقفلت).
- الترجمة النصية المجانية: كل عضو يحفظ كلامه هو، والمتحدث يُفرض بالباك-إند.

التخزين مموَّه (conftest._fake_storage) — نتحقق من المحتوى المدموج فعليًا.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core import teams_client
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.meeting_recording_session import MeetingRecordingSession
from app.models.meeting_insights import MeetingTranscriptSegment
from app.models.user import User
from app.services import meeting_service

from tests.test_meetings import _create_approved_committee, _grant_committee_role_permissions


@pytest.fixture(autouse=True)
def _agora_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AGORA_APP_ID", "test-app-id")
    monkeypatch.setattr(settings, "AGORA_APP_CERTIFICATE", "0123456789abcdef0123456789abcdef")
    monkeypatch.setattr(settings, "MEETING_PROVIDER", "agora")


def _slot(days: int = 3) -> tuple[str, str]:
    start = (datetime.now(UTC) + timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
    return start.isoformat(), (start + timedelta(hours=1)).isoformat()


async def _setup(client: AsyncClient, auth_headers, roles_by_name, *, mode: str = "remote") -> dict:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    await _grant_committee_role_permissions(
        ["meetings.join", "meetings.record_audio", "meetings.draft.view"], slug="chair"
    )
    await _grant_committee_role_permissions(["meetings.join"], slug="member")
    start, end = _slot()
    create = await client.post(
        "/api/v1/meetings",
        json={
            "committee_id": ctx["committee_id"],
            "title": "اجتماع Agora",
            "mode": mode,
            "scheduled_at": start,
            "scheduled_end_at": end,
            **({"location": "قاعة 1"} if mode == "in_person" else {}),
        },
        headers=ctx["chair_headers"],
    )
    assert create.status_code == 201, create.text
    ctx["meeting_id"] = create.json()["meeting_id"]
    ctx["meeting"] = create.json()
    return ctx


# ============================== الانضمام ==============================


async def test_join_returns_token_bound_to_user(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User
) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    response = await client.post(f"/api/v1/meetings/{ctx['meeting_id']}/agora/join", headers=ctx["member_headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["app_id"] == "test-app-id"
    assert body["channel"] == ctx["meeting_id"]
    # الحساب = user_id بالمنصة (مو من العميل) — كل جهاز يعرف هوية كل صوت.
    assert body["account"] == ctx["member_id"]
    assert body["token"] and body["expires_at"] > datetime.now(UTC).timestamp()


async def test_join_rejections(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, monkeypatch
) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    url = f"/api/v1/meetings/{ctx['meeting_id']}/agora/join"

    # مفاتيح Agora ناقصة ⇒ 503 واضح.
    monkeypatch.setattr(settings, "AGORA_APP_CERTIFICATE", "")
    missing = await client.post(url, headers=ctx["chair_headers"])
    assert missing.status_code == 503, missing.text


async def test_join_in_person_meeting_is_rejected(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User
) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name, mode="in_person")
    response = await client.post(f"/api/v1/meetings/{ctx['meeting_id']}/agora/join", headers=ctx["chair_headers"])
    assert response.status_code == 409, response.text


async def test_new_remote_meetings_skip_teams_unless_provider_is_teams(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, monkeypatch
) -> None:
    """مفاتيح Teams موجودة لكن MEETING_PROVIDER=agora ⇒ ما يُنادى Graph أبدًا."""
    for name, value in (
        ("TEAMS_TENANT_ID", "t"),
        ("TEAMS_CLIENT_ID", "c"),
        ("TEAMS_CLIENT_SECRET", "s"),
        ("TEAMS_ORGANIZER_EMAIL", "o@example.com"),
    ):
        monkeypatch.setattr(settings, name, value)

    async def must_not_be_called(**_kwargs):
        raise AssertionError("Teams Graph لازم ما يُستدعى بوضع Agora")

    monkeypatch.setattr(teams_client, "create_online_meeting", must_not_be_called)
    ctx = await _setup(client, auth_headers, roles_by_name)
    assert ctx["meeting"]["has_teams_meeting"] is False


# ============================== التسجيل على دفعات ==============================


async def _start(client: AsyncClient, ctx: dict, *, headers=None, mime: str = "audio/webm;codecs=opus"):
    return await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/recording-sessions",
        json={"mime_type": mime},
        headers=headers or ctx["chair_headers"],
    )


async def _chunk(client: AsyncClient, ctx: dict, session_id: str, seq: int, data: bytes, *, headers=None):
    return await client.put(
        f"/api/v1/meetings/{ctx['meeting_id']}/recording-sessions/{session_id}/chunks/{seq}",
        content=data,
        headers={**(headers or ctx["chair_headers"]), "Content-Type": "application/octet-stream"},
    )


async def test_chunked_recording_full_flow(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User
) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    meeting_id = ctx["meeting_id"]

    # العضو ما يقدر يبدأ التسجيل.
    assert (await _start(client, ctx, headers=ctx["member_headers"])).status_code == 403
    # صيغة غير صوتية مرفوضة.
    assert (await _start(client, ctx, mime="video/webm")).status_code == 400

    started = await _start(client, ctx)
    assert started.status_code == 201, started.text
    state = started.json()
    assert state["active"] is True and state["started_by"] == ctx["chair_id"]
    session_id = state["session_id"]

    # كل الحضور يشوفون "جاري التسجيل".
    seen = await client.get(f"/api/v1/meetings/{meeting_id}/recording-sessions/state", headers=ctx["member_headers"])
    assert seen.json()["active"] is True

    assert (await _chunk(client, ctx, session_id, 0, b"HEADER+part0|")).json()["last_seq"] == 0
    assert (await _chunk(client, ctx, session_id, 1, b"part1|")).json()["last_seq"] == 1
    # إعادة إرسال نفس القطعة (انقطاع لحظي) — مقبولة بدون تكرار.
    assert (await _chunk(client, ctx, session_id, 1, b"part1|")).json()["last_seq"] == 1
    # فجوة بالترتيب ⇒ مرفوضة.
    gap = await _chunk(client, ctx, session_id, 3, b"part3")
    assert gap.status_code == 400, gap.text
    # العضو ما يقدر يرفع لجلسة غيره.
    assert (await _chunk(client, ctx, session_id, 2, b"x", headers=ctx["member_headers"])).status_code == 403
    assert (await _chunk(client, ctx, session_id, 2, b"part2")).status_code == 200

    stopped = await client.post(
        f"/api/v1/meetings/{meeting_id}/recording-sessions/{session_id}/stop", headers=ctx["chair_headers"]
    )
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "finalized" and stopped.json()["recording_id"]

    # الملف النهائي = القطع مدموجة بالترتيب، ويدخل مسار التسجيل الحالي (المسودة).
    download = await client.get(f"/api/v1/meetings/{meeting_id}/recording/download", headers=ctx["chair_headers"])
    assert download.status_code == 200, download.text
    assert download.content == b"HEADER+part0|part1|part2"
    assert (await client.get(f"/api/v1/meetings/{meeting_id}/recording-sessions/state", headers=ctx["member_headers"])).json()["active"] is False

    # بعد الإيقاف ما يُقبل رفع.
    assert (await _chunk(client, ctx, session_id, 3, b"late")).status_code == 409


async def test_restart_finalizes_previous_session(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User
) -> None:
    """الرئيس انقطع ورجع وضغط تسجيل ⇒ الجلسة القديمة تنحفظ، وتبدأ جديدة (المقطعين للمسودة)."""
    ctx = await _setup(client, auth_headers, roles_by_name)
    first = (await _start(client, ctx)).json()["session_id"]
    await _chunk(client, ctx, first, 0, b"first")
    second = (await _start(client, ctx)).json()["session_id"]
    assert second != first
    async with AsyncSessionLocal() as db:
        old = (await db.execute(select(MeetingRecordingSession).where(MeetingRecordingSession.session_id == uuid.UUID(first)))).scalar_one()
    assert old.status == "finalized" and old.recording_id is not None


async def test_stale_session_is_finalized_automatically(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User
) -> None:
    """صفحة الرئيس انقفلت بدون إيقاف ⇒ المجدوِل يدمج التسجيل بعد دقائق — ما يضيع."""
    ctx = await _setup(client, auth_headers, roles_by_name)
    session_id = (await _start(client, ctx)).json()["session_id"]
    await _chunk(client, ctx, session_id, 0, b"only-part")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(MeetingRecordingSession)
            .where(MeetingRecordingSession.session_id == uuid.UUID(session_id))
            .values(last_chunk_at=datetime.now(UTC) - timedelta(minutes=10))
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        closed = await meeting_service.finalize_stale_recording_sessions(db)
    assert uuid.UUID(ctx["meeting_id"]) in closed
    download = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/recording/download", headers=ctx["chair_headers"])
    assert download.content == b"only-part"


# ============================== الترجمة النصية (كل عضو كلامه) ==============================


async def test_member_saves_own_speech_and_speaker_is_enforced(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User
) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    payload = {
        "own_speech": True,
        "segments": [
            {
                "client_key": "k1",
                # محاولة نسب الكلام لشخص ثاني — تُتجاهل.
                "speaker_name": "شخص ثاني",
                "speaker_raw_id": ctx["chair_id"],
                "text": "أقترح نأجل البند الثاني",
                "spoken_at": datetime.now(UTC).isoformat(),
                "language": "ar-SA",
            }
        ],
    }
    url = f"/api/v1/meetings/{ctx['meeting_id']}/transcript/segments"
    saved = await client.post(url, json=payload, headers=ctx["member_headers"])
    assert saved.status_code == 200, saved.text
    assert saved.json()["saved"] == 1
    # نفس الجملة مرة ثانية ⇒ ما تتكرر.
    assert (await client.post(url, json=payload, headers=ctx["member_headers"])).json()["saved"] == 0
    # نفس المفتاح من شخص ثاني (الرئيس) ⇒ جملة مستقلة (المفتاح مربوط بالمتحدث).
    assert (await client.post(url, json=payload, headers=ctx["chair_headers"])).json()["saved"] == 1

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(MeetingTranscriptSegment).where(MeetingTranscriptSegment.meeting_id == uuid.UUID(ctx["meeting_id"]))
            )
        ).scalars().all()
    speakers = {str(r.speaker_user_id) for r in rows}
    assert speakers == {ctx["member_id"], ctx["chair_id"]}
    assert all(r.speaker_name != "شخص ثاني" for r in rows)

    # بدون own_speech يبقى المسار القديم لرئيس اللجنة فقط (Teams).
    payload["own_speech"] = False
    assert (await client.post(url, json=payload, headers=ctx["member_headers"])).status_code == 403


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg غير موجود")
async def test_finalized_recording_gets_real_duration(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User
) -> None:
    """بلاغ لاما 2026-11-04: ملف MediaRecorder بدون مدة ⇒ المشغّل يعرضه قصير.
    نولّد ملف WebM بدون مدة (نفس حالة المتصفح)، نرفعه على قطعتين، ونتأكد إن الملف
    النهائي صار فيه مدة صحيحة (~6 ثواني)."""
    import subprocess

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
         "-c:a", "libopus", "-b:a", "32k", "-f", "webm", "pipe:1"],
        check=True, capture_output=True,
    ).stdout
    ctx = await _setup(client, auth_headers, roles_by_name)
    session_id = (await _start(client, ctx)).json()["session_id"]
    half = len(raw) // 2
    await _chunk(client, ctx, session_id, 0, raw[:half])
    await _chunk(client, ctx, session_id, 1, raw[half:])
    stopped = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/recording-sessions/{session_id}/stop", headers=ctx["chair_headers"]
    )
    assert stopped.json()["status"] == "finalized", stopped.text
    final = (await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/recording/download", headers=ctx["chair_headers"])).content
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", "-i", "pipe:0"],
        input=final, capture_output=True, check=True,
    )
    assert 5.5 < float(probe.stdout.strip()) < 6.6


async def test_attendance_is_recorded_for_agora_meetings(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User
) -> None:
    """بلاغ لاما 2026-11-04: نسبة الحضور طلعت 0 باجتماع Agora (الحضور كان لـTeams فقط)."""
    ctx = await _setup(client, auth_headers, roles_by_name)
    started = await client.post(f"/api/v1/meetings/{ctx['meeting_id']}/attendance", headers=ctx["member_headers"])
    assert started.status_code in (200, 201), started.text
    rows = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/attendance", headers=ctx["chair_headers"])
    assert rows.status_code == 200, rows.text
    assert any(r["user"]["user_id"] == ctx["member_id"] for r in rows.json())
