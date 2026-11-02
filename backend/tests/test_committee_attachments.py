"""
الهدف:
اختبارات تصنيف "مرفقات اللجنة" بالوثائق + محضر PDF (طلب لاما 2026-11-01):
- كل مستوى يرجع حقول شاشته فقط (تحميل كسول — لا بيانات المستوى التالي).
- اللجان المنتهية/الجارية، اجتماعات لجنة، مرفقات اجتماع مع عنوان البند.
- المحضر: متاح/غير متاح، وتحميله PDF، والصلاحيات.
"""

import base64
import io
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update

from app.db.session import AsyncSessionLocal
from app.models.committee import Committee
from app.models.role import Permission, Role, RolePermission
from app.models.meeting_minutes import MeetingMinutes, MeetingMinutesSignature, MeetingMinutesStage
from tests.test_agenda_item_attachments import _payload, captured, ctx  # noqa: F401 — fixtures
from tests.test_meetings import _create_user_with_role, _grant_committee_role_permissions

BASE = "/api/v1/documents/committee-attachments"


@pytest.fixture(autouse=True)
async def _documents_access():
    """
    بوابة صفحة الوثائق: بالإنتاج كل الأدوار تملك documents.view؛ بقاعدة
    الاختبار لا يملكها دور admin — تُمنح مؤقتًا وتُسحب بعد الاختبار (جدول
    role_permissions لا يُفرَّغ بين الاختبارات، فلا نترك أثرًا على غيرها).
    """
    async with AsyncSessionLocal() as db:
        role_id = await db.scalar(select(Role.role_id).where(Role.name == "admin"))
        perm_id = await db.scalar(select(Permission.permission_id).where(Permission.code == "documents.view"))
        db.add(RolePermission(role_id=role_id, permission_id=perm_id, scope="all"))
        await db.commit()
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id, RolePermission.permission_id == perm_id)
        )
        await db.commit()


@pytest.fixture
async def meeting_id(client: AsyncClient, ctx: dict, captured) -> str:  # noqa: F811
    await _grant_committee_role_permissions(["meetings.view", "minutes.view"], slug="chair")
    response = await client.post(
        "/api/v1/meetings/with-attachments",
        data={"payload": _payload(ctx, ["مراجعة الخطة", "الميزانية"]), "agenda_file_indexes": ["1"]},
        files=[
            ("attachments", ("ملاحظات.txt", b"general notes", "text/plain")),
            ("agenda_files", ("budget.pdf", b"%PDF budget", "application/pdf")),
        ],
        headers=ctx["chair_headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()["meeting"]["meeting_id"]


async def test_committees_level_returns_only_brief_fields(client: AsyncClient, ctx: dict) -> None:  # noqa: F811
    response = await client.get(f"{BASE}/committees", headers=ctx["chair_headers"])
    assert response.status_code == 200, response.text
    [committee] = response.json()
    assert set(committee) == {"committee_id", "name", "end_date", "is_ended"}
    assert committee["committee_id"] == ctx["committee_id"] and committee["is_ended"] is False

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Committee)
            .where(Committee.committee_id == ctx["committee_id"])
            .values(start_date=date.today() - timedelta(days=60), end_date=date.today() - timedelta(days=1))
        )
        await db.commit()
    response = await client.get(f"{BASE}/committees", headers=ctx["chair_headers"])
    assert response.json()[0]["is_ended"] is True


async def test_meetings_level_returns_titles_only(client: AsyncClient, ctx: dict, meeting_id: str) -> None:  # noqa: F811
    response = await client.get(f"{BASE}/committees/{ctx['committee_id']}/meetings", headers=ctx["chair_headers"])
    assert response.status_code == 200, response.text
    [meeting] = response.json()
    assert set(meeting) == {"meeting_id", "title", "scheduled_at"}
    assert meeting["meeting_id"] == meeting_id


async def test_meeting_bundle_has_attachments_with_agenda_title_and_minutes_state(
    client: AsyncClient, ctx: dict, meeting_id: str  # noqa: F811
) -> None:
    response = await client.get(f"{BASE}/meetings/{meeting_id}", headers=ctx["chair_headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["can_view_attachments"] is True
    by_name = {a["file_name"]: a for a in body["attachments"]}
    assert by_name["budget.pdf"]["kind"] == "agenda" and by_name["budget.pdf"]["agenda_item_title"] == "الميزانية"
    assert by_name["ملاحظات.txt"]["kind"] == "attachment" and by_name["ملاحظات.txt"]["agenda_item_title"] is None
    assert body["minutes_available"] is False and body["minutes_stage"] is None

    # تنزيل مرفق باسم عربي من نفس المستوى (النقطة القائمة بوحدة الاجتماعات).
    doc_id = by_name["ملاحظات.txt"]["document_id"]
    download = await client.get(
        f"/api/v1/meetings/{meeting_id}/attachments/{doc_id}/download", headers=ctx["chair_headers"]
    )
    assert download.status_code == 200 and download.content == b"general notes"

    # لا محضر بعد → تحميل الـPDF 404 (لا يُنشأ محضر من نقطة قراءة).
    pdf = await client.get(f"/api/v1/meetings/{meeting_id}/minutes/pdf", headers=ctx["chair_headers"])
    assert pdf.status_code == 404


async def test_minutes_pdf_download(client: AsyncClient, ctx: dict, meeting_id: str) -> None:  # noqa: F811
    from PIL import Image

    png = io.BytesIO()
    Image.new("RGBA", (120, 40), (16, 94, 167, 255)).save(png, "PNG")
    async with AsyncSessionLocal() as db:
        minutes = MeetingMinutes(
            meeting_id=meeting_id,
            stage=MeetingMinutesStage.completed,
            sections=[
                {"id": "s2", "title": "القرارات", "body": "اعتماد الخطة.", "order": 1},
                {"id": "s1", "title": "المناقشة", "body": "ناقش الأعضاء الخطة بالتفصيل.\nسطر ثاني.", "order": 0},
            ],
        )
        db.add(minutes)
        await db.flush()
        db.add(
            MeetingMinutesSignature(
                minutes_id=minutes.minutes_id,
                user_id=ctx["chair_id"],
                signature_image="data:image/png;base64," + base64.b64encode(png.getvalue()).decode(),
                signed_at=datetime.now(UTC),
            )
        )
        db.add(MeetingMinutesSignature(minutes_id=minutes.minutes_id, user_id=ctx["member_id"]))
        await db.commit()

    bundle = await client.get(f"{BASE}/meetings/{meeting_id}", headers=ctx["chair_headers"])
    assert bundle.json()["minutes_available"] is True and bundle.json()["minutes_stage"] == "completed"

    pdf = await client.get(f"/api/v1/meetings/{meeting_id}/minutes/pdf", headers=ctx["chair_headers"])
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert "filename*=UTF-8''" in pdf.headers["content-disposition"]
    assert pdf.content.startswith(b"%PDF")

    from pypdf import PdfReader

    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "2026" in text or str(date.today().year) in text


async def test_outsider_cannot_open_committee_levels(
    client: AsyncClient, ctx: dict, meeting_id: str, auth_headers, roles_by_name  # noqa: F811
) -> None:
    # بلا دور إطلاقًا: لا يفتح صفحة الوثائق أصلًا.
    no_role, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="ca_norole", role_name=None
    )
    assert (await client.get(f"{BASE}/committees", headers=no_role)).status_code == 403

    # admin بقاعدة الاختبار: يعرض الوثائق، ونطاق اجتماعاته "department" وهو بلا
    # إدارة، وليس عضوًا باللجنة → لا يفتح اجتماعاتها ولا مرفقاتها ولا محضرها.
    outsider, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="ca_outsider", role_name="admin"
    )
    meetings = await client.get(f"{BASE}/committees/{ctx['committee_id']}/meetings", headers=outsider)
    assert meetings.status_code == 403
    bundle = await client.get(f"{BASE}/meetings/{meeting_id}", headers=outsider)
    assert bundle.status_code == 403
    pdf = await client.get(f"/api/v1/meetings/{meeting_id}/minutes/pdf", headers=outsider)
    assert pdf.status_code == 403
