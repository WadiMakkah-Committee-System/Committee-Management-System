"""
اختبارات دخول الضيوف للاجتماع برابط عام (migration 0047 — قرار لاما 2026-11-10).

يغطي: رابط الضيوف وصلاحياته، صفحة الدعوة العامة، طلب الدخول وقبوله/رفضه،
حصر توكن الضيف باجتماعه فقط، منع الدخول بكلمة المرور، إخفاء الضيوف من
قائمة المستخدمين، حد الطلبات، وانتهاء جلسة الضيف بانتهاء الاجتماع.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.meeting import Meeting
from app.models.user import User
from tests.test_meetings import _create_approved_committee, _grant_committee_role_permissions


@pytest.fixture(autouse=True)
def _agora_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AGORA_APP_ID", "test-app-id")
    monkeypatch.setattr(settings, "AGORA_APP_CERTIFICATE", "0123456789abcdef0123456789abcdef")
    monkeypatch.setattr(settings, "MEETING_PROVIDER", "agora")


def _slot(hours_from_now: float = 1) -> tuple[str, str]:
    start = (datetime.now(UTC) + timedelta(hours=hours_from_now)).replace(second=0, microsecond=0)
    return start.isoformat(), (start + timedelta(hours=1)).isoformat()


async def _create_meeting(client: AsyncClient, ctx: dict, *, mode: str = "remote", title: str = "اجتماع بضيوف") -> str:
    start, end = _slot()
    response = await client.post(
        "/api/v1/meetings",
        json={
            "committee_id": ctx["committee_id"],
            "title": title,
            "mode": mode,
            "scheduled_at": start,
            "scheduled_end_at": end,
            **({"location": "قاعة 1"} if mode == "in_person" else {}),
        },
        headers=ctx["chair_headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()["meeting_id"]


async def _setup(client: AsyncClient, auth_headers, roles_by_name) -> dict:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    await _grant_committee_role_permissions(["meetings.join"], slug="chair")
    await _grant_committee_role_permissions(["meetings.join"], slug="member")
    ctx["meeting_id"] = await _create_meeting(client, ctx)
    return ctx


async def _guest_link(client: AsyncClient, ctx: dict) -> str:
    response = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/guest-link", headers=ctx["member_headers"])
    assert response.status_code == 200, response.text
    return response.json()["token"]


async def _request_join(client: AsyncClient, token: str, name: str = "أحمد الضيف", ip: str = "10.0.0.1") -> dict:
    response = await client.post(
        f"/api/v1/public/meeting-invites/{token}/requests",
        json={"display_name": name},
        headers={"X-Forwarded-For": ip},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _status(client: AsyncClient, req: dict):
    return await client.post(
        f"/api/v1/public/guest-requests/{req['request_id']}/status", json={"secret": req["secret"]}
    )


async def _admitted_guest(client: AsyncClient, ctx: dict, name: str = "أحمد الضيف") -> dict:
    token = await _guest_link(client, ctx)
    req = await _request_join(client, token, name)
    admit = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/guest-requests/{req['request_id']}/admit",
        headers=ctx["chair_headers"],
    )
    assert admit.status_code == 200, admit.text
    status = await _status(client, req)
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["status"] == "admitted" and body["access_token"], body
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"}, "body": body, "req": req}


# ============================== رابط الضيوف ==============================


async def test_guest_link_for_meeting_members_only(client: AsyncClient, auth_headers, roles_by_name) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    url = f"/api/v1/meetings/{ctx['meeting_id']}/guest-link"

    first = await client.get(url, headers=ctx["member_headers"])
    assert first.status_code == 200, first.text
    token = first.json()["token"]
    assert len(token) >= 40 and ctx["meeting_id"] not in token

    # نفس الرابط في كل مرة (لا يتغيّر إلا بـrotate).
    again = await client.get(url, headers=ctx["chair_headers"])
    assert again.json()["token"] == token

    outsider = await client.get(url, headers=ctx["outsider_headers"])
    assert outsider.status_code == 403, outsider.text


async def test_rotate_link_disables_old_one(client: AsyncClient, auth_headers, roles_by_name) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    old = await _guest_link(client, ctx)

    # العضو العادي لا يملك meetings.update ⇒ لا يغيّر الرابط.
    denied = await client.post(f"/api/v1/meetings/{ctx['meeting_id']}/guest-link/rotate", headers=ctx["member_headers"])
    assert denied.status_code == 403, denied.text

    rotated = await client.post(f"/api/v1/meetings/{ctx['meeting_id']}/guest-link/rotate", headers=ctx["chair_headers"])
    assert rotated.status_code == 200, rotated.text
    new = rotated.json()["token"]
    assert new != old

    assert (await client.get(f"/api/v1/public/meeting-invites/{old}")).status_code == 404
    assert (await client.get(f"/api/v1/public/meeting-invites/{new}")).status_code == 200


async def test_in_person_meeting_has_no_guest_link(client: AsyncClient, auth_headers, roles_by_name) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    in_person = await _create_meeting(client, ctx, mode="in_person", title="حضوري")
    response = await client.get(f"/api/v1/meetings/{in_person}/guest-link", headers=ctx["chair_headers"])
    assert response.status_code == 409, response.text


# ============================== صفحة الدعوة وطلب الدخول ==============================


async def test_public_invite_shows_minimal_info(client: AsyncClient, auth_headers, roles_by_name) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    token = await _guest_link(client, ctx)

    invite = await client.get(f"/api/v1/public/meeting-invites/{token}")
    assert invite.status_code == 200, invite.text
    body = invite.json()
    assert body["title"] == "اجتماع بضيوف"
    assert body["committee_name"] == "لجنة الاجتماعات التجريبية"
    assert body["is_open"] is True
    # لا أعضاء ولا أجندة ولا معرّف الاجتماع.
    assert set(body) == {"title", "committee_name", "scheduled_at", "scheduled_end_at", "status", "is_open"}

    assert (await client.get("/api/v1/public/meeting-invites/not-a-real-token")).status_code == 404


async def test_join_request_validation(client: AsyncClient, auth_headers, roles_by_name) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    token = await _guest_link(client, ctx)
    too_short = await client.post(f"/api/v1/public/meeting-invites/{token}/requests", json={"display_name": " أ "})
    assert too_short.status_code == 400, too_short.text


async def test_admit_flow_issues_guest_session(client: AsyncClient, auth_headers, roles_by_name) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    token = await _guest_link(client, ctx)
    req = await _request_join(client, token)

    pending = await _status(client, req)
    assert pending.json() == {
        "status": "pending", "meeting_id": None, "access_token": None, "refresh_token": None, "user": None,
    }

    # رمز سري خاطئ ⇒ 404 (بدون كشف وجود الطلب).
    wrong = await client.post(f"/api/v1/public/guest-requests/{req['request_id']}/status", json={"secret": "x"})
    assert wrong.status_code == 404

    waiting = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/guest-requests", headers=ctx["member_headers"])
    assert waiting.status_code == 200
    assert [w["display_name"] for w in waiting.json()] == ["أحمد الضيف"]

    # من خارج الاجتماع لا يشوف ولا يقبل.
    assert (
        await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/guest-requests", headers=ctx["outsider_headers"])
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/meetings/{ctx['meeting_id']}/guest-requests/{req['request_id']}/admit",
            headers=ctx["outsider_headers"],
        )
    ).status_code == 403

    # أي عضو داخل الاجتماع يقبل (ليس الرئيس فقط).
    admit = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/guest-requests/{req['request_id']}/admit",
        headers=ctx["member_headers"],
    )
    assert admit.status_code == 200, admit.text
    assert admit.json()["status"] == "admitted"

    # قبول مرة ثانية ⇒ 409 (لا حساب ثانٍ).
    twice = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/guest-requests/{req['request_id']}/admit",
        headers=ctx["chair_headers"],
    )
    assert twice.status_code == 409

    admitted = (await _status(client, req)).json()
    assert admitted["status"] == "admitted"
    assert admitted["meeting_id"] == ctx["meeting_id"]
    assert admitted["access_token"] and admitted["refresh_token"]
    assert admitted["user"]["first_name"] == "أحمد الضيف"

    async with AsyncSessionLocal() as db:
        guest = (await db.execute(select(User).where(User.first_name == "أحمد الضيف"))).scalar_one()
        assert guest.is_guest is True
        assert str(guest.guest_meeting_id) == ctx["meeting_id"]
        assert guest.role_id is None


async def test_reject_flow(client: AsyncClient, auth_headers, roles_by_name) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    req = await _request_join(client, await _guest_link(client, ctx))
    reject = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/guest-requests/{req['request_id']}/reject",
        headers=ctx["chair_headers"],
    )
    assert reject.status_code == 200, reject.text
    body = (await _status(client, req)).json()
    assert body["status"] == "rejected" and body["access_token"] is None


async def test_guest_can_cancel_own_request(client: AsyncClient, auth_headers, roles_by_name) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    req = await _request_join(client, await _guest_link(client, ctx))
    cancel = await client.post(
        f"/api/v1/public/guest-requests/{req['request_id']}/cancel", json={"secret": req["secret"]}
    )
    assert cancel.status_code == 204
    assert (await _status(client, req)).json()["status"] == "cancelled"
    waiting = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/guest-requests", headers=ctx["chair_headers"])
    assert waiting.json() == []


async def test_rate_limit_per_ip(client: AsyncClient, auth_headers, roles_by_name) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    token = await _guest_link(client, ctx)
    for i in range(8):
        await _request_join(client, token, name=f"ضيف رقم {i}", ip="10.9.9.9")
    blocked = await client.post(
        f"/api/v1/public/meeting-invites/{token}/requests",
        json={"display_name": "ضيف زائد"},
        headers={"X-Forwarded-For": "10.9.9.9"},
    )
    assert blocked.status_code == 429, blocked.text
    # عنوان آخر لا يتأثر.
    await _request_join(client, token, name="ضيف من جهاز آخر", ip="10.9.9.10")


# ============================== حصر الضيف باجتماعه ==============================


async def test_guest_token_is_scoped_to_its_meeting(client: AsyncClient, auth_headers, roles_by_name) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    other_meeting = await _create_meeting(client, ctx, title="اجتماع آخر بنفس اللجنة")
    guest = await _admitted_guest(client, ctx)
    h = guest["headers"]

    # اجتماعه: مسموح (بصلاحيات عضو اللجنة).
    own = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}", headers=h)
    assert own.status_code == 200, own.text
    me = await client.get("/api/v1/users/me", headers=h)
    assert me.status_code == 200, me.text
    join = await client.post(f"/api/v1/meetings/{ctx['meeting_id']}/agora/join", headers=h)
    assert join.status_code == 200, join.text

    # أي شيء آخر بالمنصة: ممنوع — حتى اجتماع آخر بنفس اللجنة.
    for method, path in [
        ("GET", f"/api/v1/meetings/{other_meeting}"),
        ("GET", "/api/v1/meetings"),
        ("GET", "/api/v1/users"),
        ("GET", "/api/v1/committees"),
        ("GET", f"/api/v1/committees/{ctx['committee_id']}"),
        ("GET", "/api/v1/documents"),
        ("GET", "/api/v1/tasks"),
        ("GET", "/api/v1/decisions"),
        ("GET", f"/api/v1/decisions?meeting_id={other_meeting}"),
        ("GET", "/api/v1/dashboard/summary"),
        ("GET", "/api/v1/notifications"),
        ("GET", "/api/v1/audit-logs"),
    ]:
        response = await client.request(method, path, headers=h)
        assert response.status_code == 403, (path, response.status_code, response.text)

    # قرارات اجتماعه: مسموح.
    own_decisions = await client.get(f"/api/v1/decisions?meeting_id={ctx['meeting_id']}", headers=h)
    assert own_decisions.status_code != 403, own_decisions.text


async def test_guest_can_admit_other_guests(client: AsyncClient, auth_headers, roles_by_name) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    first = await _admitted_guest(client, ctx, name="الضيف الأول")
    second = await _request_join(client, await _guest_link(client, ctx), name="الضيف الثاني", ip="10.0.0.2")
    admit = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/guest-requests/{second['request_id']}/admit",
        headers=first["headers"],
    )
    assert admit.status_code == 200, admit.text


async def test_guest_cannot_login_with_password(client: AsyncClient, auth_headers, roles_by_name) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    await _admitted_guest(client, ctx)
    async with AsyncSessionLocal() as db:
        guest = (await db.execute(select(User).where(User.is_guest.is_(True)))).scalar_one()
    for identifier in (guest.username, guest.email):
        login = await client.post("/api/v1/auth/login", json={"username": identifier, "password": "anything1A"})
        assert login.status_code == 401


async def test_guests_hidden_from_users_list_and_shown_on_meeting(
    client: AsyncClient, auth_headers, roles_by_name
) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    await _admitted_guest(client, ctx, name="ضيفة خارجية")

    users = await client.get("/api/v1/users", headers=auth_headers)
    assert users.status_code == 200, users.text
    assert all(u["first_name"] != "ضيفة خارجية" for u in users.json())

    meeting = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}", headers=ctx["chair_headers"])
    guests = meeting.json()["guests"]
    assert [g["first_name"] for g in guests] == ["ضيفة خارجية"]
    assert guests[0]["is_guest"] is True and guests[0]["email"] == ""


async def test_guest_session_ends_with_meeting(client: AsyncClient, auth_headers, roles_by_name) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    guest = await _admitted_guest(client, ctx)
    pending = await _request_join(client, await _guest_link(client, ctx), name="متأخر", ip="10.0.0.3")

    past = datetime.now(UTC) - timedelta(minutes=5)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Meeting)
            .where(Meeting.meeting_id == ctx["meeting_id"])
            .values(scheduled_at=past - timedelta(hours=1), scheduled_end_at=past)
        )
        await db.commit()

    after = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}", headers=guest["headers"])
    assert after.status_code == 401, after.text
    refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": guest["body"]["refresh_token"]})
    assert refresh.status_code == 401

    # الطلب المنتظر يتحوّل "ملغى"، والرابط ما عاد يقبل طلبات.
    assert (await _status(client, pending)).json()["status"] == "cancelled"
    token = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/guest-link", headers=ctx["chair_headers"])
    assert token.status_code == 409


# ============================== التصويت ==============================


async def test_guest_vote_counts_in_its_meeting_decisions_only(
    client: AsyncClient, auth_headers, roles_by_name
) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    await _grant_committee_role_permissions(
        ["decisions.view", "decisions.create", "decisions.vote.open", "decisions.vote.cast"], slug="chair"
    )
    await _grant_committee_role_permissions(["decisions.view", "decisions.vote.cast"], slug="member")
    other_meeting = await _create_meeting(client, ctx, title="اجتماع آخر")
    guest = await _admitted_guest(client, ctx)

    async def _voting_decision(meeting_id: str) -> tuple[str, dict[str, str]]:
        create = await client.post(
            "/api/v1/decisions",
            json={
                "committee_id": ctx["committee_id"],
                "meeting_id": meeting_id,
                "title": "قرار للتصويت",
                "classification": "voting",
                "start_date": "2026-11-01",
                "end_date": "2026-11-30",
            },
            headers=ctx["chair_headers"],
        )
        assert create.status_code == 201, create.text
        decision_id = create.json()["decision_id"]
        opened = await client.post(f"/api/v1/decisions/{decision_id}/open-voting", json={}, headers=ctx["chair_headers"])
        assert opened.status_code == 200, opened.text
        return decision_id, {o["label"]: o["option_id"] for o in opened.json()["vote_options"]}

    decision_id, options = await _voting_decision(ctx["meeting_id"])

    async def vote(headers, label: str):
        return await client.post(
            f"/api/v1/decisions/{decision_id}/vote", json={"option_id": options[label]}, headers=headers
        )

    # الضيف يصوّت (مثل العضو) ولا يُغلق التصويت بانتظار الأعضاء.
    g = await vote(guest["headers"], "موافق")
    assert g.status_code == 200, g.text
    assert g.json()["voting_closed_at"] is None
    assert (await vote(ctx["chair_headers"], "موافق")).status_code == 200
    last = await vote(ctx["member_headers"], "غير موافق")
    assert last.status_code == 200, last.text
    body = last.json()
    # أُغلق بتصويت آخر عضو. بدون صوت الضيف: 1 من 2 (لا أغلبية ⇒ رفض تلقائي).
    # مع صوت الضيف: 2 من 3 ⇒ أغلبية ⇒ يبقى بانتظار اعتماد الرئيس.
    assert body["voting_closed_at"] is not None
    assert body["status"] == "voting", body

    # قرار اجتماع آخر بنفس اللجنة: ممنوع على الضيف تمامًا.
    other_decision, other_options = await _voting_decision(other_meeting)
    denied = await client.post(
        f"/api/v1/decisions/{other_decision}/vote",
        json={"option_id": other_options["موافق"]},
        headers=guest["headers"],
    )
    assert denied.status_code == 403, denied.text
