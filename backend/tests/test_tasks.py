"""
اختبارات وحدة "إدارة المهام".

بنفس أسلوب test_decisions.py بالضبط: تُنشأ لجنة معتمدة من الصفر بكل
اختبار، وتُمنح صلاحيات tasks.* لدوري "رئيس اللجنة"/"عضو اللجنة" صراحةً
(بلا هذا المنح، لا أحد غير سوبر أدمن يقدر يتعامل مع المهام فعليًا — نفس
القيد المطبَّق بوحدة القرارات، راجعي رأس task_service.py).
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
    member_count: int = 2,
) -> dict:
    """لجنة معتمدة فعليًا برئيس وعدد member_count من الأعضاء الإضافيين، وصلاحيات tasks.* ممنوحة."""
    admin_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username=f"tt_admin_{suffix}", role_name="admin"
    )
    office_headers, _ = await _create_user_with_role(
        client,
        auth_headers,
        roles_by_name,
        username=f"tt_office_{suffix}",
        role_name="executive_office_manager",
    )
    ceo_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username=f"tt_ceo_{suffix}", role_name="executive_president"
    )
    chair_headers, chair_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username=f"tt_chair_{suffix}", role_name="admin"
    )

    member_ids = []
    member_headers_list = []
    for i in range(member_count):
        headers, uid = await _create_user_with_role(
            client, auth_headers, roles_by_name, username=f"tt_member_{suffix}_{i}", role_name="admin"
        )
        member_ids.append(uid)
        member_headers_list.append(headers)

    outsider_headers, outsider_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username=f"tt_outsider_{suffix}", role_name="admin"
    )

    create = await client.post(
        "/api/v1/committee-requests",
        json={
            "committee_name": f"لجنة المهام التجريبية {suffix}",
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
            "tasks.create",
            "tasks.view",
            "tasks.view_details",
            "tasks.update",
            "tasks.delete",
            "tasks.status.update",
        ],
        slug="chair",
    )
    await _grant_committee_role_permissions(
        ["tasks.view", "tasks.view_details", "tasks.status.update"], slug="member"
    )

    return {
        "committee_id": committee_id,
        "chair_headers": chair_headers,
        "chair_id": chair_id,
        "member_ids": member_ids,
        "member_headers_list": member_headers_list,
        "outsider_headers": outsider_headers,
        "outsider_id": outsider_id,
    }


async def _create_task(client: AsyncClient, ctx: dict, *, assignee_id: str, title: str = "مهمة تجريبية"):
    return await client.post(
        "/api/v1/tasks",
        json={
            "committee_id": ctx["committee_id"],
            "title": title,
            "start_date": "2026-09-10",
            "end_date": "2026-10-10",
            "assignee_user_id": assignee_id,
        },
        headers=ctx["chair_headers"],
    )


async def test_chair_can_create_task_and_view_it(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="createview")

    create = await _create_task(client, ctx, assignee_id=ctx["member_ids"][0])
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["status"] == "todo"
    assert body["assignee"]["user_id"] == ctx["member_ids"][0]

    get_resp = await client.get(f"/api/v1/tasks/{body['task_id']}", headers=ctx["chair_headers"])
    assert get_resp.status_code == 200, get_resp.text


async def test_member_cannot_create_task(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="noncreate")

    response = await client.post(
        "/api/v1/tasks",
        json={
            "committee_id": ctx["committee_id"],
            "title": "محاولة غير مصرح بها",
            "start_date": "2026-09-10",
            "end_date": "2026-10-10",
            "assignee_user_id": ctx["member_ids"][0],
        },
        headers=ctx["member_headers_list"][0],
    )
    assert response.status_code == 403, response.text


async def test_cannot_assign_task_to_non_committee_member(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="badassignee")

    create = await _create_task(client, ctx, assignee_id=ctx["outsider_id"])
    assert create.status_code == 400, create.text


async def test_end_date_before_start_date_rejected(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="baddates")

    response = await client.post(
        "/api/v1/tasks",
        json={
            "committee_id": ctx["committee_id"],
            "title": "تواريخ خاطئة",
            "start_date": "2026-10-10",
            "end_date": "2026-09-10",
            "assignee_user_id": ctx["chair_id"],
        },
        headers=ctx["chair_headers"],
    )
    assert response.status_code == 422, response.text


async def test_member_can_view_only_own_assigned_task(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="ownview")

    create = await _create_task(client, ctx, assignee_id=ctx["member_ids"][0])
    task_id = create.json()["task_id"]

    own_view = await client.get(f"/api/v1/tasks/{task_id}", headers=ctx["member_headers_list"][0])
    assert own_view.status_code == 200, own_view.text

    other_view = await client.get(f"/api/v1/tasks/{task_id}", headers=ctx["member_headers_list"][1])
    assert other_view.status_code == 403, other_view.text


async def test_list_tasks_scoped_by_role(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="listscope")

    t1 = await _create_task(client, ctx, assignee_id=ctx["member_ids"][0], title="مهمة العضو الأول")
    t2 = await _create_task(client, ctx, assignee_id=ctx["member_ids"][1], title="مهمة العضو الثاني")
    assert t1.status_code == 201 and t2.status_code == 201

    chair_list = await client.get("/api/v1/tasks", headers=ctx["chair_headers"])
    assert chair_list.status_code == 200, chair_list.text
    chair_ids = {t["task_id"] for t in chair_list.json()}
    assert {t1.json()["task_id"], t2.json()["task_id"]} <= chair_ids

    member0_list = await client.get("/api/v1/tasks", headers=ctx["member_headers_list"][0])
    member0_ids = {t["task_id"] for t in member0_list.json()}
    assert t1.json()["task_id"] in member0_ids
    assert t2.json()["task_id"] not in member0_ids


async def test_member_can_update_status_of_own_task_only(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="statusown")

    task = await _create_task(client, ctx, assignee_id=ctx["member_ids"][0])
    task_id = task.json()["task_id"]

    own_update = await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers=ctx["member_headers_list"][0],
    )
    assert own_update.status_code == 200, own_update.text
    assert own_update.json()["status"] == "in_progress"

    other_update = await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "on_hold"},
        headers=ctx["member_headers_list"][1],
    )
    assert other_update.status_code == 403, other_update.text


async def test_chair_can_update_status_of_any_task_in_committee(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="chairstatus")

    task = await _create_task(client, ctx, assignee_id=ctx["member_ids"][0])
    task_id = task.json()["task_id"]

    update = await client.post(
        f"/api/v1/tasks/{task_id}/status", json={"status": "completed"}, headers=ctx["chair_headers"]
    )
    assert update.status_code == 200, update.text
    assert update.json()["status"] == "completed"


async def test_cannot_modify_completed_task(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="lockedtask")

    task = await _create_task(client, ctx, assignee_id=ctx["member_ids"][0])
    task_id = task.json()["task_id"]

    complete = await client.post(
        f"/api/v1/tasks/{task_id}/status", json={"status": "completed"}, headers=ctx["chair_headers"]
    )
    assert complete.status_code == 200, complete.text

    update_attempt = await client.patch(
        f"/api/v1/tasks/{task_id}", json={"title": "تعديل ممنوع"}, headers=ctx["chair_headers"]
    )
    assert update_attempt.status_code == 409, update_attempt.text

    delete_attempt = await client.delete(f"/api/v1/tasks/{task_id}", headers=ctx["chair_headers"])
    assert delete_attempt.status_code == 409, delete_attempt.text

    reassign_attempt = await client.post(
        f"/api/v1/tasks/{task_id}/reassign",
        json={"assignee_user_id": ctx["member_ids"][1]},
        headers=ctx["chair_headers"],
    )
    assert reassign_attempt.status_code == 409, reassign_attempt.text

    status_attempt = await client.post(
        f"/api/v1/tasks/{task_id}/status", json={"status": "todo"}, headers=ctx["chair_headers"]
    )
    assert status_attempt.status_code == 409, status_attempt.text


async def test_reassign_records_task_trail(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="trail")

    task = await _create_task(client, ctx, assignee_id=ctx["member_ids"][0])
    task_id = task.json()["task_id"]
    assert len(task.json()["assignment_history"]) == 1
    assert task.json()["assignment_history"][0]["from_user"] is None

    reassign = await client.post(
        f"/api/v1/tasks/{task_id}/reassign",
        json={"assignee_user_id": ctx["member_ids"][1]},
        headers=ctx["chair_headers"],
    )
    assert reassign.status_code == 200, reassign.text
    body = reassign.json()
    assert body["assignee"]["user_id"] == ctx["member_ids"][1]
    assert len(body["assignment_history"]) == 2
    last_entry = body["assignment_history"][-1]
    assert last_entry["from_user"]["user_id"] == ctx["member_ids"][0]
    assert last_entry["to_user"]["user_id"] == ctx["member_ids"][1]


async def test_member_cannot_reassign_task(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="memberreassign")

    task = await _create_task(client, ctx, assignee_id=ctx["member_ids"][0])
    task_id = task.json()["task_id"]

    reassign = await client.post(
        f"/api/v1/tasks/{task_id}/reassign",
        json={"assignee_user_id": ctx["member_ids"][1]},
        headers=ctx["member_headers_list"][0],
    )
    assert reassign.status_code == 403, reassign.text
