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
        "chair_user_id": member_id,
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


async def test_office_returns_request_to_admin_who_edits_and_resubmits(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """قرار موثّق 2026-08-24: المكتب يرجع الطلب للادمن بسبب، الادمن يعدّل ويعيد الإرسال."""
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    create = await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"]),
        headers=actors["admin_headers"],
    )
    request_id = create.json()["request_id"]
    await client.post(f"/api/v1/committee-requests/{request_id}/submit", headers=actors["admin_headers"])

    missing_reason = await client.post(
        f"/api/v1/committee-requests/{request_id}/return-to-admin",
        json={},
        headers=actors["office_headers"],
    )
    assert missing_reason.status_code == 422

    ret = await client.post(
        f"/api/v1/committee-requests/{request_id}/return-to-admin",
        json={"return_reason": "بيانات اللجنة ناقصة"},
        headers=actors["office_headers"],
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["status"] == "returned"
    assert ret.json()["return_reason"] == "بيانات اللجنة ناقصة"

    # الادمن يقدر يعدّل الآن (returned مثل draft)
    edit = await client.patch(
        f"/api/v1/committee-requests/{request_id}",
        json={"committee_name": "لجنة الجودة (بعد التعديل)"},
        headers=actors["admin_headers"],
    )
    assert edit.status_code == 200, edit.text

    # المكتب التنفيذي ما يقدر يعدّل وهي returned (ملك الادمن فقط بهذه الحالة)
    office_edit_returned = await client.patch(
        f"/api/v1/committee-requests/{request_id}",
        json={"statement": "محاولة من المكتب"},
        headers=actors["office_headers"],
    )
    assert office_edit_returned.status_code == 403

    resubmit = await client.post(
        f"/api/v1/committee-requests/{request_id}/submit", headers=actors["admin_headers"]
    )
    assert resubmit.status_code == 200, resubmit.text
    assert resubmit.json()["status"] == "submitted"
    assert resubmit.json()["return_reason"] is None  # السبب يُمسح بعد إعادة الإرسال


async def test_ceo_returns_request_to_office_who_edits_and_escalates_again(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """قرار موثّق 2026-08-24: الرئيس التنفيذي يرجع الطلب للمكتب (غير نهائي)، يعدّل المكتب ويرفعه ثانية."""
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    create = await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"]),
        headers=actors["admin_headers"],
    )
    request_id = create.json()["request_id"]
    await client.post(f"/api/v1/committee-requests/{request_id}/submit", headers=actors["admin_headers"])
    await client.post(f"/api/v1/committee-requests/{request_id}/escalate", headers=actors["office_headers"])

    # لا أحد يعدّل وهي pending_approval — ولا حتى المكتب التنفيذي
    locked_edit = await client.patch(
        f"/api/v1/committee-requests/{request_id}",
        json={"statement": "محاولة تعديل وهي بانتظار الاعتماد"},
        headers=actors["office_headers"],
    )
    assert locked_edit.status_code == 409

    ret = await client.post(
        f"/api/v1/committee-requests/{request_id}/return-to-office",
        json={"return_reason": "محتاج تفاصيل أكثر عن أهداف اللجنة"},
        headers=actors["ceo_headers"],
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["status"] == "under_review"
    assert ret.json()["return_reason"] == "محتاج تفاصيل أكثر عن أهداف اللجنة"

    # المكتب يعدّل وهي under_review
    office_edit = await client.patch(
        f"/api/v1/committee-requests/{request_id}",
        json={"statement": "تفاصيل إضافية عن أهداف اللجنة"},
        headers=actors["office_headers"],
    )
    assert office_edit.status_code == 200, office_edit.text

    re_escalate = await client.post(
        f"/api/v1/committee-requests/{request_id}/escalate", headers=actors["office_headers"]
    )
    assert re_escalate.status_code == 200, re_escalate.text
    assert re_escalate.json()["status"] == "pending_approval"
    assert re_escalate.json()["return_reason"] is None

    approve = await client.post(
        f"/api/v1/committee-requests/{request_id}/approve", headers=actors["ceo_headers"]
    )
    assert approve.status_code == 200, approve.text


async def test_admin_cannot_return_request(
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

    forbidden = await client.post(
        f"/api/v1/committee-requests/{request_id}/return-to-admin",
        json={"return_reason": "محاولة من الادمن نفسه"},
        headers=actors["admin_headers"],
    )
    assert forbidden.status_code == 403


async def test_office_cannot_return_to_office(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """return-to-office حصرية على الرئيس التنفيذي فقط."""
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    create = await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"]),
        headers=actors["admin_headers"],
    )
    request_id = create.json()["request_id"]
    await client.post(f"/api/v1/committee-requests/{request_id}/submit", headers=actors["admin_headers"])
    await client.post(f"/api/v1/committee-requests/{request_id}/escalate", headers=actors["office_headers"])

    forbidden = await client.post(
        f"/api/v1/committee-requests/{request_id}/return-to-office",
        json={"return_reason": "محاولة من المكتب"},
        headers=actors["office_headers"],
    )
    assert forbidden.status_code == 403


async def test_get_committee_detail_returns_full_data(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    تغطية سطح القراءة committees_router (GET /committees/{id}) — لم يكن
    مغطّى سابقًا إلا ضمنيًا عبر GET /committees بقائمة الطلبات. تتأكد أن
    اللجنة المُنشأة تلقائيًا عند الاعتماد تحمل نفس بيانات الطلب المصدر
    (الاسم، البيان، التواريخ، الأعضاء) وrequest_id الصحيح.
    """
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    create = await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"], name="لجنة التدقيق"),
        headers=actors["admin_headers"],
    )
    request_id = create.json()["request_id"]
    await client.post(f"/api/v1/committee-requests/{request_id}/submit", headers=actors["admin_headers"])
    await client.post(f"/api/v1/committee-requests/{request_id}/escalate", headers=actors["office_headers"])
    approve = await client.post(
        f"/api/v1/committee-requests/{request_id}/approve", headers=actors["ceo_headers"]
    )
    assert approve.status_code == 200, approve.text

    committees = await client.get("/api/v1/committees", headers=actors["admin_headers"])
    committee_id = next(
        c["committee_id"] for c in committees.json() if c["source_request_id"] == request_id
    )

    detail = await client.get(f"/api/v1/committees/{committee_id}", headers=actors["admin_headers"])
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["name"] == "لجنة التدقيق"
    assert body["source_request_id"] == request_id
    assert [m["user_id"] for m in body["members"]] == [actors["member_id"]]

    not_found = await client.get(
        f"/api/v1/committees/{uuid.uuid4()}", headers=actors["admin_headers"]
    )
    assert not_found.status_code == 404


async def test_view_committees_requires_view_authorized_permission(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    committees.view_authorized مقصورة على admin (وsuper_admin) حسب
    permissions.xlsx — المكتب التنفيذي والرئيس التنفيذي لا يملكانها
    (لا يظهر لهما True بعمود "عرض اللجان المصرح بها لكل عضو"، وهو أصلًا
    مرتبط ببند BRS المستقبلي لعضوية/مناصب اللجان الفعلية، خارج نطاق Phase
    2). راجعي project_memory: phase2-committee-formation-requests.md.
    """
    actors = await _setup_actors(client, auth_headers, roles_by_name)

    forbidden_office = await client.get("/api/v1/committees", headers=actors["office_headers"])
    assert forbidden_office.status_code == 403

    forbidden_ceo = await client.get("/api/v1/committees", headers=actors["ceo_headers"])
    assert forbidden_ceo.status_code == 403

    allowed_admin = await client.get("/api/v1/committees", headers=actors["admin_headers"])
    assert allowed_admin.status_code == 200


async def _create_role_and_login(
    client: AsyncClient,
    auth_headers: dict[str, str],
    *,
    username: str,
    permission_codes: list[str],
    permission_scopes: dict[str, str],
) -> tuple[dict[str, str], str]:
    role = await client.post(
        "/api/v1/roles",
        json={
            "name": f"role_{username}",
            "permission_codes": permission_codes,
            "permission_scopes": permission_scopes,
        },
        headers=auth_headers,
    )
    assert role.status_code == 201, role.text
    create = await client.post(
        "/api/v1/users",
        json={
            "first_name": "أ",
            "middle_name": "ب",
            "last_name": "ج",
            "username": username,
            "email": f"{username}@example.com",
            "password": "StrongPass1",
            "role_id": role.json()["role_id"],
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
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, user_id


async def _approve_full_flow(
    client: AsyncClient, actors: dict, *, name: str, member_ids: list[str], chair_id: str
) -> str:
    """يُنفّذ دورة الحياة الكاملة (draft → submitted → pending_approval → approved) ويرجع committee_id."""
    payload = {
        "committee_name": name,
        "statement": "بيان اللجنة",
        "start_date": "2026-09-01",
        "end_date": "2026-12-01",
        "proposed_member_ids": member_ids,
        "chair_user_id": chair_id,
    }
    create = await client.post(
        "/api/v1/committee-requests", json=payload, headers=actors["admin_headers"]
    )
    assert create.status_code == 201, create.text
    request_id = create.json()["request_id"]
    await client.post(f"/api/v1/committee-requests/{request_id}/submit", headers=actors["admin_headers"])
    await client.post(f"/api/v1/committee-requests/{request_id}/escalate", headers=actors["office_headers"])
    approve = await client.post(
        f"/api/v1/committee-requests/{request_id}/approve", headers=actors["ceo_headers"]
    )
    assert approve.status_code == 200, approve.text
    return approve.json()["committee_id"]


async def test_committees_view_own_scope_limits_to_member_committees(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    مراجعة لاما 2026-08-30: صلاحية عرض اللجان بنطاق own يجب أن تقتصر فعليًا
    على اللجان التي المستخدم رئيسها أو عضو فيها — وليس كل اللجان المعتمدة
    (تصحيح الاسم المُضلِّل committees.view_authorized السابق، وتفعيل الفلتر
    الفعلي بطبقة الخدمة committee_service.list_committees/get_committee).
    """
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    viewer_headers, viewer_id = await _create_role_and_login(
        client,
        auth_headers,
        username="committee_own_viewer",
        permission_codes=["committees.view"],
        permission_scopes={"committees.view": "own"},
    )

    my_committee_id = await _approve_full_flow(
        client,
        actors,
        name="لجنتي",
        member_ids=[actors["member_id"], viewer_id],
        chair_id=actors["member_id"],
    )
    other_committee_id = await _approve_full_flow(
        client,
        actors,
        name="لجنة غيري",
        member_ids=[actors["member_id"]],
        chair_id=actors["member_id"],
    )

    listed = await client.get("/api/v1/committees", headers=viewer_headers)
    assert listed.status_code == 200
    listed_ids = {c["committee_id"] for c in listed.json()}
    assert listed_ids == {my_committee_id}

    allowed = await client.get(f"/api/v1/committees/{my_committee_id}", headers=viewer_headers)
    assert allowed.status_code == 200

    forbidden = await client.get(f"/api/v1/committees/{other_committee_id}", headers=viewer_headers)
    assert forbidden.status_code == 403


async def test_chair_must_be_a_proposed_member_on_create(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    رئيس اللجنة المقترح (chair_user_id) يجب أن يكون أحد الأعضاء المقترحين
    فعليًا — قرار موثّق 2026-08-27 (فصل System Role عن Committee Role).
    التحقق مزدوج (Schema + طبقة الخدمة)؛ هذا الاختبار يغطي مسار الإنشاء.
    """
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    outsider_headers, outsider_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="cf_outsider", role_name="admin"
    )
    payload = _valid_payload(actors["member_id"])
    payload["chair_user_id"] = outsider_id  # ليس ضمن proposed_member_ids

    response = await client.post(
        "/api/v1/committee-requests", json=payload, headers=actors["admin_headers"]
    )
    assert response.status_code == 422, response.text


async def test_chair_must_remain_a_member_on_update(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    نفس القاعدة أعلاه، بمسار التعديل: لو مقدّم الطلب غيّر قائمة الأعضاء
    وأزال الرئيس الحالي منها دون تحديد رئيس جديد، يُرفض التعديل — رئيس
    اللجنة لا يبقى معلّقًا بلا وجود ضمن الأعضاء.
    """
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    other_headers, other_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="cf_other", role_name="admin"
    )
    create = await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"]),
        headers=actors["admin_headers"],
    )
    request_id = create.json()["request_id"]

    # يستبدل قائمة الأعضاء بعضو آخر فقط — الرئيس المحفوظ (member_id) لم
    # يعد ضمن الأعضاء الجدد، ولم يُرسَل chair_user_id جديد بنفس الطلب.
    response = await client.patch(
        f"/api/v1/committee-requests/{request_id}",
        json={"proposed_member_ids": [other_id]},
        headers=actors["admin_headers"],
    )
    assert response.status_code == 400, response.text

    # يبقى صحيحًا لو حدّدت رئيسًا جديدًا ضمن نفس طلب التعديل.
    response_ok = await client.patch(
        f"/api/v1/committee-requests/{request_id}",
        json={"proposed_member_ids": [other_id], "chair_user_id": other_id},
        headers=actors["admin_headers"],
    )
    assert response_ok.status_code == 200, response_ok.text
    assert response_ok.json()["chair_user_id"] == other_id


async def test_chair_propagates_to_approved_committee(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    رئيس الطلب يُنسَخ تلقائيًا لرئيس اللجنة المعتمدة لحظة approve_request —
    التغطية الكاملة لتدفق "من رئيس الطلب إلى رئيس اللجنة" المطلوب فصله عن
    System Role نهائيًا.
    """
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    create = await client.post(
        "/api/v1/committee-requests",
        json=_valid_payload(actors["member_id"], name="لجنة رئيس محدد"),
        headers=actors["admin_headers"],
    )
    request_id = create.json()["request_id"]
    assert create.json()["chair_user_id"] == actors["member_id"]
    assert create.json()["chair"]["user_id"] == actors["member_id"]
    # قبل الاعتماد لا توجد لجنة ناتجة بعد — لازم يكون committee_id فارغ
    # (Task #15: التنقّل الذكي من قائمة الطلبات يعتمد على هذا الحقل).
    assert create.json()["committee_id"] is None

    await client.post(f"/api/v1/committee-requests/{request_id}/submit", headers=actors["admin_headers"])
    await client.post(f"/api/v1/committee-requests/{request_id}/escalate", headers=actors["office_headers"])
    approve = await client.post(
        f"/api/v1/committee-requests/{request_id}/approve", headers=actors["ceo_headers"]
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["committee_id"] is not None

    committees = await client.get("/api/v1/committees", headers=actors["admin_headers"])
    created = next(c for c in committees.json() if c["source_request_id"] == request_id)
    assert created["chair_user_id"] == actors["member_id"]
    assert created["chair"]["user_id"] == actors["member_id"]
    # committee_id بالطلب المعاد من approve يطابق فعليًا معرّف اللجنة المُنشأة.
    assert approve.json()["committee_id"] == created["committee_id"]

    # نفس القيمة تظهر أيضًا عند إعادة جلب الطلب لاحقًا (GET منفصل)، لا فقط
    # باستجابة approve نفسها — تأكيد أن lazy="selectin" يعمل بكل مسارات القراءة.
    fetched = await client.get(f"/api/v1/committee-requests/{request_id}", headers=actors["admin_headers"])
    assert fetched.json()["committee_id"] == created["committee_id"]
