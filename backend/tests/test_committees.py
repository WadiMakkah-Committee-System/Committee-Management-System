"""
اختبارات وحدة "طلبات تشكيل اللجان" — Phase 2 (RF-COM-100 → RF-COM-700).

تغطي: التدفق الكامل الناجح (draft → submitted → pending_approval →
approved، مع إنشاء اللجنة فعليًا)، الرفض، RBAC (كل انتقال بدوره الصحيح
فقط)، قيود التعديل حسب الحالة والملكية، وEdge Cases (تواريخ غير صحيحة،
أعضاء غير موجودين، تكرار عضو، انتقال حالة غير صالح).
"""

import uuid

from httpx import AsyncClient

from app.models.user import User


async def _create_user_with_role(
    client: AsyncClient,
    auth_headers: dict[str, str],
    roles_by_name: dict[str, str],
    *,
    username: str,
    role_name: str,
) -> dict[str, str]:
    """ينشئ مستخدمًا بدور معيّن، يسجّل دخوله، ويرجع headers جاهزة للاستخدام."""
    create = await client.post(
        "/api/v1/users",
        json={
            "first_name": "أ",
            "middle_name": "ب",
            "last_name": "ج",
            "username": username,
            "email": f"{username}@example.com",
            "password": "StrongPass1",
            "role_id": roles_by_name[role_name],
            "dep_id": None,
        },
        headers=auth_headers,
    )
    assert create.status_code == 201, create.text
    user_id = create.json()["user_id"]

    login = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "StrongPass1"}
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user_id


async def _setup_actors(
    client: AsyncClient, auth_headers: dict[str, str], roles_by_name: dict[str, str]
) -> dict:
    admin_headers, admin_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="cf_admin", role_name="admin"
    )
    office_headers, _ = await _create_user_with_role(
        client,
        auth_headers,
        roles_by_name,
        username="cf_office",
        role_name="executive_office_manager",
    )
    ceo_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="cf_ceo", role_name="executive_president"
    )
    member_headers, member_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="cf_member1", role_name="admin"
    )
    return {
        "admin_headers": admin_headers,
        "admin_id": admin_id,
        "office_headers": office_headers,
        "ceo_headers": ceo_headers,
        "member_id": member_id,
    }


def _valid_payload(member_id: str, *, name: str = "لجنة الجودة") -> dict:
    return {
        "committee_name": name,
        "statement": "بيان اللجنة",
        "start_date": "2026-09-01",
        "end_date": "2026-12-01",
        "proposed_member_ids": [member_id],
    }


async def test_full_approval_flow_creates_committee(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)

    create = await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"]),
        headers=actors["admin_headers"],
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["status"] == "draft"
    request_id = body["request_id"]

    submit = await client.post(
        f"/api/v1/committee-requests/{request_id}/submit", headers=actors["admin_headers"]
    )
    assert submit.status_code == 200, submit.text
    assert submit.json()["status"] == "submitted"

    escalate = await client.post(
        f"/api/v1/committee-requests/{request_id}/escalate", headers=actors["office_headers"]
    )
    assert escalate.status_code == 200, escalate.text
    assert escalate.json()["status"] == "pending_approval"

    approve = await client.post(
        f"/api/v1/committee-requests/{request_id}/approve", headers=actors["ceo_headers"]
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "approved"

    committees = await client.get("/api/v1/committees", headers=actors["admin_headers"])
    assert committees.status_code == 200, committees.text
    created = [c for c in committees.json() if c["source_request_id"] == request_id]
    assert len(created) == 1
    assert created[0]["name"] == "لجنة الجودة"
    assert [m["user_id"] for m in created[0]["members"]] == [actors["member_id"]]


async def test_reject_flow_requires_reason_and_is_final(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)

    create = await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"]),
        headers=actors["admin_headers"],
    )
    request_id = create.json()["request_id"]
    await client.post(f"/api/v1/committee-requests/{request_id}/submit", headers=actors["admin_headers"])
    await client.post(f"/api/v1/committee-requests/{request_id}/escalate", headers=actors["office_headers"])

    missing_reason = await client.post(
        f"/api/v1/committee-requests/{request_id}/reject", json={}, headers=actors["ceo_headers"]
    )
    assert missing_reason.status_code == 422

    reject = await client.post(
        f"/api/v1/committee-requests/{request_id}/reject",
        json={"rejection_reason": "لا حاجة فعلية للجنة حاليًا"},
        headers=actors["ceo_headers"],
    )
    assert reject.status_code == 200, reject.text
    assert reject.json()["status"] == "rejected"

    # نهائية: لا اعتماد بعد الرفض
    approve_after_reject = await client.post(
        f"/api/v1/committee-requests/{request_id}/approve", headers=actors["ceo_headers"]
    )
    assert approve_after_reject.status_code == 409


async def test_admin_cannot_escalate_or_approve(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    create = await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"]),
        headers=actors["admin_headers"],
    )
    request_id = create.json()["request_id"]
    await client.post(f"/api/v1/committee-requests/{request_id}/submit", headers=actors["admin_headers"])

    forbidden_escalate = await client.post(
        f"/api/v1/committee-requests/{request_id}/escalate", headers=actors["admin_headers"]
    )
    assert forbidden_escalate.status_code == 403

    forbidden_approve = await client.post(
        f"/api/v1/committee-requests/{request_id}/approve", headers=actors["admin_headers"]
    )
    assert forbidden_approve.status_code == 403


async def test_office_cannot_create_or_approve(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)

    forbidden_create = await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"]),
        headers=actors["office_headers"],
    )
    assert forbidden_create.status_code == 403

    create = await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"]),
        headers=actors["admin_headers"],
    )
    request_id = create.json()["request_id"]
    await client.post(f"/api/v1/committee-requests/{request_id}/submit", headers=actors["admin_headers"])
    await client.post(f"/api/v1/committee-requests/{request_id}/escalate", headers=actors["office_headers"])

    forbidden_approve = await client.post(
        f"/api/v1/committee-requests/{request_id}/approve", headers=actors["office_headers"]
    )
    assert forbidden_approve.status_code == 403


async def test_admin_can_edit_own_draft_but_not_after_submit(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    create = await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"]),
        headers=actors["admin_headers"],
    )
    request_id = create.json()["request_id"]

    edit_draft = await client.patch(
        f"/api/v1/committee-requests/{request_id}",
        json={"committee_name": "لجنة الجودة المعدّلة"},
        headers=actors["admin_headers"],
    )
    assert edit_draft.status_code == 200, edit_draft.text
    assert edit_draft.json()["committee_name"] == "لجنة الجودة المعدّلة"

    await client.post(f"/api/v1/committee-requests/{request_id}/submit", headers=actors["admin_headers"])

    edit_after_submit = await client.patch(
        f"/api/v1/committee-requests/{request_id}",
        json={"committee_name": "محاولة تعديل بعد الإرسال"},
        headers=actors["admin_headers"],
    )
    assert edit_after_submit.status_code == 403


async def test_office_can_edit_submitted_request_without_ownership(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """المكتب التنفيذي يعدّل مباشرة بعد الإرسال — بدون أي مسار إرجاع للادمن (قرار موثّق)."""
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    create = await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"]),
        headers=actors["admin_headers"],
    )
    request_id = create.json()["request_id"]
    await client.post(f"/api/v1/committee-requests/{request_id}/submit", headers=actors["admin_headers"])

    edit = await client.patch(
        f"/api/v1/committee-requests/{request_id}",
        json={"statement": "بيان معدَّل من المكتب التنفيذي"},
        headers=actors["office_headers"],
    )
    assert edit.status_code == 200, edit.text
    assert edit.json()["statement"] == "بيان معدَّل من المكتب التنفيذي"


async def test_admin_sees_only_own_requests_office_sees_all(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    other_admin_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="cf_admin2", role_name="admin"
    )

    await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"], name="لجنة 1"),
        headers=actors["admin_headers"],
    )
    await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"], name="لجنة 2"),
        headers=other_admin_headers,
    )

    admin_view = await client.get("/api/v1/committee-requests", headers=actors["admin_headers"])
    assert admin_view.status_code == 200
    assert {r["committee_name"] for r in admin_view.json()} == {"لجنة 1"}

    office_view = await client.get("/api/v1/committee-requests", headers=actors["office_headers"])
    assert office_view.status_code == 200
    assert {r["committee_name"] for r in office_view.json()} == {"لجنة 1", "لجنة 2"}


async def test_invalid_dates_rejected(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    payload = _valid_payload(actors["member_id"])
    payload["end_date"] = "2026-01-01"  # قبل start_date
    response = await client.post(
        "/api/v1/committee-requests", json=payload, headers=actors["admin_headers"]
    )
    assert response.status_code == 422


async def test_unknown_member_rejected(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    payload = _valid_payload(str(uuid.uuid4()))
    response = await client.post(
        "/api/v1/committee-requests", json=payload, headers=actors["admin_headers"]
    )
    assert response.status_code == 400


async def test_duplicate_member_rejected(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    payload = _valid_payload(actors["member_id"])
    payload["proposed_member_ids"] = [actors["member_id"], actors["member_id"]]
    response = await client.post(
        "/api/v1/committee-requests", json=payload, headers=actors["admin_headers"]
    )
    assert response.status_code == 422


async def test_empty_members_list_rejected(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    payload = _valid_payload(actors["member_id"])
    payload["proposed_member_ids"] = []
    response = await client.post(
        "/api/v1/committee-requests", json=payload, headers=actors["admin_headers"]
    )
    assert response.status_code == 422


async def test_cannot_escalate_draft(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    create = await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"]),
        headers=actors["admin_headers"],
    )
    request_id = create.json()["request_id"]

    escalate = await client.post(
        f"/api/v1/committee-requests/{request_id}/escalate", headers=actors["office_headers"]
    )
    assert escalate.status_code == 409


async def test_create_request_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/committee-requests", json=_valid_payload(str(uuid.uuid4()))
    )
    assert response.status_code == 401
