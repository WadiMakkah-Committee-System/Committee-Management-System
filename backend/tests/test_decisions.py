"""
اختبارات وحدة "إدارة القرارات" — القرارات المستقلة فقط (بدون AI/اجتماع).

بنفس أسلوب test_meetings.py بالضبط: تُنشأ لجنة معتمدة من الصفر بكل
اختبار، وتُمنح صلاحيات decisions.* لدوري "رئيس اللجنة"/"عضو اللجنة"
صراحةً (بلا هذا المنح، لا أحد غير سوبر أدمن يقدر يتعامل مع القرارات فعليًا
— نفس القيد المطبَّق بوحدة الاجتماعات، راجعي رأس decision_service.py).
"""

from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.role import Permission, Role, RolePermission
from app.models.user import User


async def _grant_committee_role_permissions(codes: list[str], *, slug: str) -> None:
    """Idempotent — راجعي شرح مماثل بـtest_meetings.py (roles/role_permissions لا تُنظَّف بين الاختبارات)."""
    async with AsyncSessionLocal() as db:
        role = (
            await db.execute(select(Role).where(Role.committee_role_slug == slug))
        ).scalar_one()
        perms = (await db.execute(select(Permission).where(Permission.code.in_(codes)))).scalars().all()
        assert len(perms) == len(codes), f"بعض الأكواد غير موجودة بالكتالوج: {codes}"

        existing = (
            await db.execute(
                select(RolePermission.permission_id).where(RolePermission.role_id == role.role_id)
            )
        ).scalars().all()
        existing_ids = set(existing)

        for p in perms:
            if p.permission_id in existing_ids:
                continue
            db.add(RolePermission(role_id=role.role_id, permission_id=p.permission_id, scope="all"))
        await db.commit()


async def _create_user_with_role(
    client: AsyncClient,
    auth_headers: dict[str, str],
    roles_by_name: dict[str, str],
    *,
    username: str,
    role_name: str | None,
) -> tuple[dict[str, str], str]:
    create = await client.post(
        "/api/v1/users",
        json={
            "first_name": "أ",
            "middle_name": "ب",
            "last_name": "ج",
            "username": username,
            "email": f"{username}@example.com",
            "password": "StrongPass1",
            "role_id": roles_by_name[role_name] if role_name else None,
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


async def _create_approved_committee(
    client: AsyncClient,
    auth_headers: dict[str, str],
    roles_by_name: dict[str, str],
    *,
    suffix: str,
    member_count: int = 1,
) -> dict:
    """لجنة معتمدة فعليًا برئيس وعدد member_count من الأعضاء الإضافيين، وصلاحيات decisions.* ممنوحة."""
    admin_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username=f"dt_admin_{suffix}", role_name="admin"
    )
    office_headers, _ = await _create_user_with_role(
        client,
        auth_headers,
        roles_by_name,
        username=f"dt_office_{suffix}",
        role_name="executive_office_manager",
    )
    ceo_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username=f"dt_ceo_{suffix}", role_name="executive_president"
    )
    chair_headers, chair_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username=f"dt_chair_{suffix}", role_name="admin"
    )

    member_ids = []
    member_headers_list = []
    for i in range(member_count):
        headers, uid = await _create_user_with_role(
            client, auth_headers, roles_by_name, username=f"dt_member_{suffix}_{i}", role_name="admin"
        )
        member_ids.append(uid)
        member_headers_list.append(headers)

    outsider_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username=f"dt_outsider_{suffix}", role_name="admin"
    )

    create = await client.post(
        "/api/v1/committee-requests",
        json={
            "committee_name": f"لجنة القرارات التجريبية {suffix}",
            "statement": "بيان",
            "start_date": "2026-09-01",
            "end_date": "2026-12-01",
            "proposed_member_ids": [chair_id, *member_ids],
            "chair_user_id": chair_id,
        },
        headers=admin_headers,
    )
    assert create.status_code == 201, create.text
    request_id = create.json()["request_id"]

    await client.post(f"/api/v1/committee-requests/{request_id}/submit", headers=admin_headers)
    await client.post(f"/api/v1/committee-requests/{request_id}/escalate", headers=office_headers)
    approve = await client.post(
        f"/api/v1/committee-requests/{request_id}/approve", headers=ceo_headers
    )
    assert approve.status_code == 200, approve.text
    committee_id = approve.json()["committee_id"]

    await _grant_committee_role_permissions(
        [
            "decisions.view",
            "decisions.create",
            "decisions.update",
            "decisions.delete",
            "decisions.vote.open",
            "decisions.vote.cast",
            "decisions.vote.view_result",
            "decisions.approve",
        ],
        slug="chair",
    )
    await _grant_committee_role_permissions(
        ["decisions.view", "decisions.vote.cast", "decisions.vote.view_result"], slug="member"
    )

    return {
        "committee_id": committee_id,
        "chair_headers": chair_headers,
        "chair_id": chair_id,
        "member_ids": member_ids,
        "member_headers_list": member_headers_list,
        "outsider_headers": outsider_headers,
    }


async def test_chair_can_create_final_decision_and_approve_directly(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="final")

    create = await client.post(
        "/api/v1/decisions",
        json={
            "committee_id": ctx["committee_id"],
            "title": "قرار إداري نهائي",
            "classification": "final",
            "start_date": "2026-09-10",
            "end_date": "2026-10-10",
            "assignee_ids": [ctx["chair_id"]],
        },
        headers=ctx["chair_headers"],
    )
    assert create.status_code == 201, create.text
    decision_id = create.json()["decision_id"]
    assert create.json()["status"] == "pending"

    approve = await client.post(
        f"/api/v1/decisions/{decision_id}/approve", headers=ctx["chair_headers"]
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "approved"


async def test_non_chair_cannot_create_decision(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="noncreate")

    response = await client.post(
        "/api/v1/decisions",
        json={
            "committee_id": ctx["committee_id"],
            "title": "محاولة غير مصرح بها",
            "classification": "final",
            "start_date": "2026-09-10",
            "end_date": "2026-10-10",
            "assignee_ids": [ctx["member_ids"][0]],
        },
        headers=ctx["member_headers_list"][0],
    )
    assert response.status_code == 403, response.text


async def test_cannot_edit_or_delete_decision_after_voting_opened(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="lockedit")

    create = await client.post(
        "/api/v1/decisions",
        json={
            "committee_id": ctx["committee_id"],
            "title": "قرار للتصويت",
            "classification": "voting",
            "start_date": "2026-09-10",
            "end_date": "2026-10-10",
            "assignee_ids": [ctx["chair_id"]],
        },
        headers=ctx["chair_headers"],
    )
    decision_id = create.json()["decision_id"]

    open_vote = await client.post(
        f"/api/v1/decisions/{decision_id}/open-voting", json={}, headers=ctx["chair_headers"]
    )
    assert open_vote.status_code == 200, open_vote.text
    assert open_vote.json()["status"] == "voting"

    update_attempt = await client.patch(
        f"/api/v1/decisions/{decision_id}", json={"title": "تعديل ممنوع"}, headers=ctx["chair_headers"]
    )
    assert update_attempt.status_code == 409, update_attempt.text

    delete_attempt = await client.delete(
        f"/api/v1/decisions/{decision_id}", headers=ctx["chair_headers"]
    )
    assert delete_attempt.status_code == 409, delete_attempt.text


async def test_voting_decision_approved_when_majority_reached(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(
        client, auth_headers, roles_by_name, suffix="majority", member_count=1
    )

    create = await client.post(
        "/api/v1/decisions",
        json={
            "committee_id": ctx["committee_id"],
            "title": "قرار بالأغلبية",
            "classification": "voting",
            "start_date": "2026-09-10",
            "end_date": "2026-10-10",
            "assignee_ids": [ctx["chair_id"]],
        },
        headers=ctx["chair_headers"],
    )
    decision_id = create.json()["decision_id"]

    await client.post(
        f"/api/v1/decisions/{decision_id}/open-voting", json={}, headers=ctx["chair_headers"]
    )

    # لجنة برئيس + عضو واحد = مصوّتان اثنان فقط. تصويت الرئيس أولًا.
    v1 = await client.post(
        f"/api/v1/decisions/{decision_id}/vote",
        json={"choice": "approve"},
        headers=ctx["chair_headers"],
    )
    assert v1.status_code == 200, v1.text
    assert v1.json()["status"] == "voting"  # لسا ما صوّت الجميع

    v2 = await client.post(
        f"/api/v1/decisions/{decision_id}/vote",
        json={"choice": "approve"},
        headers=ctx["member_headers_list"][0],
    )
    assert v2.status_code == 200, v2.text
    body = v2.json()
    assert body["status"] == "voting"  # مغلق للتصويت لكن بانتظار اعتماد الرئيس
    assert body["voting_closed_at"] is not None

    approve = await client.post(
        f"/api/v1/decisions/{decision_id}/approve", headers=ctx["chair_headers"]
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "approved"


async def test_voting_decision_auto_rejected_without_majority(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(
        client, auth_headers, roles_by_name, suffix="rejectmaj", member_count=1
    )

    create = await client.post(
        "/api/v1/decisions",
        json={
            "committee_id": ctx["committee_id"],
            "title": "قرار مرفوض",
            "classification": "voting",
            "start_date": "2026-09-10",
            "end_date": "2026-10-10",
            "assignee_ids": [ctx["chair_id"]],
        },
        headers=ctx["chair_headers"],
    )
    decision_id = create.json()["decision_id"]

    await client.post(
        f"/api/v1/decisions/{decision_id}/open-voting", json={}, headers=ctx["chair_headers"]
    )

    await client.post(
        f"/api/v1/decisions/{decision_id}/vote",
        json={"choice": "approve"},
        headers=ctx["chair_headers"],
    )
    reject_vote = await client.post(
        f"/api/v1/decisions/{decision_id}/vote",
        json={"choice": "reject"},
        headers=ctx["member_headers_list"][0],
    )
    assert reject_vote.status_code == 200, reject_vote.text
    body = reject_vote.json()
    # تعادل 1/1 (50%) → مرفوض تلقائيًا (التعادل يُعتبر رفضًا صراحة، FR-012)
    assert body["status"] == "rejected"
    assert body["rejection_reason"]

    approve_attempt = await client.post(
        f"/api/v1/decisions/{decision_id}/approve", headers=ctx["chair_headers"]
    )
    assert approve_attempt.status_code == 409, approve_attempt.text


async def test_outsider_cannot_view_decision(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="outsider")

    create = await client.post(
        "/api/v1/decisions",
        json={
            "committee_id": ctx["committee_id"],
            "title": "قرار خاص",
            "classification": "final",
            "start_date": "2026-09-10",
            "end_date": "2026-10-10",
            "assignee_ids": [ctx["chair_id"]],
        },
        headers=ctx["chair_headers"],
    )
    decision_id = create.json()["decision_id"]

    view = await client.get(f"/api/v1/decisions/{decision_id}", headers=ctx["outsider_headers"])
    assert view.status_code == 403


async def test_assignee_must_be_committee_member(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="badassignee")
    outsider_headers, outsider_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="dt_bad_assignee", role_name="admin"
    )

    response = await client.post(
        "/api/v1/decisions",
        json={
            "committee_id": ctx["committee_id"],
            "title": "قرار بمنفذ خاطئ",
            "classification": "final",
            "start_date": "2026-09-10",
            "end_date": "2026-10-10",
            "assignee_ids": [outsider_id],
        },
        headers=ctx["chair_headers"],
    )
    assert response.status_code == 400, response.text
