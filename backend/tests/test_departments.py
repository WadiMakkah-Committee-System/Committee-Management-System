"""اختبارات إدارة الإدارات (Departments) — CRUD + RBAC + Soft Delete."""

from httpx import AsyncClient

from app.models.user import User


async def test_create_department_success(
    client: AsyncClient, auth_headers, super_admin_user: User
) -> None:
    response = await client.post(
        "/api/v1/departments",
        json={
            "name": "إدارة تقنية المعلومات",
            "code": "IT",
            "description": "الإدارة المسؤولة عن الأنظمة",
            "manager_user_id": str(super_admin_user.user_id),
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "إدارة تقنية المعلومات"
    assert body["code"] == "IT"
    assert body["manager"]["user_id"] == str(super_admin_user.user_id)
    assert "dep_id" in body


async def test_create_department_sets_manager_as_member(
    client: AsyncClient, auth_headers, super_admin_user: User
) -> None:
    """المسؤول عن الإدارة يُضاف تلقائيًا كعضو فيها (قرار عمل موثّق)."""
    response = await client.post(
        "/api/v1/departments",
        json={
            "name": "إدارة الموارد البشرية",
            "code": "HR",
            "description": None,
            "manager_user_id": str(super_admin_user.user_id),
        },
        headers=auth_headers,
    )
    dep_id = response.json()["dep_id"]

    detail = await client.get(f"/api/v1/departments/{dep_id}", headers=auth_headers)
    member_ids = [m["user_id"] for m in detail.json()["members"]]
    assert str(super_admin_user.user_id) in member_ids


async def test_create_department_duplicate_name_rejected(
    client: AsyncClient, auth_headers, super_admin_user: User
) -> None:
    payload = {
        "name": "إدارة مكررة",
        "code": "DUP1",
        "description": None,
        "manager_user_id": str(super_admin_user.user_id),
    }
    first = await client.post("/api/v1/departments", json=payload, headers=auth_headers)
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/departments",
        json={**payload, "code": "DUP2"},
        headers=auth_headers,
    )
    assert second.status_code == 400


async def test_create_department_duplicate_code_rejected(
    client: AsyncClient, auth_headers, super_admin_user: User
) -> None:
    payload = {
        "name": "إدارة أ",
        "code": "SAME",
        "description": None,
        "manager_user_id": str(super_admin_user.user_id),
    }
    first = await client.post("/api/v1/departments", json=payload, headers=auth_headers)
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/departments",
        json={**payload, "name": "إدارة ب"},
        headers=auth_headers,
    )
    assert second.status_code == 400


async def test_create_department_unknown_manager_rejected(
    client: AsyncClient, auth_headers
) -> None:
    response = await client.post(
        "/api/v1/departments",
        json={
            "name": "إدارة بمسؤول وهمي",
            "code": "GHOST",
            "description": None,
            "manager_user_id": "00000000-0000-0000-0000-000000000000",
        },
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_create_department_requires_super_admin(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/departments",
        json={
            "name": "إدارة بدون صلاحية",
            "code": "NOPE",
            "description": None,
            "manager_user_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    # بدون توكن أصلًا → 401 (لم يوصل حتى لفحص RBAC)
    assert response.status_code == 401


async def test_soft_delete_department_hides_it_from_list(
    client: AsyncClient, auth_headers, super_admin_user: User
) -> None:
    create = await client.post(
        "/api/v1/departments",
        json={
            "name": "إدارة مؤقتة للحذف",
            "code": "TMP",
            "description": None,
            "manager_user_id": str(super_admin_user.user_id),
        },
        headers=auth_headers,
    )
    dep_id = create.json()["dep_id"]

    delete = await client.delete(f"/api/v1/departments/{dep_id}", headers=auth_headers)
    assert delete.status_code == 204

    listing = await client.get("/api/v1/departments", headers=auth_headers)
    ids = [d["dep_id"] for d in listing.json()]
    assert dep_id not in ids

    get_after_delete = await client.get(f"/api/v1/departments/{dep_id}", headers=auth_headers)
    assert get_after_delete.status_code == 404


async def test_soft_deleted_department_name_and_code_can_be_reused(
    client: AsyncClient, auth_headers, super_admin_user: User
) -> None:
    payload = {
        "name": "إدارة قابلة لإعادة الاستخدام",
        "code": "REUSE",
        "description": None,
        "manager_user_id": str(super_admin_user.user_id),
    }
    create = await client.post("/api/v1/departments", json=payload, headers=auth_headers)
    dep_id = create.json()["dep_id"]

    await client.delete(f"/api/v1/departments/{dep_id}", headers=auth_headers)

    recreate = await client.post("/api/v1/departments", json=payload, headers=auth_headers)
    assert recreate.status_code == 201


async def _create_department(
    client: AsyncClient, auth_headers, name: str, code: str, manager_user_id: str
) -> str:
    response = await client.post(
        "/api/v1/departments",
        json={"name": name, "code": code, "description": None, "manager_user_id": manager_user_id},
        headers=auth_headers,
    )
    return response.json()["dep_id"]


async def _create_admin_in_department(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], *, username: str, dep_id: str
) -> dict[str, str]:
    """ينشئ مستخدم admin تابع لإدارة معيّنة، ويسجّل دخوله، ويرجع headers جاهزة."""
    await client.post(
        "/api/v1/users",
        json={
            "first_name": "أ",
            "middle_name": "ب",
            "last_name": "ج",
            "username": username,
            "email": f"{username}@example.com",
            "password": "StrongPass1",
            "role_id": roles_by_name["admin"],
            "dep_id": dep_id,
        },
        headers=auth_headers,
    )
    login = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "StrongPass1"}
    )
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_super_admin_sees_all_departments_in_list(
    client: AsyncClient, auth_headers, super_admin_user: User
) -> None:
    manager_id = str(super_admin_user.user_id)
    await _create_department(client, auth_headers, "إدارة أولى", "ONE", manager_id)
    await _create_department(client, auth_headers, "إدارة ثانية", "TWO", manager_id)

    listing = await client.get("/api/v1/departments", headers=auth_headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 2


async def test_non_super_admin_cannot_list_departments(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    """
    قرار موثّق: endpoint الإدارات بالكامل مقصور على super_admin. بقية
    الأدوار يشوفون إدارتهم عبر GET /users/me بدل هذا المسار.
    """
    dep_id = await _create_department(
        client, auth_headers, "إدارة الموظف", "EMP1", str(super_admin_user.user_id)
    )
    member_headers = await _create_admin_in_department(
        client, auth_headers, roles_by_name, username="member_dep_forbidden_list", dep_id=dep_id
    )

    listing = await client.get("/api/v1/departments", headers=member_headers)
    assert listing.status_code == 403


async def test_non_super_admin_cannot_get_department_by_id(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    dep_id = await _create_department(
        client, auth_headers, "إدارة الموظف الثانية", "EMP2", str(super_admin_user.user_id)
    )
    member_headers = await _create_admin_in_department(
        client, auth_headers, roles_by_name, username="member_dep_forbidden_get", dep_id=dep_id
    )

    response = await client.get(f"/api/v1/departments/{dep_id}", headers=member_headers)
    assert response.status_code == 403
