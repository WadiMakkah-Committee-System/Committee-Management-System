"""
الهدف:
اختبارات مرفقات بنود جدول الأعمال (طلب لاما 2026-11-01):
- إنشاء اجتماع مع ملفاته بطلب واحد (POST /meetings/with-attachments) وبريد
  "اجتماع جديد" واحد فيه كل الملفات.
- إرفاق ملفات لبند لاحقًا + بريد "مرفقات جديدة للبند".
- العرض/التحميل/الحذف، وحذف البند يحذف مرفقاته، والصلاحيات.
- تقسيم المرفقات بالبريد (حد 10 ميجا) وصيغة الإرسال لكل مزوّد.

البريد لا يُرسل فعليًا — دوال الإشعار مُستبدَلة بدوال تلتقط الاستدعاء.
"""

import json
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core import background, email_client
from app.db.session import AsyncSessionLocal
from app.models.committee import Committee
from app.models.user import User
from app.services import notification_service
from tests.test_meetings import _create_approved_committee, _grant_committee_role_permissions


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict:
    calls: dict = {"created": [], "agenda": []}

    async def fake_created(meeting, *, actor_user_id=None, files=None):
        calls["created"].append({"meeting": meeting, "files": files or []})

    async def fake_agenda(meeting, title, files, *, actor_user_id=None):
        calls["agenda"].append({"title": title, "files": files})

    monkeypatch.setattr(notification_service, "notify_meeting_created", fake_created)
    monkeypatch.setattr(notification_service, "notify_agenda_item_attachments_added", fake_agenda)
    return calls


async def _flush() -> None:
    import asyncio

    pending = list(background._pending_tasks)
    if pending:
        await asyncio.wait(pending, timeout=5)


@pytest.fixture
async def ctx(client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User) -> dict:
    context = await _create_approved_committee(client, auth_headers, roles_by_name)
    await _grant_committee_role_permissions(
        ["meetings.attachments.add", "meetings.attachments.view", "meetings.attachments.delete"], slug="chair"
    )
    await _grant_committee_role_permissions(["meetings.attachments.view"], slug="member")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Committee)
            .where(Committee.committee_id == context["committee_id"])
            .values(start_date=date.today() - timedelta(days=30), end_date=date.today() + timedelta(days=365))
        )
        await db.commit()
    return context


def _payload(ctx: dict, agenda: list[str]) -> str:
    start = datetime.now(UTC) + timedelta(days=3)
    return json.dumps(
        {
            "committee_id": ctx["committee_id"],
            "title": "اجتماع بمرفقات البنود",
            "mode": "remote",
            "scheduled_at": _iso(start),
            "scheduled_end_at": _iso(start + timedelta(hours=1)),
            "agenda_items": [{"title": t} for t in agenda],
        }
    )


async def test_create_meeting_with_all_files_sends_one_email(client: AsyncClient, ctx: dict, captured) -> None:
    response = await client.post(
        "/api/v1/meetings/with-attachments",
        data={"payload": _payload(ctx, ["مراجعة الخطة", "الميزانية"]), "agenda_file_indexes": ["0", "0", "1"]},
        files=[
            ("presentation", ("slides.pdf", b"%PDF slides", "application/pdf")),
            ("attachments", ("notes.txt", b"general notes", "text/plain")),
            ("agenda_files", ("plan.pdf", b"%PDF plan", "application/pdf")),
            ("agenda_files", ("timeline.xlsx", b"xlsx-bytes", "application/vnd.ms-excel")),
            ("agenda_files", ("budget.pdf", b"%PDF budget", "application/pdf")),
        ],
        headers=ctx["chair_headers"],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["failed_files"] == []
    meeting_id = body["meeting"]["meeting_id"]
    items = {i["title"]: i["agenda_item_id"] for i in body["meeting"]["agenda_items"]}

    await _flush()
    assert len(captured["created"]) == 1  # بريد إنشاء واحد فقط
    files = captured["created"][0]["files"]
    assert {f.filename for f in files} == {"slides.pdf", "notes.txt", "plan.pdf", "timeline.xlsx", "budget.pdf"}
    by_name = {f.filename: f.agenda_item_id for f in files}
    assert str(by_name["plan.pdf"]) == items["مراجعة الخطة"] and str(by_name["budget.pdf"]) == items["الميزانية"]
    assert by_name["notes.txt"] is None

    listed = await client.get(f"/api/v1/meetings/{meeting_id}/attachments", headers=ctx["member_headers"])
    assert listed.status_code == 200
    agenda = [a for a in listed.json() if a["kind"] == "agenda"]
    assert {a["file_name"]: a["agenda_item_id"] for a in agenda} == {
        "plan.pdf": items["مراجعة الخطة"],
        "timeline.xlsx": items["مراجعة الخطة"],
        "budget.pdf": items["الميزانية"],
    }
    assert {a["kind"] for a in listed.json()} == {"presentation", "attachment", "agenda"}


async def test_create_with_invalid_agenda_index_creates_nothing(client: AsyncClient, ctx: dict, captured) -> None:
    response = await client.post(
        "/api/v1/meetings/with-attachments",
        data={"payload": _payload(ctx, ["بند واحد"]), "agenda_file_indexes": ["5"]},
        files=[("agenda_files", ("x.pdf", b"x", "application/pdf"))],
        headers=ctx["chair_headers"],
    )
    assert response.status_code == 400
    meetings = await client.get("/api/v1/meetings", headers=ctx["chair_headers"])
    assert meetings.json() == []
    await _flush()
    assert captured["created"] == []


async def test_add_attachments_to_agenda_item_later(client: AsyncClient, ctx: dict, captured) -> None:
    create = await client.post(
        "/api/v1/meetings/with-attachments",
        data={"payload": _payload(ctx, ["البند الأول"])},
        headers=ctx["chair_headers"],
    )
    assert create.status_code == 201, create.text
    meeting = create.json()["meeting"]
    item_id = meeting["agenda_items"][0]["agenda_item_id"]

    upload = await client.post(
        f"/api/v1/meetings/{meeting['meeting_id']}/agenda-items/{item_id}/attachments",
        files=[("files", ("a.pdf", b"%PDF a", "application/pdf")), ("files", ("b.txt", b"b", "text/plain"))],
        headers=ctx["chair_headers"],
    )
    assert upload.status_code == 201, upload.text
    assert [a["agenda_item_id"] for a in upload.json()] == [item_id, item_id]

    await _flush()
    assert captured["agenda"][0]["title"] == "البند الأول"
    assert [f.filename for f in captured["agenda"][0]["files"]] == ["a.pdf", "b.txt"]

    doc_id = upload.json()[0]["document_id"]
    download = await client.get(
        f"/api/v1/meetings/{meeting['meeting_id']}/attachments/{doc_id}/download", headers=ctx["member_headers"]
    )
    assert download.status_code == 200 and download.content == b"%PDF a"

    delete = await client.delete(
        f"/api/v1/meetings/{meeting['meeting_id']}/attachments/{doc_id}", headers=ctx["chair_headers"]
    )
    assert delete.status_code == 204

    # حذف البند يحذف مرفقاته الباقية
    await client.delete(f"/api/v1/meetings/agenda-items/{item_id}", headers=ctx["chair_headers"])
    listed = await client.get(f"/api/v1/meetings/{meeting['meeting_id']}/attachments", headers=ctx["chair_headers"])
    assert [a for a in listed.json() if a["kind"] == "agenda"] == []


async def test_agenda_attachment_permissions_and_wrong_meeting(client: AsyncClient, ctx: dict, captured) -> None:
    first_resp = await client.post(
        "/api/v1/meetings/with-attachments", data={"payload": _payload(ctx, ["البند أ"])}, headers=ctx["chair_headers"]
    )
    assert first_resp.status_code == 201, first_resp.text
    first = first_resp.json()["meeting"]
    second_resp = await client.post(
        "/api/v1/meetings/with-attachments", data={"payload": _payload(ctx, ["البند ب"])}, headers=ctx["chair_headers"]
    )
    assert second_resp.status_code == 201, second_resp.text
    second = second_resp.json()["meeting"]
    item_of_first = first["agenda_items"][0]["agenda_item_id"]
    files = [("files", ("a.pdf", b"a", "application/pdf"))]

    member = await client.post(
        f"/api/v1/meetings/{first['meeting_id']}/agenda-items/{item_of_first}/attachments",
        files=files,
        headers=ctx["member_headers"],
    )
    assert member.status_code == 403

    wrong_meeting = await client.post(
        f"/api/v1/meetings/{second['meeting_id']}/agenda-items/{item_of_first}/attachments",
        files=files,
        headers=ctx["chair_headers"],
    )
    assert wrong_meeting.status_code == 404


# ---------------------------------------------------------------- البريد


def test_email_files_split_at_10mb() -> None:
    small = notification_service.MeetingEmailFile("a.pdf", b"x" * (6 * 1024 * 1024), "application/pdf")
    big = notification_service.MeetingEmailFile("b.pdf", b"y" * (5 * 1024 * 1024), "application/pdf")
    tiny = notification_service.MeetingEmailFile("c.txt", b"z" * 1024, "text/plain")
    attached, too_big = notification_service._split_email_files([small, big, tiny])
    assert [a.filename for a in attached] == ["a.pdf", "c.txt"]
    assert too_big == [big]


def test_providers_payload_include_attachments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_client.settings, "EMAIL_API_KEY", "k")
    encoded = email_client._encode_attachments([email_client.EmailAttachment("ملف.pdf", b"abc", "application/pdf")])
    _, _, brevo = email_client._build_http_request(
        provider="brevo", recipient="a@x.com", subject="s", html_body="h", from_email="f@x.com", from_name="n",
        encoded_attachments=encoded,
    )
    assert brevo["attachment"] == [{"name": "ملف.pdf", "content": "YWJj"}]
    _, _, resend = email_client._build_http_request(
        provider="resend", recipient="a@x.com", subject="s", html_body="h", from_email="f@x.com", from_name="n",
        encoded_attachments=encoded,
    )
    assert resend["attachments"] == [{"filename": "ملف.pdf", "content": "YWJj"}]
    _, _, plain = email_client._build_http_request(
        provider="brevo", recipient="a@x.com", subject="s", html_body="h", from_email="f@x.com", from_name="n"
    )
    assert "attachment" not in plain


async def test_smtp_message_contains_attachments(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, **kw):
            pass

        async def connect(self):
            pass

        async def login(self, *a):
            pass

        async def send_message(self, message):
            sent.append(message)

        async def quit(self):
            pass

    monkeypatch.setattr(email_client.aiosmtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_client.settings, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(email_client.settings, "SMTP_HOST", "smtp.test")
    await email_client.send_email(
        to=["a@x.com"], subject="s", html_body="<p>h</p>",
        attachments=[email_client.EmailAttachment("plan.pdf", b"%PDF", "application/pdf")],
    )
    names = [part.get_filename() for part in sent[0].iter_attachments()]
    assert names == ["plan.pdf"]


async def test_failed_file_upload_keeps_meeting_and_other_files(
    client: AsyncClient, ctx: dict, captured, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    تعذّر رفع ملف للتخزين بعد إنشاء الاجتماع: الاجتماع يبقى، بقية الملفات
    تُرفع، الملف الفاشل يظهر بـfailed_files، والبريد يُرسل بما نجح فقط.
    (حالة حقيقية اكتُشفت بالتجربة: rollback بعد الفشل كان يُنهي صلاحية كائنات
    الجلسة ويُسقط الطلب بخطأ 500.)
    """
    from app.core import storage_client

    real_upload = storage_client.upload_object

    async def flaky_upload(storage_path: str, content: bytes, *, content_type: str) -> None:
        if content == b"BROKEN":
            raise storage_client.StorageError("فشل التخزين")
        await real_upload(storage_path, content, content_type=content_type)

    monkeypatch.setattr(storage_client, "upload_object", flaky_upload)
    response = await client.post(
        "/api/v1/meetings/with-attachments",
        data={"payload": _payload(ctx, ["البند الأول", "البند الثاني"]), "agenda_file_indexes": ["0", "1"]},
        files=[
            ("presentation", ("broken.pdf", b"BROKEN", "application/pdf")),
            ("agenda_files", ("ok.pdf", b"%PDF ok", "application/pdf")),
            ("agenda_files", ("broken2.pdf", b"BROKEN", "application/pdf")),
        ],
        headers=ctx["chair_headers"],
    )
    assert response.status_code == 201, response.text
    assert sorted(response.json()["failed_files"]) == ["broken.pdf", "broken2.pdf"]
    await _flush()
    assert [f.filename for f in captured["created"][0]["files"]] == ["ok.pdf"]
