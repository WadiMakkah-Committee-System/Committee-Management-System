"""
اختبارات ميزة "التسجيل الصوتي + المسودة بالذكاء الاصطناعي" — راجعي رأس
db/migrations/0025_meeting_recordings_and_drafts.sql وapp/services/
meeting_service.py (قسم "التسجيل الصوتي + المسودة") للتصميم الكامل.

تغطي: رفع تسجيل من رئيس اللجنة (نجاح)، رفض الرفع من عضو بدون صلاحية
meetings.record_audio، رفض توليد المسودة بدون تسجيل مسبق (FR-AI-001:
"بشرط أن يكون التسجيل الصوتي متاح")، توليد ناجح لمسودة (Gemini مموَّه
بـmonkeypatch — بدون استدعاء شبكة فعلي)، وأهم شيء: فشل استدعاء Gemini
يُخزَّن كحالة status='failed' بالمسودة نفسها بدل رمي خطأ HTTP (راجعي
تعليق _handle_errors بـapi/v1/meetings.py لتبرير هذا القرار).
"""

from httpx import AsyncClient

from app.core import gemini_client
from app.models.user import User

from tests.test_meetings import _create_meeting_with_attachment_permissions, _grant_committee_role_permissions


async def _create_meeting_with_recording_permissions(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> dict:
    ctx = await _create_meeting_with_attachment_permissions(client, auth_headers, roles_by_name)
    await _grant_committee_role_permissions(
        ["meetings.record_audio", "meetings.draft.summarize", "meetings.draft.view"], slug="chair"
    )
    return ctx


async def test_chair_can_upload_recording(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_meeting_with_recording_permissions(client, auth_headers, roles_by_name)
    meeting_id = ctx["meeting_id"]

    upload = await client.post(
        f"/api/v1/meetings/{meeting_id}/recording",
        files={"file": ("meeting.mp3", b"fake audio bytes", "audio/mpeg")},
        headers=ctx["chair_headers"],
    )
    assert upload.status_code == 201, upload.text
    body = upload.json()
    assert body["file_name"] == "meeting.mp3"
    assert body["mime_type"] == "audio/mpeg"

    fetched = await client.get(f"/api/v1/meetings/{meeting_id}/recording", headers=ctx["chair_headers"])
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["recording_id"] == body["recording_id"]


async def test_member_without_permission_cannot_upload_recording(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_meeting_with_recording_permissions(client, auth_headers, roles_by_name)
    meeting_id = ctx["meeting_id"]

    upload = await client.post(
        f"/api/v1/meetings/{meeting_id}/recording",
        files={"file": ("meeting.mp3", b"fake audio bytes", "audio/mpeg")},
        headers=ctx["member_headers"],
    )
    assert upload.status_code == 403, upload.text


async def test_generate_draft_requires_recording_first(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_meeting_with_recording_permissions(client, auth_headers, roles_by_name)
    meeting_id = ctx["meeting_id"]

    response = await client.post(f"/api/v1/meetings/{meeting_id}/draft", headers=ctx["chair_headers"])
    assert response.status_code == 400, response.text


async def test_chair_can_generate_and_view_draft(
    client: AsyncClient,
    auth_headers,
    roles_by_name: dict[str, str],
    super_admin_user: User,
    monkeypatch,
) -> None:
    ctx = await _create_meeting_with_recording_permissions(client, auth_headers, roles_by_name)
    meeting_id = ctx["meeting_id"]

    await client.post(
        f"/api/v1/meetings/{meeting_id}/recording",
        files={"file": ("meeting.mp3", b"fake audio bytes", "audio/mpeg")},
        headers=ctx["chair_headers"],
    )

    fake_result = {
        "full_transcript": [{"speaker": "أحمد العتيبي", "start_time": "00:00", "text": "بدأنا الاجتماع"}],
        "summary": "ملخص تجريبي للاجتماع.",
        "decisions": [{"text": "اعتماد الميزانية", "proposed_by": "أحمد العتيبي", "approved": True}],
        "action_items": [{"text": "إرسال التقرير", "assignee": "أحمد العتيبي", "due_date": None}],
        "key_points": ["نقطة مهمة واحدة"],
    }

    async def fake_generate(**kwargs):
        return fake_result

    monkeypatch.setattr(gemini_client, "generate_meeting_draft", fake_generate)

    generate = await client.post(f"/api/v1/meetings/{meeting_id}/draft", headers=ctx["chair_headers"])
    assert generate.status_code == 201, generate.text
    body = generate.json()
    assert body["status"] == "completed"
    assert body["summary"] == "ملخص تجريبي للاجتماع."
    assert body["decisions"][0]["text"] == "اعتماد الميزانية"

    fetched = await client.get(f"/api/v1/meetings/{meeting_id}/draft", headers=ctx["chair_headers"])
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["status"] == "completed"


async def test_draft_generation_failure_is_stored_not_raised(
    client: AsyncClient,
    auth_headers,
    roles_by_name: dict[str, str],
    super_admin_user: User,
    monkeypatch,
) -> None:
    ctx = await _create_meeting_with_recording_permissions(client, auth_headers, roles_by_name)
    meeting_id = ctx["meeting_id"]

    await client.post(
        f"/api/v1/meetings/{meeting_id}/recording",
        files={"file": ("meeting.mp3", b"fake audio bytes", "audio/mpeg")},
        headers=ctx["chair_headers"],
    )

    async def fake_generate_failure(**kwargs):
        raise gemini_client.GeminiError("فشل تجريبي")

    monkeypatch.setattr(gemini_client, "generate_meeting_draft", fake_generate_failure)

    generate = await client.post(f"/api/v1/meetings/{meeting_id}/draft", headers=ctx["chair_headers"])
    assert generate.status_code == 201, generate.text
    body = generate.json()
    assert body["status"] == "failed"
    assert body["error_message"] == "فشل تجريبي"


async def test_member_without_draft_view_permission_cannot_view_draft(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_meeting_with_recording_permissions(client, auth_headers, roles_by_name)
    meeting_id = ctx["meeting_id"]

    response = await client.get(f"/api/v1/meetings/{meeting_id}/draft", headers=ctx["member_headers"])
    assert response.status_code == 403, response.text
