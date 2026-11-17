"""
الهدف:
اختبارات وحدة "التذاكر" (الدعم الفني) — المسموح والممنوع لكل صفة، حسب
مواصفات tickets_spec.md وmigration 0051.

يغطي: الإرسال والتحقق من المحتوى والمرفقات، منع التكرار، "تذاكري"، عزل
تذاكر المستخدمين (IDOR)، تبويبات الدعم، الاستلام المتزامن، الإسناد، الحالات
وإعادة الفتح، الإلغاء، الملاحظات الداخلية ومرفقاتها، تعديل الحقول، السجل،
الإغلاق التلقائي، نطاق صلاحيات الدعم، الإشعارات، والاشتراك اللحظي.

الإعداد: أدوار مخصّصة تُنشأ لكل اختبار (conftest يحذف الأدوار غير النظامية
قبل كل اختبار): "مستخدم نظام" بخانة tickets.create، و"دعم فني" بخانات الدعم.
"""

import json
import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core import ticket_realtime
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.notification import Notification
from app.models.role import Permission, Role, RolePermission
from app.models.user import User
from app.models.user_role import UserRole
from app.services import ticket_service, user_service

PASSWORD = "StrongPass1"
SUPPORT_CODES = ("tickets.view_all", "tickets.reply", "tickets.internal_notes", "tickets.manage", "tickets.assign")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"0" * 64


def _doc(value: str) -> str:
    """مستند TipTap بفقرة واحدة كنص JSON (نفس ما ترسله الواجهة)."""
    return json.dumps(
        {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": value}]}]}
    )


async def _make_role(name: str, grants: dict[str, str]) -> uuid.UUID:
    """ينشئ دورًا نظاميًا مخصّصًا بالخانات المحددة ونطاقها."""
    async with AsyncSessionLocal() as db:
        role = Role(name=name, description=None, is_system=False, is_super_admin=False, kind="user")
        db.add(role)
        await db.flush()
        perms = (await db.execute(select(Permission).where(Permission.code.in_(grants)))).scalars().all()
        assert len(perms) == len(grants)
        for perm in perms:
            db.add(RolePermission(role_id=role.role_id, permission_id=perm.permission_id, scope=grants[perm.code]))
        await db.commit()
        return role.role_id


async def _make_user(username: str, role_id: uuid.UUID | None, *, first_name: str = "مستخدم") -> uuid.UUID:
    """ينشئ مستخدمًا مباشرة بالقاعدة بدوره (نفس نمط super_admin_user بـconftest)."""
    async with AsyncSessionLocal() as db:
        user = User(
            first_name=first_name,
            middle_name="اختبار",
            last_name=username,
            username=username,
            email=f"{username}@example.com",
            password_hash=hash_password(PASSWORD),
            role_id=role_id,
            dep_id=None,
            must_change_password=False,
        )
        db.add(user)
        await db.flush()
        if role_id is not None:
            db.add(UserRole(user_id=user.user_id, role_id=role_id))
        await db.commit()
        return user.user_id


async def _login(client: AsyncClient, username: str) -> dict[str, str]:
    """تسجيل الدخول وإرجاع رأس Authorization."""
    response = await client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest_asyncio.fixture
async def people(client: AsyncClient) -> dict:
    """
    مقدّما طلب (req1/req2)، عضوا دعم (sup1/sup2)، ومستخدم بلا خانات تذاكر (plain).
    """
    await text_reset_counters()
    requester_role = await _make_role("مستخدم نظام", {"tickets.create": "own"})
    support_role = await _make_role("دعم فني", {code: "all" for code in SUPPORT_CODES})
    plain_role = await _make_role("بدون تذاكر", {"users.view": "own"})
    ids = {
        "req1": await _make_user("req1", requester_role, first_name="سارة"),
        "req2": await _make_user("req2", requester_role, first_name="خالد"),
        "sup1": await _make_user("sup1", support_role, first_name="فهد"),
        "sup2": await _make_user("sup2", support_role, first_name="نورة"),
        "plain": await _make_user("plain", plain_role, first_name="علي"),
    }
    headers = {name: await _login(client, name) for name in ids}
    return {"ids": ids, "h": headers, "roles": {"requester": requester_role, "support": support_role}}


async def text_reset_counters() -> None:
    """عدّاد الأرقام لا يُفرَّغ مع المستخدمين (لا FK) — نصفّره لتثبيت الأرقام."""
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM ticket_number_counters"))
        await db.commit()


async def _create(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    title: str = "مشكلة في صفحة الاجتماعات",
    body: str = "الصفحة ما تفتح بعد التحديث الأخير",
    files: list[tuple[str, bytes, str]] | None = None,
    client_id: str | None = None,
):
    """إرسال تذكرة عبر الـAPI (multipart) — نفس شكل طلب الواجهة."""
    data = {"title": title, "ticket_type": "bug", "module": "meetings", "body": _doc(body)}
    if client_id:
        data["client_message_id"] = client_id
    upload = [("files", (n, c, t)) for n, c, t in (files or [])]
    return await client.post("/api/v1/tickets", data=data, files=upload or None, headers=headers)


async def _reply(client, headers, ticket_id, body="رد", *, internal=False, status_after=None, files=None, client_id=None):
    """رد أو ملاحظة داخلية عبر الـAPI (multipart)."""
    data = {"body": _doc(body) if body else "", "is_internal": "true" if internal else "false"}
    if status_after:
        data["status_after"] = status_after
    if client_id:
        data["client_message_id"] = client_id
    upload = [("files", (n, c, t)) for n, c, t in (files or [])]
    return await client.post(
        f"/api/v1/tickets/{ticket_id}/messages", data=data, files=upload or None, headers=headers
    )


async def _notifications(user_id: uuid.UUID) -> list[Notification]:
    """إشعارات الجرس المكتوبة لمستخدم."""
    async with AsyncSessionLocal() as db:
        rows = await db.execute(select(Notification).where(Notification.recipient_user_id == user_id))
        return list(rows.scalars().all())


async def _wait_background() -> None:
    """ينتظر مهام الإشعارات المنفصلة (run_detached) قبل فحص جدول الإشعارات."""
    import asyncio

    from app.core import background

    pending = list(background._pending_tasks)
    if pending:
        await asyncio.wait(pending, timeout=10)


# ============================ الإرسال ============================


async def test_create_ticket_numbering_and_requester_view(client: AsyncClient, people) -> None:
    response = await _create(client, people["h"]["req1"])
    assert response.status_code == 201, response.text
    body = response.json()
    ticket = body["ticket"]
    assert ticket["ticket_number"].startswith("TKT-") and ticket["ticket_number"].endswith("-0001")
    assert ticket["status"] == "new"
    assert ticket["viewer"] == "requester"
    assert ticket["priority"] is None  # الأولوية للدعم فقط
    assert ticket["requester"]["email"] is None
    assert ticket["actions"] == {
        "can_reply": True,
        "can_add_internal_note": False,
        "can_cancel": True,
        "can_manage": False,
        "can_assign": False,
    }
    assert body["message"]["is_description"] is True
    assert body["message"]["author_side"] == "requester"

    second = await _create(client, people["h"]["req2"])
    assert second.json()["ticket"]["ticket_number"].endswith("-0002")


async def test_create_requires_tickets_create(client: AsyncClient, people) -> None:
    assert (await _create(client, people["h"]["plain"])).status_code == 403
    # عضو الدعم بدون tickets.create ما يرسل تذاكر
    assert (await _create(client, people["h"]["sup1"])).status_code == 403


async def test_super_admin_can_send_but_not_support(client: AsyncClient, people, auth_headers) -> None:
    """قرار 2026-11-17: السوبر أدمن يرسل مثل أي مستخدم، وما ياخذ خانات الدعم."""
    created = await _create(client, auth_headers)
    assert created.status_code == 201, created.text
    assert (await client.get("/api/v1/tickets", headers=auth_headers)).status_code == 403


async def test_create_validation(client: AsyncClient, people) -> None:
    h = people["h"]["req1"]
    assert (await _create(client, h, title="قصير")).status_code == 400
    assert (await _create(client, h, title="أ" * 151)).status_code == 400
    assert (await _create(client, h, body="قصير")).status_code == 400
    too_long = await _create(client, h, body="ب" * 5001)
    assert too_long.status_code == 400

    bad_json = await client.post(
        "/api/v1/tickets",
        data={"title": "عنوان صحيح", "ticket_type": "bug", "module": "other", "body": "{not json"},
        headers=h,
    )
    assert bad_json.status_code == 400
    script_node = json.dumps({"type": "doc", "content": [{"type": "image", "attrs": {"src": "javascript:x"}}]})
    rejected_node = await client.post(
        "/api/v1/tickets",
        data={"title": "عنوان صحيح", "ticket_type": "bug", "module": "other", "body": script_node},
        headers=h,
    )
    assert rejected_node.status_code == 400
    bad_type = await client.post(
        "/api/v1/tickets",
        data={"title": "عنوان صحيح", "ticket_type": "feature", "module": "other", "body": _doc("وصف كافي للمشكلة")},
        headers=h,
    )
    assert bad_type.status_code == 422


async def test_create_attachment_rules(client: AsyncClient, people) -> None:
    h = people["h"]["req1"]
    six = [(f"f{i}.png", PNG, "image/png") for i in range(6)]
    assert (await _create(client, h, files=six)).status_code == 400
    zip_file = await _create(client, h, files=[("a.zip", b"PK\x03\x04data", "application/zip")])
    assert zip_file.status_code == 400
    fake_png = await _create(client, h, files=[("fake.png", b"not really a png", "image/png")])
    assert fake_png.status_code == 400
    empty = await _create(client, h, files=[("empty.pdf", b"", "application/pdf")])
    assert empty.status_code == 400

    ok = await _create(client, h, files=[("لقطة شاشة.png", PNG, "image/png"), ("تقرير.pdf", PDF, "application/pdf")])
    assert ok.status_code == 201, ok.text
    attachments = ok.json()["message"]["attachments"]
    assert [a["mime_type"] for a in attachments] == ["image/png", "application/pdf"]
    ticket_id = ok.json()["ticket"]["ticket_id"]
    download = await client.get(
        f"/api/v1/tickets/{ticket_id}/attachments/{attachments[0]['attachment_id']}/download", headers=h
    )
    assert download.status_code == 200
    assert download.content == PNG
    assert "filename*=UTF-8''" in download.headers["content-disposition"]
    assert download.headers["x-content-type-options"] == "nosniff"


async def test_create_is_idempotent_with_client_message_id(client: AsyncClient, people) -> None:
    h = people["h"]["req1"]
    client_id = str(uuid.uuid4())
    first = await _create(client, h, client_id=client_id)
    again = await _create(client, h, client_id=client_id)
    assert first.status_code == again.status_code == 201
    assert first.json()["ticket"]["ticket_id"] == again.json()["ticket"]["ticket_id"]
    mine = await client.get("/api/v1/tickets/mine", headers=h)
    assert mine.json()["total"] == 1


# ============================ العزل (IDOR) ============================


async def test_requester_sees_only_own_tickets(client: AsyncClient, people) -> None:
    t1 = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    await _create(client, people["h"]["req2"])
    await _create(client, people["h"]["req2"])

    mine1 = (await client.get("/api/v1/tickets/mine", headers=people["h"]["req1"])).json()
    mine2 = (await client.get("/api/v1/tickets/mine", headers=people["h"]["req2"])).json()
    assert mine1["total"] == 1 and mine1["items"][0]["ticket_id"] == t1
    assert mine2["total"] == 2
    assert (await client.get("/api/v1/tickets/mine", headers=people["h"]["plain"])).status_code == 403


async def test_other_users_ticket_is_404_everywhere(client: AsyncClient, people) -> None:
    created = (await _create(client, people["h"]["req1"], files=[("a.png", PNG, "image/png")])).json()
    tid = created["ticket"]["ticket_id"]
    att = created["message"]["attachments"][0]["attachment_id"]
    other = people["h"]["req2"]
    assert (await client.get(f"/api/v1/tickets/{tid}", headers=other)).status_code == 404
    assert (await client.get(f"/api/v1/tickets/{tid}/messages", headers=other)).status_code == 404
    assert (await _reply(client, other, tid, "تطفل")).status_code == 404
    assert (await client.post(f"/api/v1/tickets/{tid}/cancel", headers=other)).status_code == 404
    assert (
        await client.get(f"/api/v1/tickets/{tid}/attachments/{att}/download", headers=other)
    ).status_code == 404
    assert (await client.get(f"/api/v1/tickets/{tid}", headers=people["h"]["plain"])).status_code == 404
    assert (await client.get(f"/api/v1/tickets/{uuid.uuid4()}", headers=people["h"]["req1"])).status_code == 404


async def test_owner_without_permission_gets_403(client: AsyncClient, people) -> None:
    """صاحب التذكرة اللي انسحبت منه tickets.create: 403 (القسم 10 بالمواصفات)."""
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    async with AsyncSessionLocal() as db:
        perm_id = await db.scalar(select(Permission.permission_id).where(Permission.code == "tickets.create"))
        await db.execute(
            RolePermission.__table__.delete().where(
                RolePermission.role_id == people["roles"]["requester"], RolePermission.permission_id == perm_id
            )
        )
        await db.commit()
    assert (await client.get(f"/api/v1/tickets/{tid}", headers=people["h"]["req1"])).status_code == 403


# ============================ الدعم: القوائم والاستلام والإسناد ============================


async def test_support_tabs_and_claim_conflict(client: AsyncClient, people) -> None:
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    s1, s2 = people["h"]["sup1"], people["h"]["sup2"]

    assert (await client.get("/api/v1/tickets", headers=people["h"]["req1"])).status_code == 403
    unassigned = (await client.get("/api/v1/tickets?tab=unassigned", headers=s1)).json()
    assert [t["ticket_id"] for t in unassigned["items"]] == [tid]
    assert unassigned["items"][0]["viewer"] == "support"
    assert unassigned["items"][0]["priority"] == "medium"
    assert unassigned["items"][0]["requester"]["email"] == "req1@example.com"

    claimed = await client.post(f"/api/v1/tickets/{tid}/claim", headers=s1)
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["status"] == "in_progress"
    assert claimed.json()["assignee"]["user_id"] == str(people["ids"]["sup1"])
    assert claimed.json()["assignee_is_active_support"] is True

    conflict = await client.post(f"/api/v1/tickets/{tid}/claim", headers=s2)
    assert conflict.status_code == 409
    assert "استلمها" in conflict.json()["detail"]
    # الاستلام مرة ثانية من نفس العضو بدون تغيير
    assert (await client.post(f"/api/v1/tickets/{tid}/claim", headers=s1)).status_code == 200

    assert (await client.get("/api/v1/tickets?tab=unassigned", headers=s1)).json()["total"] == 0
    assert (await client.get("/api/v1/tickets?tab=mine", headers=s1)).json()["total"] == 1
    assert (await client.get("/api/v1/tickets?tab=mine", headers=s2)).json()["total"] == 0
    assert (await client.get("/api/v1/tickets?tab=all", headers=s2)).json()["total"] == 1

    requester_view = (await client.get(f"/api/v1/tickets/{tid}", headers=people["h"]["req1"])).json()
    assert requester_view["status"] == "in_progress"
    assert requester_view["actions"]["can_cancel"] is False


async def test_search_by_number_and_title(client: AsyncClient, people) -> None:
    await _create(client, people["h"]["req1"], title="الطباعة لا تعمل")
    second = (await _create(client, people["h"]["req1"], title="تعديل تقرير اللجان")).json()["ticket"]
    s1 = people["h"]["sup1"]
    by_number = (await client.get(f"/api/v1/tickets?q={second['ticket_number'].lower()}", headers=s1)).json()
    assert [t["ticket_id"] for t in by_number["items"]] == [second["ticket_id"]]
    by_suffix = (await client.get("/api/v1/tickets?q=0002", headers=s1)).json()
    assert by_suffix["total"] == 1
    by_title = (await client.get("/api/v1/tickets?q=الطباعة", headers=s1)).json()
    assert by_title["total"] == 1
    wildcard = (await client.get("/api/v1/tickets?q=%25", headers=s1)).json()
    assert wildcard["total"] == 0  # % حرفي، مو "أي شيء"


async def test_assign_rules_and_notification(client: AsyncClient, people) -> None:
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    s1 = people["h"]["sup1"]
    not_support = await client.post(
        f"/api/v1/tickets/{tid}/assign", json={"assignee_id": str(people["ids"]["req2"])}, headers=s1
    )
    assert not_support.status_code == 400
    assigned = await client.post(
        f"/api/v1/tickets/{tid}/assign", json={"assignee_id": str(people["ids"]["sup2"])}, headers=s1
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["status"] == "in_progress"
    await _wait_background()
    events = [n.event_type for n in await _notifications(people["ids"]["sup2"])]
    assert "ticket_assigned" in events

    members = (await client.get("/api/v1/tickets/support-members", headers=s1)).json()
    assert {m["user_id"] for m in members} == {str(people["ids"]["sup1"]), str(people["ids"]["sup2"])}
    assert (await client.get("/api/v1/tickets/support-members", headers=people["h"]["req1"])).status_code == 403


async def test_assignee_who_left_support_shows_as_unassigned(client: AsyncClient, people) -> None:
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    await client.post(f"/api/v1/tickets/{tid}/claim", headers=people["h"]["sup2"])
    async with AsyncSessionLocal() as db:
        await db.execute(UserRole.__table__.delete().where(UserRole.user_id == people["ids"]["sup2"]))
        await db.execute(
            User.__table__.update().where(User.user_id == people["ids"]["sup2"]).values(role_id=None)
        )
        await db.commit()
    unassigned = (await client.get("/api/v1/tickets?tab=unassigned", headers=people["h"]["sup1"])).json()
    assert [t["ticket_id"] for t in unassigned["items"]] == [tid]
    assert unassigned["items"][0]["assignee_is_active_support"] is False
    # عضو دعم فعّال يقدر يستلمها
    assert (await client.post(f"/api/v1/tickets/{tid}/claim", headers=people["h"]["sup1"])).status_code == 200


async def test_support_permissions_need_scope_all(client: AsyncClient, people) -> None:
    dept_role = await _make_role("دعم بنطاق إدارة", {"tickets.view_all": "department", "tickets.reply": "all"})
    await _make_user("dept_support", dept_role)
    h = await _login(client, "dept_support")
    assert (await client.get("/api/v1/tickets", headers=h)).status_code == 403

    reply_only = await _make_role("رد بدون عرض", {"tickets.reply": "all"})
    await _make_user("reply_only", reply_only)
    h2 = await _login(client, "reply_only")
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    assert (await _reply(client, h2, tid, "رد")).status_code == 404


# ============================ المحادثة والحالات ============================


async def test_support_reply_auto_assigns_and_waits_then_requester_reply(client: AsyncClient, people) -> None:
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    support_reply = await _reply(client, people["h"]["sup1"], tid, "ممكن تعطينا لقطة شاشة؟")
    assert support_reply.status_code == 201, support_reply.text
    ticket = support_reply.json()["ticket"]
    assert ticket["status"] == "waiting_on_requester"
    assert ticket["assignee"]["user_id"] == str(people["ids"]["sup1"])

    await _wait_background()
    requester_events = [n.event_type for n in await _notifications(people["ids"]["req1"])]
    assert requester_events.count("ticket_replied") == 1  # إشعار واحد للرد مع تغيير الحالة

    requester_reply = await _reply(
        client, people["h"]["req1"], tid, "", files=[("screen.png", PNG, "image/png")]
    )
    assert requester_reply.status_code == 201, requester_reply.text
    assert requester_reply.json()["ticket"]["status"] == "in_progress"
    assert requester_reply.json()["message"]["author_side"] == "requester"

    await _wait_background()
    assert "ticket_replied" in [n.event_type for n in await _notifications(people["ids"]["sup1"])]
    # عضو الدعم الثاني ما يوصله لأن التذكرة مسندة
    assert "ticket_replied" not in [n.event_type for n in await _notifications(people["ids"]["sup2"])]


async def test_resolve_then_reopen_by_requester(client: AsyncClient, people) -> None:
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    resolved = await _reply(client, people["h"]["sup1"], tid, "تم الإصلاح", status_after="resolved")
    assert resolved.json()["ticket"]["status"] == "resolved"
    assert resolved.json()["ticket"]["resolved_at"] is not None

    reopened = await _reply(client, people["h"]["req1"], tid, "للأسف ما زالت المشكلة موجودة")
    assert reopened.json()["ticket"]["status"] == "in_progress"
    assert reopened.json()["ticket"]["resolved_at"] is None
    assert reopened.json()["ticket"]["assignee"]["user_id"] == str(people["ids"]["sup1"])

    await _wait_background()
    assert "ticket_resolved" in [n.event_type for n in await _notifications(people["ids"]["req1"])]
    assert "ticket_reopened" in [n.event_type for n in await _notifications(people["ids"]["sup1"])]


async def test_support_reply_keeps_resolved_ticket_resolved(client: AsyncClient, people) -> None:
    """إعادة الفتح برد مقدّم الطلب فقط — رد الدعم على المحلولة يبقيها محلولة."""
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    await _reply(client, people["h"]["sup1"], tid, "تم", status_after="resolved")
    follow_up = await _reply(client, people["h"]["sup1"], tid, "معلومة إضافية")
    assert follow_up.status_code == 201
    assert follow_up.json()["ticket"]["status"] == "resolved"
    assert (await _reply(client, people["h"]["sup1"], tid, "نفتحها", status_after="waiting_on_requester")).status_code == 409


async def test_requester_cannot_set_status_or_write_internal(client: AsyncClient, people) -> None:
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    assert (await _reply(client, people["h"]["req1"], tid, "حل", status_after="resolved")).status_code == 400
    assert (await _reply(client, people["h"]["req1"], tid, "داخلي", internal=True)).status_code == 403
    assert (await client.post(f"/api/v1/tickets/{tid}/status", json={"status": "resolved"}, headers=people["h"]["req1"])).status_code == 403
    assert (await client.post(f"/api/v1/tickets/{tid}/claim", headers=people["h"]["req1"])).status_code == 403
    assert (await client.get(f"/api/v1/tickets/{tid}/history", headers=people["h"]["req1"])).status_code == 403
    assert (await _reply(client, people["h"]["req1"], tid, "")).status_code == 400  # بدون نص ولا مرفق


async def test_internal_notes_never_reach_requester(client: AsyncClient, people) -> None:
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    note = await _reply(
        client, people["h"]["sup1"], tid, "سبب المشكلة في الـ API", internal=True, files=[("log.pdf", PDF, "application/pdf")]
    )
    assert note.status_code == 201, note.text
    assert note.json()["message"]["is_internal"] is True
    assert note.json()["ticket"]["status"] == "new"  # الملاحظة ما تغيّر الحالة
    note_attachment = note.json()["message"]["attachments"][0]["attachment_id"]

    requester_messages = (await client.get(f"/api/v1/tickets/{tid}/messages", headers=people["h"]["req1"])).json()
    assert all(not m["is_internal"] for m in requester_messages)
    assert len(requester_messages) == 1
    support_messages = (await client.get(f"/api/v1/tickets/{tid}/messages", headers=people["h"]["sup2"])).json()
    assert len(support_messages) == 2

    assert (
        await client.get(f"/api/v1/tickets/{tid}/attachments/{note_attachment}/download", headers=people["h"]["req1"])
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/tickets/{tid}/attachments/{note_attachment}/download", headers=people["h"]["sup2"])
    ).status_code == 200

    await _wait_background()
    assert await _notifications(people["ids"]["req1"]) == []  # الملاحظات ما لها إشعار


async def test_message_retry_is_idempotent(client: AsyncClient, people) -> None:
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    client_id = str(uuid.uuid4())
    first = await _reply(client, people["h"]["req1"], tid, "رسالة واحدة", client_id=client_id)
    again = await _reply(client, people["h"]["req1"], tid, "رسالة واحدة", client_id=client_id)
    assert first.json()["message"]["message_id"] == again.json()["message"]["message_id"]
    messages = (await client.get(f"/api/v1/tickets/{tid}/messages", headers=people["h"]["req1"])).json()
    assert len(messages) == 2  # الوصف + رسالة واحدة


async def test_manual_status_rules(client: AsyncClient, people) -> None:
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    s1 = people["h"]["sup1"]

    async def status_to(value: str):
        return await client.post(f"/api/v1/tickets/{tid}/status", json={"status": value}, headers=s1)

    assert (await status_to("in_progress")).status_code == 409  # "جديدة" تتحرك بالاستلام
    await client.post(f"/api/v1/tickets/{tid}/claim", headers=s1)
    assert (await status_to("waiting_on_requester")).json()["status"] == "waiting_on_requester"
    assert (await status_to("in_progress")).json()["status"] == "in_progress"
    resolved = await status_to("resolved")
    assert resolved.json()["status"] == "resolved"
    assert (await status_to("in_progress")).status_code == 409  # إعادة الفتح برد مقدّم الطلب فقط
    assert (await status_to("closed")).status_code == 422  # الإغلاق تلقائي فقط

    await _wait_background()
    assert "ticket_resolved" in [n.event_type for n in await _notifications(people["ids"]["req1"])]


async def test_cancel_only_while_new(client: AsyncClient, people) -> None:
    t1 = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    cancelled = await client.post(f"/api/v1/tickets/{t1}/cancel", headers=people["h"]["req1"])
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["actions"]["can_reply"] is False
    assert (await _reply(client, people["h"]["req1"], t1, "رد")).status_code == 409
    assert (await client.post(f"/api/v1/tickets/{t1}/claim", headers=people["h"]["sup1"])).status_code == 409

    t2 = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    await client.post(f"/api/v1/tickets/{t2}/claim", headers=people["h"]["sup1"])
    assert (await client.post(f"/api/v1/tickets/{t2}/cancel", headers=people["h"]["req1"])).status_code == 409
    assert (await client.post(f"/api/v1/tickets/{t2}/cancel", headers=people["h"]["sup1"])).status_code == 403


async def test_update_fields_and_history(client: AsyncClient, people) -> None:
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    s1 = people["h"]["sup1"]
    await client.post(f"/api/v1/tickets/{tid}/claim", headers=s1)
    patched = await client.patch(
        f"/api/v1/tickets/{tid}", json={"priority": "urgent", "module": "users_departments"}, headers=s1
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["priority"] == "urgent"
    assert (await client.patch(f"/api/v1/tickets/{tid}", json={"title": "عنوان جديد"}, headers=s1)).status_code == 422
    assert (await client.patch(f"/api/v1/tickets/{tid}", json={"priority": "high"}, headers=people["h"]["req1"])).status_code == 403

    requester_view = (await client.get(f"/api/v1/tickets/{tid}", headers=people["h"]["req1"])).json()
    assert requester_view["priority"] is None
    assert requester_view["module"] == "users_departments"

    history = (await client.get(f"/api/v1/tickets/{tid}/history", headers=s1)).json()
    events = [(e["event"], e["from_value"], e["to_value"]) for e in history]
    assert events[0][0] == "created"
    assert ("status_changed", "new", "in_progress") in events
    assert ("priority_changed", "medium", "urgent") in events
    assert ("module_changed", "meetings", "users_departments") in events
    assigned = next(e for e in history if e["event"] == "assigned")
    assert assigned["to_value"].startswith("فهد") and assigned["actor"]["user_id"] == str(people["ids"]["sup1"])


async def test_auto_close_after_four_days(client: AsyncClient, people) -> None:
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    other = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    await _reply(client, people["h"]["sup1"], tid, "تم", status_after="resolved")
    await _reply(client, people["h"]["sup1"], other, "تم", status_after="resolved")
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE tickets SET resolved_at = now() - interval '5 days' WHERE ticket_id = :t"), {"t": tid}
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        closed = await ticket_service.auto_close_resolved(db)
    assert [c.ticket_id for c in closed] == [uuid.UUID(tid)]

    view = (await client.get(f"/api/v1/tickets/{tid}", headers=people["h"]["req1"])).json()
    assert view["status"] == "closed" and view["closed_at"] is not None
    assert (await client.get(f"/api/v1/tickets/{other}", headers=people["h"]["req1"])).json()["status"] == "resolved"
    assert (await _reply(client, people["h"]["req1"], tid, "رد متأخر")).status_code == 409

    history = (await client.get(f"/api/v1/tickets/{tid}/history", headers=people["h"]["sup1"])).json()
    auto = history[-1]
    assert auto["event"] == "status_changed" and auto["to_value"] == "closed" and auto["actor"] is None


# ============================ الكتالوج والاشتراك اللحظي ============================


async def test_permissions_marked_enforced(client: AsyncClient, auth_headers) -> None:
    catalog = (await client.get("/api/v1/permissions", headers=auth_headers)).json()
    tickets = [p for p in catalog if p["category"] == "tickets"]
    assert {p["code"] for p in tickets} == {"tickets.create", *SUPPORT_CODES}
    assert all(p["is_enforced"] for p in tickets)


async def test_realtime_subscribe_follows_ticket_access(client: AsyncClient, people, monkeypatch) -> None:
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    rooms: dict[str, list[str]] = {}
    sessions: dict[str, dict] = {}

    async def fake_get_session(sid, namespace=None):
        return sessions[sid]

    async def fake_enter_room(sid, room, namespace=None):
        rooms.setdefault(sid, []).append(room)

    monkeypatch.setattr(ticket_realtime.sio, "get_session", fake_get_session)
    monkeypatch.setattr(ticket_realtime.sio, "enter_room", fake_enter_room)
    async with AsyncSessionLocal() as db:
        for name in ("req1", "req2", "sup1"):
            sessions[name] = {"user": await user_service.get_user(db, people["ids"][name])}

    assert await ticket_realtime.tickets_subscribe("req1", {"ticket_id": tid}) == {"ok": True, "viewer": "requester"}
    assert rooms["req1"] == [f"ticket:{tid}"]
    assert await ticket_realtime.tickets_subscribe("sup1", {"ticket_id": tid}) == {"ok": True, "viewer": "support"}
    assert rooms["sup1"] == [f"ticket:{tid}", f"ticket:{tid}:support"]
    assert await ticket_realtime.tickets_subscribe("req2", {"ticket_id": tid}) == {"ok": False}
    assert "req2" not in rooms
    assert await ticket_realtime.tickets_subscribe("req1", {"ticket_id": "not-a-uuid"}) == {"ok": False}


async def test_internal_note_broadcast_goes_to_support_room_only(client: AsyncClient, people, monkeypatch) -> None:
    emitted: list[tuple[str, str]] = []

    async def fake_emit(event, data, room=None, namespace=None):
        emitted.append((event, room))

    monkeypatch.setattr(ticket_realtime.sio, "emit", fake_emit)
    tid = (await _create(client, people["h"]["req1"])).json()["ticket"]["ticket_id"]
    await _reply(client, people["h"]["sup1"], tid, "ملاحظة", internal=True)
    await _wait_background()
    assert emitted == [("ticket.message", f"ticket:{tid}:support")]

    emitted.clear()
    await _reply(client, people["h"]["sup1"], tid, "رد عام")
    await _wait_background()
    assert ("ticket.message", f"ticket:{tid}") in emitted
    assert ("ticket.updated", f"ticket:{tid}") in emitted
