"""
اختبارات تكامل Microsoft Teams للاجتماعات عن بعد (migration 0041) — راجعي
رأس app/services/meeting_service/teams.py لقواعد العمل.

لا اتصال شبكة فعلي إطلاقًا:
- اختبارات الـAPI تستبدل دوال app.core.teams_client بـFakeTeams (بالذاكرة)
  وتعبّئ إعدادات TEAMS_* بقيم وهمية حتى يُعتبر التكامل مفعّلًا.
- اختبارات teams_client نفسه تستخدم httpx.MockTransport (طلبات Graph مزيّفة)
  للتحقق من شكل الطلبات وترجمة الأخطاء.
- Gemini مموَّه بـmonkeypatch بنفس نمط test_meeting_recordings.py.

ملاحظة: مواعيد الاجتماعات تُحسب نسبيًا من الآن (لا تواريخ ثابتة) حتى لا
تتحول الاختبارات لاجتماعات "منتهية" مع مرور الوقت، لكنها مقيّدة بفترة
لجنة _create_approved_committee (حتى 2026-12-01).
"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import acs_client, gemini_client, teams_client, teams_transcript
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.meeting import Meeting
from app.models.user import User

from tests.test_meetings import _create_approved_committee, _grant_committee_role_permissions

ORGANIZER_ID = "11111111-1111-1111-1111-111111111111"


class FakeTeams:
    """بديل app.core.teams_client بالذاكرة — يسجّل كل استدعاء للتحقق منه."""

    def __init__(self) -> None:
        self.meetings: dict[str, dict] = {}
        self.deleted: list[str] = []
        self.updates: list[dict] = []
        self.missing_emails: set[str] = set()
        self.fail_create = False
        self.fail_update = False
        self.fail_delete = False
        self.transcripts: dict[str, list[str]] = {}
        self.recordings: dict[str, list[str]] = {}
        self._counter = 0

    async def get_user_id(self, email: str) -> str | None:
        if email == settings.TEAMS_ORGANIZER_EMAIL:
            return ORGANIZER_ID
        return None if email in self.missing_emails else f"entra-{email}"

    async def get_organizer_id(self) -> str:
        return ORGANIZER_ID

    async def create_online_meeting(self, *, organizer_id, subject, start, end, participants):
        if self.fail_create:
            raise teams_client.TeamsError("graph down")
        self._counter += 1
        meeting_id = f"MSO-{self._counter}"
        self.meetings[meeting_id] = {
            "organizer_id": organizer_id,
            "subject": subject,
            "start": start,
            "end": end,
            "participants": participants,
        }
        return teams_client.TeamsMeeting(meeting_id=meeting_id, join_url=f"https://teams.example/join/{meeting_id}")

    async def update_online_meeting(self, *, organizer_id, meeting_id, subject, start, end, participants):
        if self.fail_update:
            raise teams_client.TeamsError("graph down")
        if meeting_id not in self.meetings:
            raise teams_client.TeamsNotFoundError("gone")
        self.updates.append({"meeting_id": meeting_id, "subject": subject, "start": start, "end": end, "participants": participants})

    async def delete_online_meeting(self, *, organizer_id, meeting_id):
        if self.fail_delete:
            raise teams_client.TeamsError("graph down")
        self.deleted.append(meeting_id)
        self.meetings.pop(meeting_id, None)

    async def list_transcripts(self, *, organizer_id, meeting_id):
        return [
            teams_client.TeamsArtifact(artifact_id=f"{meeting_id}-t{i}", created_at=None)
            for i, _ in enumerate(self.transcripts.get(meeting_id, []))
        ]

    async def get_transcript_vtt(self, *, organizer_id, meeting_id, transcript_id):
        index = int(transcript_id.rsplit("-t", 1)[1])
        return self.transcripts[meeting_id][index]

    async def list_recordings(self, *, organizer_id, meeting_id):
        return [teams_client.TeamsArtifact(artifact_id=r, created_at=None) for r in self.recordings.get(meeting_id, [])]

    async def open_recording_stream(self, *, organizer_id, meeting_id, recording_id):
        if recording_id not in self.recordings.get(meeting_id, []):
            raise teams_client.TeamsNotFoundError("no such recording")

        async def chunks():
            yield b"fake-"
            yield b"video"

        return teams_client.RecordingStream(content_type="video/mp4", content_length="10", chunks=chunks())


@pytest.fixture
def fake_teams(monkeypatch: pytest.MonkeyPatch) -> FakeTeams:
    fake = FakeTeams()
    monkeypatch.setattr(settings, "TEAMS_TENANT_ID", "tenant")
    monkeypatch.setattr(settings, "TEAMS_CLIENT_ID", "client")
    monkeypatch.setattr(settings, "TEAMS_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "TEAMS_ORGANIZER_EMAIL", "meetings@example.com")
    for name in (
        "get_user_id",
        "get_organizer_id",
        "create_online_meeting",
        "update_online_meeting",
        "delete_online_meeting",
        "list_transcripts",
        "get_transcript_vtt",
        "list_recordings",
        "open_recording_stream",
    ):
        monkeypatch.setattr(teams_client, name, getattr(fake, name))
    return fake


def _slot(days: int = 3, hours: int = 1) -> tuple[str, str]:
    start = (datetime.now(UTC) + timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
    return start.isoformat(), (start + timedelta(hours=hours)).isoformat()


async def _create(client: AsyncClient, ctx: dict, *, mode: str = "remote", title: str = "اجتماع تيمز"):
    start, end = _slot()
    payload = {"committee_id": ctx["committee_id"], "title": title, "mode": mode, "scheduled_at": start, "scheduled_end_at": end}
    if mode == "in_person":
        payload["location"] = "قاعة الاجتماعات"
    return await client.post("/api/v1/meetings", json=payload, headers=ctx["chair_headers"])


async def _db_meeting(meeting_id: str) -> Meeting:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(Meeting).where(Meeting.meeting_id == meeting_id))).scalar_one()


# ============================== الإنشاء ==============================


async def test_remote_meeting_creates_teams_meeting_with_roles(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    response = await _create(client, ctx)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["has_teams_meeting"] is True
    assert "teams_join_url" not in body  # الرابط لا يُكشف بتفاصيل الاجتماع

    (teams_meeting,) = fake_teams.meetings.values()
    assert teams_meeting["organizer_id"] == ORGANIZER_ID
    assert teams_meeting["subject"] == "اجتماع تيمز"
    roles = {p.upn: p.role for p in teams_meeting["participants"]}
    assert roles == {"mt_chair@example.com": "coorganizer", "mt_member@example.com": "attendee"}

    stored = await _db_meeting(body["meeting_id"])
    assert stored.teams_meeting_id == "MSO-1"
    assert str(stored.teams_organizer_id) == ORGANIZER_ID


async def test_member_missing_from_microsoft_365_is_skipped(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams
) -> None:
    fake_teams.missing_emails.add("mt_member@example.com")
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    response = await _create(client, ctx)
    assert response.status_code == 201, response.text
    (teams_meeting,) = fake_teams.meetings.values()
    assert [p.upn for p in teams_meeting["participants"]] == ["mt_chair@example.com"]


async def test_in_person_meeting_has_no_teams_meeting(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    response = await _create(client, ctx, mode="in_person")
    assert response.status_code == 201, response.text
    assert response.json()["has_teams_meeting"] is False
    assert fake_teams.meetings == {}


async def test_teams_failure_rejects_meeting_creation(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams
) -> None:
    fake_teams.fail_create = True
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    response = await _create(client, ctx)
    assert response.status_code == 502, response.text
    assert "graph down" not in response.text  # لا تسريب لتفاصيل Graph الداخلية

    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(Meeting).where(Meeting.committee_id == ctx["committee_id"]))).scalars().all()
    assert count == []


async def test_without_teams_config_remote_meeting_is_created_without_link(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "TEAMS_CLIENT_SECRET", "")

    async def must_not_be_called(**_):
        raise AssertionError("Graph must not be called when Teams is not configured")

    monkeypatch.setattr(teams_client, "create_online_meeting", must_not_be_called)
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    response = await _create(client, ctx)
    assert response.status_code == 201, response.text
    assert response.json()["has_teams_meeting"] is False


# ============================== التعديل/التمديد/الحذف ==============================


async def test_update_time_and_title_syncs_teams(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    meeting_id = (await _create(client, ctx)).json()["meeting_id"]
    new_start, new_end = _slot(days=4, hours=2)

    response = await client.patch(
        f"/api/v1/meetings/{meeting_id}",
        json={"title": "عنوان جديد", "scheduled_at": new_start, "scheduled_end_at": new_end},
        headers=ctx["chair_headers"],
    )
    assert response.status_code == 200, response.text
    (update,) = fake_teams.updates
    assert update["subject"] == "عنوان جديد"
    assert update["start"].isoformat() == datetime.fromisoformat(new_start).isoformat()
    assert {p.role for p in update["participants"]} == {"coorganizer", "attendee"}


async def test_update_description_only_does_not_call_teams(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    meeting_id = (await _create(client, ctx)).json()["meeting_id"]
    response = await client.patch(
        f"/api/v1/meetings/{meeting_id}", json={"description": "وصف جديد"}, headers=ctx["chair_headers"]
    )
    assert response.status_code == 200, response.text
    assert fake_teams.updates == []


async def test_switching_to_in_person_deletes_teams_and_back_recreates(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    meeting_id = (await _create(client, ctx)).json()["meeting_id"]

    to_in_person = await client.patch(
        f"/api/v1/meetings/{meeting_id}",
        json={"mode": "in_person", "location": "القاعة"},
        headers=ctx["chair_headers"],
    )
    assert to_in_person.status_code == 200, to_in_person.text
    assert to_in_person.json()["has_teams_meeting"] is False
    assert fake_teams.deleted == ["MSO-1"]
    stored = await _db_meeting(meeting_id)
    assert (stored.teams_meeting_id, stored.teams_join_url, stored.teams_organizer_id) == (None, None, None)

    back = await client.patch(
        f"/api/v1/meetings/{meeting_id}",
        json={"mode": "remote", "location": None},
        headers=ctx["chair_headers"],
    )
    assert back.status_code == 200, back.text
    assert back.json()["has_teams_meeting"] is True
    assert (await _db_meeting(meeting_id)).teams_meeting_id == "MSO-2"


async def test_teams_failure_rejects_update(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    meeting_id = (await _create(client, ctx)).json()["meeting_id"]
    fake_teams.fail_update = True

    response = await client.patch(
        f"/api/v1/meetings/{meeting_id}", json={"title": "لن يُحفظ"}, headers=ctx["chair_headers"]
    )
    assert response.status_code == 502, response.text
    assert (await _db_meeting(meeting_id)).title == "اجتماع تيمز"


async def test_teams_meeting_deleted_externally_is_recreated_on_update(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    meeting_id = (await _create(client, ctx)).json()["meeting_id"]
    fake_teams.meetings.clear()  # حُذف من Teams مباشرة

    response = await client.patch(
        f"/api/v1/meetings/{meeting_id}", json={"title": "بعد الحذف"}, headers=ctx["chair_headers"]
    )
    assert response.status_code == 200, response.text
    assert (await _db_meeting(meeting_id)).teams_meeting_id == "MSO-2"


async def test_delete_meeting_deletes_teams_even_best_effort(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    first = (await _create(client, ctx, title="أول")).json()["meeting_id"]
    second = (await _create(client, ctx, title="ثاني")).json()["meeting_id"]

    ok = await client.delete(f"/api/v1/meetings/{first}", headers=ctx["chair_headers"])
    assert ok.status_code == 204, ok.text
    assert fake_teams.deleted == ["MSO-1"]

    fake_teams.fail_delete = True  # فشل Teams لا يمنع حذف الاجتماع عندنا
    still_ok = await client.delete(f"/api/v1/meetings/{second}", headers=ctx["chair_headers"])
    assert still_ok.status_code == 204, still_ok.text


async def test_extend_meeting_keeps_participants(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    meeting_id = (await _create(client, ctx)).json()["meeting_id"]
    _, current_end = _slot()
    new_end = (datetime.fromisoformat(current_end) + timedelta(minutes=30)).isoformat()

    response = await client.post(
        f"/api/v1/meetings/{meeting_id}/extend", json={"new_end_at": new_end}, headers=ctx["chair_headers"]
    )
    assert response.status_code == 200, response.text
    (update,) = fake_teams.updates
    assert update["participants"] is None  # التمديد لا يمس قائمة المشاركين


# ============================== الانضمام ==============================


async def test_join_url_requires_permission_and_remote_teams_meeting(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    await _grant_committee_role_permissions(["meetings.join"], slug="chair")
    remote_id = (await _create(client, ctx)).json()["meeting_id"]
    in_person_id = (await _create(client, ctx, mode="in_person")).json()["meeting_id"]

    ok = await client.get(f"/api/v1/meetings/{remote_id}/teams/join", headers=ctx["chair_headers"])
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"join_url": "https://teams.example/join/MSO-1"}
    assert (await _db_meeting(remote_id)).started_at is not None

    outsider = await client.get(f"/api/v1/meetings/{remote_id}/teams/join", headers=ctx["outsider_headers"])
    assert outsider.status_code == 403, outsider.text

    in_person = await client.get(f"/api/v1/meetings/{in_person_id}/teams/join", headers=ctx["chair_headers"])
    assert in_person.status_code == 409, in_person.text


# ============================== الانضمام المدمج (ACS — تجربة) ==============================


async def test_call_token_for_embedded_join(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams, monkeypatch
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    await _grant_committee_role_permissions(["meetings.join"], slug="chair")
    meeting_id = (await _create(client, ctx)).json()["meeting_id"]

    not_configured = await client.post(f"/api/v1/meetings/{meeting_id}/teams/call-token", headers=ctx["chair_headers"])
    assert not_configured.status_code == 503, not_configured.text

    monkeypatch.setattr(settings, "ACS_CONNECTION_STRING", "endpoint=https://x/;accesskey=y")

    async def fake_issue():
        return acs_client.AcsToken(token="acs-token", user_id="8:acs:1", expires_on=datetime.now(UTC) + timedelta(hours=24))

    monkeypatch.setattr(acs_client, "issue_meeting_token", fake_issue)
    ok = await client.post(f"/api/v1/meetings/{meeting_id}/teams/call-token", headers=ctx["chair_headers"])
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["token"] == "acs-token"
    assert body["join_url"] == "https://teams.example/join/MSO-1"
    assert body["display_name"]
    assert body["identity"] == "guest"

    outsider = await client.post(f"/api/v1/meetings/{meeting_id}/teams/call-token", headers=ctx["outsider_headers"])
    assert outsider.status_code == 403, outsider.text

    # الضيف اللي دخل من المنصة ينحفظ للقبول التلقائي من قاعة الانتظار.
    known = await client.get(f"/api/v1/meetings/{meeting_id}/teams/known-guests", headers=ctx["chair_headers"])
    assert known.status_code == 200, known.text
    assert [g["acs_user_id"] for g in known.json()] == ["8:acs:1"]
    assert known.json()[0]["display_name"]
    hidden = await client.get(f"/api/v1/meetings/{meeting_id}/teams/known-guests", headers=ctx["outsider_headers"])
    assert hidden.status_code == 403, hidden.text


async def test_call_token_with_microsoft_account(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams, monkeypatch
) -> None:
    """
    الدخول بهوية Microsoft: توكن Microsoft (مشفّر — ما نقرأه) + object_id لازم
    يطابق الحساب المربوط بمستخدم المنصة؛ ACS هو اللي يتحقق من التوكن نفسه.
    """
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    await _grant_committee_role_permissions(["meetings.join"], slug="chair")
    meeting_id = (await _create(client, ctx)).json()["meeting_id"]
    monkeypatch.setattr(settings, "ACS_CONNECTION_STRING", "endpoint=https://x/;accesskey=y")
    monkeypatch.setattr(settings, "TEAMS_CLIENT_ID", "client-1")

    exchanged: dict = {}

    def fake_exchange(aad_token: str, object_id: str):
        exchanged["oid"] = object_id
        return acs_client.AcsToken(token="teams-user-token", user_id=object_id, expires_on=datetime.now(UTC) + timedelta(hours=1))

    monkeypatch.setattr(acs_client, "_exchange_sync", fake_exchange)
    url = f"/api/v1/meetings/{meeting_id}/teams/call-token"
    oid = uuid.uuid4()
    opaque_token = "eyJ.encrypted.part.four.five"

    # الرئيس ما دخل المنصة بـMicrosoft بعد (غير مربوط) ⇒ رفض قبل ACS.
    unlinked = await client.post(
        url, headers=ctx["chair_headers"], json={"microsoft_token": opaque_token, "microsoft_object_id": str(oid)}
    )
    assert unlinked.status_code == 403, unlinked.text
    assert exchanged == {}

    chair_id = (await client.get("/api/v1/users/me", headers=ctx["chair_headers"])).json()["user_id"]
    async with AsyncSessionLocal() as db:
        chair = (await db.execute(select(User).where(User.user_id == uuid.UUID(chair_id)))).scalar_one()
        chair.microsoft_object_id = oid
        await db.commit()

    ok = await client.post(
        url, headers=ctx["chair_headers"], json={"microsoft_token": opaque_token, "microsoft_object_id": str(oid)}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["identity"] == "teams_user"
    assert ok.json()["token"] == "teams-user-token"
    assert exchanged["oid"] == str(oid)

    # حساب Microsoft غير المربوط بهالمستخدم ⇒ رفض قبل ACS.
    exchanged.clear()
    other = await client.post(
        url,
        headers=ctx["chair_headers"],
        json={"microsoft_token": opaque_token, "microsoft_object_id": str(uuid.uuid4())},
    )
    assert other.status_code == 403, other.text
    assert exchanged == {}

    # ACS رفض التوكن ⇒ 403 برسالة عامة.
    def rejecting_exchange(aad_token: str, object_id: str):
        error = Exception("InvalidAccessToken")
        error.status_code = 401  # type: ignore[attr-defined]
        raise error

    monkeypatch.setattr(acs_client, "_exchange_sync", rejecting_exchange)
    rejected = await client.post(
        url, headers=ctx["chair_headers"], json={"microsoft_token": opaque_token, "microsoft_object_id": str(oid)}
    )
    assert rejected.status_code == 403, rejected.text


# ============================== المسودة من التفريغ ==============================

VTT_PART_1 = """WEBVTT

a1/1-0
00:00:01.000 --> 00:00:04.000
<v أ ب ج>السلام عليكم، نبدأ.</v>

a1/2-0
00:00:04.500 --> 00:00:06.000
<v أ ب ج>البند الأول اعتماد الميزانية.</v>

a1/3-0
00:00:07.000 --> 00:00:09.000
<v عضو>موافق &amp; أقترح المتابعة.</v>
"""

VTT_PART_2 = """WEBVTT

00:00:00.500 --> 00:00:02.000
<v أ ب ج>نستأنف بعد الاستراحة.</v>
"""


async def test_draft_is_generated_from_teams_transcript(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams, monkeypatch
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    await _grant_committee_role_permissions(
        ["meetings.draft.summarize", "meetings.draft.view"], slug="chair"
    )
    meeting_id = (await _create(client, ctx)).json()["meeting_id"]
    fake_teams.transcripts["MSO-1"] = [VTT_PART_1, VTT_PART_2]

    captured: dict = {}

    async def fake_generate(*, meeting_title, participant_names, transcript_text):
        captured["text"] = transcript_text
        return {
            "summary": "ملخص",
            "decisions": [{"text": "اعتماد الميزانية", "proposed_by": "عضو", "approved": True}],
            "action_items": [],
            "key_points": ["نقطة"],
            "recommendations": [],
            "open_items": [],
            "compliance_notes": [],
        }

    async def audio_must_not_be_called(**_):
        raise AssertionError("audio path must not run for a Teams meeting")

    monkeypatch.setattr(gemini_client, "generate_meeting_draft_from_transcript", fake_generate)
    monkeypatch.setattr(gemini_client, "generate_meeting_draft", audio_must_not_be_called)

    response = await client.post(f"/api/v1/meetings/{meeting_id}/draft", headers=ctx["chair_headers"])
    assert response.status_code == 201, response.text
    draft = response.json()
    assert draft["status"] == "completed"
    assert draft["source"] == "teams_transcript"
    assert draft["full_transcript"] == [
        {"speaker": "أ ب ج", "start_time": "00:01", "text": "السلام عليكم، نبدأ. البند الأول اعتماد الميزانية."},
        {"speaker": "عضو", "start_time": "00:07", "text": "موافق & أقترح المتابعة."},
        {"speaker": "أ ب ج", "start_time": "00:00", "text": "نستأنف بعد الاستراحة."},
    ]
    assert "[00:07] عضو: موافق & أقترح المتابعة." in captured["text"]
    assert draft["decisions"][0]["text"] == "اعتماد الميزانية"


async def test_draft_without_transcript_is_rejected_without_creating_draft(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    await _grant_committee_role_permissions(
        ["meetings.draft.summarize", "meetings.draft.view"], slug="chair"
    )
    meeting_id = (await _create(client, ctx)).json()["meeting_id"]

    response = await client.post(f"/api/v1/meetings/{meeting_id}/draft", headers=ctx["chair_headers"])
    assert response.status_code == 400, response.text
    assert "تفريغ" in response.json()["detail"]
    missing = await client.get(f"/api/v1/meetings/{meeting_id}/draft", headers=ctx["chair_headers"])
    assert missing.status_code == 404, missing.text


async def test_gemini_failure_on_transcript_is_stored_as_failed_draft(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams, monkeypatch
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    await _grant_committee_role_permissions(
        ["meetings.draft.summarize", "meetings.draft.view"], slug="chair"
    )
    meeting_id = (await _create(client, ctx)).json()["meeting_id"]
    fake_teams.transcripts["MSO-1"] = [VTT_PART_1]

    async def failing(**_):
        raise gemini_client.GeminiError("Gemini unavailable")

    monkeypatch.setattr(gemini_client, "generate_meeting_draft_from_transcript", failing)
    response = await client.post(f"/api/v1/meetings/{meeting_id}/draft", headers=ctx["chair_headers"])
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "failed"
    assert response.json()["source"] == "teams_transcript"


# ============================== التسجيلات ==============================


async def test_recordings_list_and_stream_require_record_permission(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User, fake_teams: FakeTeams
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    await _grant_committee_role_permissions(["meetings.record_audio"], slug="chair")
    meeting_id = (await _create(client, ctx)).json()["meeting_id"]
    fake_teams.recordings["MSO-1"] = ["rec-1"]

    listing = await client.get(f"/api/v1/meetings/{meeting_id}/teams/recordings", headers=ctx["chair_headers"])
    assert listing.status_code == 200, listing.text
    assert listing.json() == [{"recording_id": "rec-1", "created_at": None}]

    content = await client.get(
        f"/api/v1/meetings/{meeting_id}/teams/recordings/rec-1/content", headers=ctx["chair_headers"]
    )
    assert content.status_code == 200, content.text
    assert content.content == b"fake-video"
    assert content.headers["content-type"] == "video/mp4"

    unknown = await client.get(
        f"/api/v1/meetings/{meeting_id}/teams/recordings/other/content", headers=ctx["chair_headers"]
    )
    assert unknown.status_code == 404, unknown.text

    member = await client.get(f"/api/v1/meetings/{meeting_id}/teams/recordings", headers=ctx["member_headers"])
    assert member.status_code == 403, member.text


# ============================== تحليل التفريغ (دوال نقية) ==============================


def test_parse_vtt_handles_unknown_speaker_hours_and_empty_cues() -> None:
    vtt = """WEBVTT

NOTE هذا تعليق

01:02:03.000 --> 01:02:05.000
نص بلا وسم متحدث

01:02:06.000 --> 01:02:07.000
<v سارة></v>
"""
    assert teams_transcript.parse_vtt(vtt) == [
        {"speaker": teams_transcript.UNKNOWN_SPEAKER, "start_time": "01:02:03", "text": "نص بلا وسم متحدث"}
    ]
    assert teams_transcript.parse_vtt("") == []


# ============================== teams_client مقابل Graph مزيّف ==============================


def _mock_graph(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return handler(request)

    monkeypatch.setattr(settings, "TEAMS_TENANT_ID", "tenant")
    monkeypatch.setattr(settings, "TEAMS_CLIENT_ID", "client")
    monkeypatch.setattr(settings, "TEAMS_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "TEAMS_ORGANIZER_EMAIL", "meetings@example.com")
    monkeypatch.setattr(teams_client, "_token_cache", {"token": None, "expires_at": 0.0})
    monkeypatch.setattr(teams_client, "_user_id_cache", {})
    monkeypatch.setattr(
        teams_client, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(recording_handler))
    )
    return seen


async def test_client_create_meeting_sends_expected_graph_request(monkeypatch) -> None:
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(201, json={"id": "MSO-x", "joinWebUrl": "https://teams/x"})

    seen = _mock_graph(monkeypatch, handler)
    start = datetime(2026, 11, 20, 10, tzinfo=UTC)
    result = await teams_client.create_online_meeting(
        organizer_id="org-1",
        subject="اجتماع",
        start=start,
        end=start + timedelta(hours=1),
        participants=[teams_client.TeamsParticipant(user_id="u1", upn="a@x.com", role="coorganizer")],
    )
    assert result == teams_client.TeamsMeeting(meeting_id="MSO-x", join_url="https://teams/x")

    graph_call = seen[-1]
    assert graph_call.method == "POST"
    assert graph_call.url.path == "/v1.0/users/org-1/onlineMeetings"
    body = json.loads(graph_call.content)
    assert body["startDateTime"] == "2026-11-20T10:00:00Z"
    assert body["participants"]["attendees"][0] == {
        "upn": "a@x.com",
        "role": "coorganizer",
        "identity": {"user": {"id": "u1"}},
    }
    assert body["lobbyBypassSettings"]["scope"] == "organization"
    assert body["recordAutomatically"] is True


async def test_client_token_is_cached_and_update_without_participants_omits_field(monkeypatch) -> None:
    import json

    seen = _mock_graph(monkeypatch, lambda request: httpx.Response(204))
    start = datetime(2026, 11, 20, 10, tzinfo=UTC)
    for _ in range(2):
        await teams_client.update_online_meeting(
            organizer_id="org-1", meeting_id="MSO-x", subject="s", start=start, end=start, participants=None
        )
    token_calls = [r for r in seen if r.url.host == "login.microsoftonline.com"]
    assert len(token_calls) == 1
    assert "participants" not in json.loads(seen[-1].content)


async def test_client_error_translation(monkeypatch) -> None:
    responses = iter(
        [
            httpx.Response(404, json={"error": {"code": "NotFound", "message": "x"}}),
            httpx.Response(403, json={"error": {"code": "Forbidden", "message": "No application access policy"}}),
            httpx.Response(404, json={"error": {"code": "NotFound", "message": "x"}}),
        ]
    )
    _mock_graph(monkeypatch, lambda request: next(responses))

    # الحذف idempotent: 404 = نجاح
    await teams_client.delete_online_meeting(organizer_id="org-1", meeting_id="MSO-x")
    with pytest.raises(teams_client.TeamsError) as forbidden:
        await teams_client.list_transcripts(organizer_id="org-1", meeting_id="MSO-x")
    assert "Application Access Policy" in str(forbidden.value)
    assert await teams_client.get_user_id("nobody@example.com") is None


def test_client_reports_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TEAMS_CLIENT_SECRET", "")
    assert teams_client.is_configured() is False


def test_transcript_schema_matches_audio_schema_without_full_transcript() -> None:
    audio = gemini_client._RESPONSE_SCHEMA
    transcript = gemini_client._TRANSCRIPT_RESPONSE_SCHEMA
    assert set(transcript["properties"]) == set(audio["properties"]) - {"full_transcript"}
    assert set(transcript["required"]) == set(audio["required"]) - {"full_transcript"}


async def test_user_id_lookups_are_cached(monkeypatch) -> None:
    """تحسين أداء 2026-11-03: نفس البريد ما يُسأل عنه Graph مرتين (إنشاء الاجتماع أسرع)."""
    seen = _mock_graph(
        monkeypatch,
        lambda request: httpx.Response(200, json={"id": "entra-1"})
        if "/users/a%40example.com" in str(request.url) or "/users/a@example.com" in str(request.url)
        else httpx.Response(404, json={"error": {"code": "NotFound", "message": "x"}}),
    )
    assert await teams_client.get_user_id("a@example.com") == "entra-1"
    assert await teams_client.get_user_id("A@Example.com") == "entra-1"
    assert await teams_client.get_user_id("missing@example.com") is None
    assert await teams_client.get_user_id("missing@example.com") is None
    user_calls = [r for r in seen if "/users/" in str(r.url)]
    assert len(user_calls) == 2
