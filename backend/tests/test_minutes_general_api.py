"""
اختبارات "القالب العام" للمحاضر عبر الـAPI مقابل PostgreSQL حقيقي:
اختيار القالب والتعبئة التلقائية، المزامنة مع الحضور والضيوف والبنود حتى
التعديل اليدوي، رقم الاجتماع، الحفظ لقسم واحد (409/400/403)، الحفظ الكامل،
الاجتماع الحضوري، التوقيع المحفوظ، التوقيع بالمحفوظ وحفظ الرسم، وملف PDF.
وأن القوالب القديمة لم تتأثر.
"""

import base64
import copy
import io
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import select, update

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.meeting import Meeting
from app.models.meeting_attendance import MeetingAttendance
from app.models.user import User, UserStatus
from app.models.user_saved_signature import UserSavedSignature
from tests.test_meetings import _create_approved_committee, _grant_committee_role_permissions

_CHAIR_MINUTES = [
    "minutes.templates.view",
    "minutes.templates.select",
    "minutes.view",
    "minutes.update",
    "minutes.approve",
    "minutes.sign",
]
_MEMBER_MINUTES = ["minutes.view", "minutes.update", "minutes.sign"]


def _png(size: int = 60) -> str:
    buffer = io.BytesIO()
    Image.new("RGBA", (size, size // 2), (10, 10, 10, 255)).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


async def _setup(client: AsyncClient, auth_headers, roles_by_name, *, mode: str = "remote", agenda=("البند الأول", "البند الثاني")) -> dict:
    """لجنة معتمدة + صلاحيات المحاضر + اجتماع منعقد الآن (بدأ قبل ساعة وينتهي بعد ساعة)."""
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    await _grant_committee_role_permissions(_CHAIR_MINUTES, slug="chair")
    await _grant_committee_role_permissions(_MEMBER_MINUTES, slug="member")
    ctx["meeting_id"] = await _create_meeting(client, ctx, mode=mode, agenda=agenda)
    now = datetime.now(UTC)
    await _set_meeting_times(ctx["meeting_id"], now - timedelta(hours=1), now + timedelta(hours=1))
    return ctx


async def _create_meeting(client: AsyncClient, ctx: dict, *, mode: str = "remote", agenda=(), title="اجتماع اللجنة الدوري") -> str:
    start = datetime.now(UTC) + timedelta(days=1)
    payload = {
        "committee_id": ctx["committee_id"],
        "title": title,
        "mode": mode,
        "scheduled_at": start.isoformat(),
        "scheduled_end_at": (start + timedelta(hours=1)).isoformat(),
        "agenda_items": [{"title": t, "sort_order": i} for i, t in enumerate(agenda)],
    }
    if mode == "in_person":
        payload["location"] = "قاعة الاجتماعات الرئيسية"
    response = await client.post("/api/v1/meetings", json=payload, headers=ctx["chair_headers"])
    assert response.status_code == 201, response.text
    return response.json()["meeting_id"]


async def _set_meeting_times(meeting_id: str, start: datetime, end: datetime) -> None:
    """تعديل الموعد مباشرة بالقاعدة (الـAPI يرفض المواعيد الماضية)."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Meeting)
            .where(Meeting.meeting_id == uuid.UUID(meeting_id))
            .values(scheduled_at=start, scheduled_end_at=end, status="upcoming")
        )
        await db.commit()


async def _attend(meeting_id: str, user_id: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(MeetingAttendance(meeting_id=uuid.UUID(meeting_id), user_id=uuid.UUID(user_id)))
        await db.commit()


async def _admit_guest(meeting_id: str, name: str) -> str:
    """ضيف مقبول = حساب ضيف مؤقت مربوط بالاجتماع (نفس ما يسويه meeting_guest_service عند القبول)."""
    async with AsyncSessionLocal() as db:
        short = secrets.token_hex(4)
        guest = User(
            first_name=name, middle_name="", last_name="", username=f"guest_{short}",
            email=f"guest-{short}@guests.invalid", password_hash=hash_password("x"), role_id=None, dep_id=None,
            status=UserStatus.active, must_change_password=False, is_guest=True,
            guest_meeting_id=uuid.UUID(meeting_id),
        )
        db.add(guest)
        await db.commit()
        return str(guest.user_id)


async def _select_general(client: AsyncClient, ctx: dict) -> dict:
    response = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/minutes/template",
        json={"template_id": "general"},
        headers=ctx["chair_headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _detail(client: AsyncClient, ctx: dict, headers=None) -> dict:
    response = await client.get(
        f"/api/v1/meetings/{ctx['meeting_id']}/minutes/detail", headers=headers or ctx["chair_headers"]
    )
    assert response.status_code == 200, response.text
    return response.json()["minutes"]


def _section(minutes: dict, kind: str) -> dict:
    return next(s for s in minutes["sections"] if s["kind"] == kind)


def _topics(minutes: dict) -> list[dict]:
    return sorted([s for s in minutes["sections"] if s["kind"] == "topic"], key=lambda s: s["order"])


async def _patch(client: AsyncClient, ctx: dict, section: dict, headers=None):
    return await client.patch(
        f"/api/v1/meetings/{ctx['meeting_id']}/minutes/sections/{section['id']}",
        json={"section": section},
        headers=headers or ctx["chair_headers"],
    )


async def test_general_template_is_listed_and_fills_from_meeting(client: AsyncClient, auth_headers, roles_by_name, super_admin_user) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    templates = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/minutes/templates", headers=ctx["chair_headers"])
    assert templates.status_code == 200
    assert "general" in [t["id"] for t in templates.json()]
    assert any(t["name"] == "القالب العام" for t in templates.json())

    minutes = await _select_general(client, ctx)
    assert minutes["template_name"] == "القالب العام"
    header = _section(minutes, "header")["data"]
    assert header["place_text"] == "عبر الاتصال المرئي"
    assert header["subject_text"] == "محضر اجتماع اللجنة الدوري"
    year = datetime.now(UTC).year
    title = _section(minutes, "title")["data"]
    assert title["line2"] == f"لجنة الاجتماعات التجريبية - الاجتماع الأول لعام {year}م"

    rows = _section(minutes, "members_table")["data"]["rows"]
    assert [r["key"] for r in rows] == [ctx["chair_id"], ctx["member_id"]]
    assert rows[0]["role_label"] == "رئيس اللجنة"
    topics = _topics(minutes)
    assert [t["data"]["heading"] for t in topics] == ["البند الأول", "البند الثاني"]
    assert topics[1]["data"]["decision_number"] == f"(2-1-{year})"
    assert _section(minutes, "guests_table")["data"]["rows"] == []


async def test_attendance_guests_and_agenda_sync_until_edited(client: AsyncClient, auth_headers, roles_by_name, super_admin_user) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    await _select_general(client, ctx)
    await _attend(ctx["meeting_id"], ctx["chair_id"])
    await _admit_guest(ctx["meeting_id"], "ضيف من الإدارة المالية")

    minutes = await _detail(client, ctx)
    rows = {r["key"]: r for r in _section(minutes, "members_table")["data"]["rows"]}
    assert (rows[ctx["chair_id"]]["status_label"], rows[ctx["chair_id"]]["mode_label"]) == ("حاضر", "عن بعد")
    assert (rows[ctx["member_id"]]["status_label"], rows[ctx["member_id"]]["mode_label"]) == ("غائب", "غائب")
    guests = _section(minutes, "guests_table")["data"]["rows"]
    assert [(g["name"], g["role_label"]) for g in guests] == [("ضيف من الإدارة المالية", "ضيف خارجي")]

    # الرئيس يصحّح صفة العضو يدويًا ⇒ تُقفل، والحالة تبقى تتزامن.
    members = copy.deepcopy(_section(minutes, "members_table"))
    for row in members["data"]["rows"]:
        if row["key"] == ctx["member_id"]:
            row["role_label"] = "عضو مستقل"
    saved = await _patch(client, ctx, members)
    assert saved.status_code == 200, saved.text

    await _attend(ctx["meeting_id"], ctx["member_id"])
    add = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/agenda-items",
        json={"title": "بند أضيف أثناء الاجتماع", "sort_order": 5},
        headers=ctx["chair_headers"],
    )
    assert add.status_code in (200, 201), add.text

    minutes = await _detail(client, ctx)
    member_row = next(r for r in _section(minutes, "members_table")["data"]["rows"] if r["key"] == ctx["member_id"])
    assert (member_row["status_label"], member_row["role_label"], member_row["mode_label"]) == ("حاضر", "عضو مستقل", "عن بعد")
    assert member_row["locked"] == ["role_label"]
    topics = _topics(minutes)
    assert [t["data"]["heading"] for t in topics][-1] == "بند أضيف أثناء الاجتماع"
    assert topics[-1]["data"]["ordinal_label"] == "الموضوع الثالث"
    assert _section(minutes, "agenda_table")["data"]["rows"][-1]["ordinal_label"] == "الموضوع الثالث"


async def test_meeting_number_counts_earlier_meetings_in_same_year(client: AsyncClient, auth_headers, roles_by_name, super_admin_user) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    now = datetime.now(UTC)
    earlier = await _create_meeting(client, ctx, title="اجتماع سابق")
    await _set_meeting_times(earlier, now - timedelta(days=3), now - timedelta(days=3) + timedelta(hours=1))

    minutes = await _select_general(client, ctx)
    assert _section(minutes, "title")["data"]["meeting_number"] == 2
    assert "الاجتماع الثاني" in _section(minutes, "title")["data"]["line2"]

    # الاجتماع السابق صار في سنة أخرى ⇒ الترقيم يبدأ من جديد (نعيد اختيار القالب).
    await _set_meeting_times(earlier, now.replace(year=now.year - 1), now.replace(year=now.year - 1) + timedelta(hours=1))
    minutes = await _select_general(client, ctx)
    assert _section(minutes, "title")["data"]["meeting_number"] == 1


async def test_single_section_save_rules(client: AsyncClient, auth_headers, roles_by_name, super_admin_user) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    minutes = await _select_general(client, ctx)
    topic = copy.deepcopy(_topics(minutes)[0])
    topic["data"]["background"] = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "حيثيات", "marks": [{"type": "bold"}]}]}],
    }

    ok = await _patch(client, ctx, topic, headers=ctx["member_headers"])  # العضو عنده minutes.update
    assert ok.status_code == 200, ok.text
    saved = next(s for s in ok.json()["sections"] if s["id"] == topic["id"])
    assert saved["rev"] == topic["rev"] + 1

    stale = await _patch(client, ctx, topic)  # نفس rev القديم
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_section"]["rev"] == saved["rev"]

    bad = copy.deepcopy(saved)
    bad["data"]["background"] = {"type": "doc", "content": [{"type": "script"}]}
    assert (await _patch(client, ctx, bad)).status_code == 400

    changed_kind = copy.deepcopy(saved)
    changed_kind["kind"] = "text"
    assert (await _patch(client, ctx, changed_kind)).status_code == 400

    mismatch = await client.patch(
        f"/api/v1/meetings/{ctx['meeting_id']}/minutes/sections/other-id",
        json={"section": saved},
        headers=ctx["chair_headers"],
    )
    assert mismatch.status_code == 400

    assert (await _patch(client, ctx, saved, headers=ctx["outsider_headers"])).status_code == 403


async def test_full_save_tombstones_deleted_topic(client: AsyncClient, auth_headers, roles_by_name, super_admin_user) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    minutes = await _select_general(client, ctx)
    removed = _topics(minutes)[1]
    remaining = [s for s in minutes["sections"] if s["id"] != removed["id"]]
    response = await client.put(
        f"/api/v1/meetings/{ctx['meeting_id']}/minutes/sections",
        json={"sections": remaining},
        headers=ctx["chair_headers"],
    )
    assert response.status_code == 200, response.text

    minutes = await _detail(client, ctx)
    assert [t["data"]["heading"] for t in _topics(minutes)] == ["البند الأول"]
    assert _section(minutes, "meta")["data"]["removed_topic_keys"] == [removed["data"]["agenda_item_id"]]

    # واجهة قديمة ترسل أقسامًا بلا kind ⇒ مرفوض بدل مسح البيانات.
    legacy = [{"id": s["id"], "title": s["title"], "body": "", "order": s["order"], "rev": s["rev"]} for s in minutes["sections"]]
    response = await client.put(
        f"/api/v1/meetings/{ctx['meeting_id']}/minutes/sections", json={"sections": legacy}, headers=ctx["chair_headers"]
    )
    assert response.status_code == 400


async def test_in_person_status_is_chosen_by_chair(client: AsyncClient, auth_headers, roles_by_name, super_admin_user) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name, mode="in_person")
    minutes = await _select_general(client, ctx)
    assert _section(minutes, "header")["data"]["place_text"] == "قاعة الاجتماعات الرئيسية"
    members = copy.deepcopy(_section(minutes, "members_table"))
    assert {(r["status_label"], r["mode_label"]) for r in members["data"]["rows"]} == {("", "حضوري")}

    for row in members["data"]["rows"]:
        row["status_label"] = "حاضر" if row["key"] == ctx["chair_id"] else "غائب"
    assert (await _patch(client, ctx, members)).status_code == 200

    minutes = await _detail(client, ctx)
    rows = {r["key"]: r for r in _section(minutes, "members_table")["data"]["rows"]}
    assert (rows[ctx["chair_id"]]["status_label"], rows[ctx["chair_id"]]["mode_label"]) == ("حاضر", "حضوري")
    assert (rows[ctx["member_id"]]["status_label"], rows[ctx["member_id"]]["mode_label"]) == ("غائب", "غائب")


async def test_saved_signature_endpoints(client: AsyncClient, auth_headers, roles_by_name, super_admin_user) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    headers = ctx["member_headers"]
    assert (await client.get("/api/v1/users/me/signature", headers=headers)).status_code == 404
    bad = await client.put("/api/v1/users/me/signature", json={"signature_image": "data:image/jpeg;base64," + "A" * 40}, headers=headers)
    assert bad.status_code == 400

    image = _png()
    saved = await client.put("/api/v1/users/me/signature", json={"signature_image": image}, headers=headers)
    assert saved.status_code == 200, saved.text
    replaced = await client.put("/api/v1/users/me/signature", json={"signature_image": _png(80)}, headers=headers)
    assert replaced.status_code == 200
    got = await client.get("/api/v1/users/me/signature", headers=headers)
    assert got.json()["signature_image"] == _png(80)
    # كل مستخدم يشوف توقيعه هو فقط.
    assert (await client.get("/api/v1/users/me/signature", headers=ctx["chair_headers"])).status_code == 404

    assert (await client.delete("/api/v1/users/me/signature", headers=headers)).status_code == 204
    assert (await client.delete("/api/v1/users/me/signature", headers=headers)).status_code == 404
    async with AsyncSessionLocal() as db:
        events = (
            await db.execute(select(AuditLog.metadata_).where(AuditLog.target_id == uuid.UUID(ctx["member_id"])))
        ).scalars().all()
    assert sum(1 for e in events if e and e.get("event") == "saved_signature_set") == 2
    assert any(e and e.get("event") == "saved_signature_deleted" for e in events)


async def test_sign_with_saved_signature_and_save_for_later(client: AsyncClient, auth_headers, roles_by_name, super_admin_user) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    await _select_general(client, ctx)
    base = f"/api/v1/meetings/{ctx['meeting_id']}/minutes"
    assert (await client.post(f"{base}/approve", headers=ctx["chair_headers"])).status_code == 200
    assert (await client.post(f"{base}/signature/send", headers=ctx["chair_headers"])).status_code == 200

    # مصدرين معًا أو بلا مصدر ⇒ 422.
    both = await client.post(f"{base}/sign", json={"signature_image": _png(), "use_saved": True}, headers=ctx["member_headers"])
    assert both.status_code == 422
    assert (await client.post(f"{base}/sign", json={}, headers=ctx["member_headers"])).status_code == 422

    # العضو يرسم ويحفظ للمرات الجاية.
    drawn = _png(70)
    signed = await client.post(
        f"{base}/sign", json={"signature_image": drawn, "save_for_later": True}, headers=ctx["member_headers"]
    )
    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        stored = await db.get(UserSavedSignature, uuid.UUID(ctx["member_id"]))
    assert stored is not None and stored.signature_image == drawn

    # الرئيس بلا توقيع محفوظ ⇒ 400، وبعد ما يحفظه يوقّع به ويكتمل المحضر.
    no_saved = await client.post(f"{base}/sign", json={"use_saved": True}, headers=ctx["chair_headers"])
    assert no_saved.status_code == 400
    chair_image = _png(90)
    await client.put("/api/v1/users/me/signature", json={"signature_image": chair_image}, headers=ctx["chair_headers"])
    done = await client.post(f"{base}/sign", json={"use_saved": True}, headers=ctx["chair_headers"])
    assert done.status_code == 200, done.text
    assert done.json()["stage"] == "completed"

    pdf = await client.get(f"{base}/pdf", headers=ctx["chair_headers"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert len(PdfReader(io.BytesIO(pdf.content)).pages) >= 2

    # بعد الاعتماد: لا تعديل.
    minutes = await _detail(client, ctx)
    assert (await _patch(client, ctx, _section(minutes, "header"))).status_code == 409


async def test_old_templates_unchanged(client: AsyncClient, auth_headers, roles_by_name, super_admin_user) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    base = f"/api/v1/meetings/{ctx['meeting_id']}/minutes"
    selected = await client.post(f"{base}/template", json={"template_id": "formal"}, headers=ctx["chair_headers"])
    assert selected.status_code == 200
    sections = selected.json()["sections"]
    assert all(s["kind"] == "text" for s in sections)
    sections[0]["body"] = "نص حر"
    saved = await client.put(f"{base}/sections", json={"sections": sections}, headers=ctx["chair_headers"])
    assert saved.status_code == 200
    assert saved.json()["sections"][0]["body"] == "نص حر"
    # حفظ القسم الواحد خاص بالقالب العام.
    assert (await _patch(client, ctx, saved.json()["sections"][0])).status_code == 400
