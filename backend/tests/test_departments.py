"""اختبارات إدارة الإدارات (Departments) — CRUD + RBAC + Soft Delete."""

from httpx import AsyncClient


async def test_create_department_success(client: AsyncClient, auth_headers) -> None:
    response = await client.post(
        "/api/v1/departments",
        json={"name": "إدارة تقنية المعلومات", "description": "الإدارة المسؤولة عن الأنظمة"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "إدارة تقنية المعلومات"
    assert "dep_id" in body


async def test_create_department_duplicate_name_rejected(client: AsyncClient, auth_headers) -> None:
    payload = {"name": "إدارة الموارد البشرية", "description": None}
    first = await client.post("/api/v1/departments", json=payload, headers=auth_headers)
    assert first.status_code == 201

    second = await client.post("/api/v1/departments", json=payload, headers=auth_headers)
    assert second.status_code == 400


async def test_create_department_requires_super_admin(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/departments", json={"name": "إدارة بدون صلاحية", "description": None}
    )
    # بدون توكن أصلًا → 401 (لم يوصل حتى لفحص RBAC)
    assert response.status_code == 401


async def test_soft_delete_department_hides_it_from_list(
    client: AsyncClient, auth_headers
) -> None:
    create = await client.post(
        "/api/v1/departments",
        json={"name": "إدارة مؤقتة للحذف", "description": None},
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


async def test_soft_deleted_department_name_can_be_reused(
    client: AsyncClient, auth_headers
) -> None:
    payload = {"name": "إدارة قابلة لإعادة الاستخدام", "description": None}
    create = await client.post("/api/v1/departments", json=payload, headers=auth_headers)
    dep_id = create.json()["dep_id"]

    await client.delete(f"/api/v1/departments/{dep_id}", headers=auth_headers)

    recreate = await client.post("/api/v1/departments", json=payload, headers=auth_headers)
    assert recreate.status_code == 201


async def _create_department(client: AsyncClient, auth_headers, name: str) -> str:
    response = await client.post(
        "/api/v1/departments", json={"name": name, "description": None}, headers=auth_headers
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
    client: AsyncClient, auth_headers
) -> None:
    await _create_department(client, auth_headers, "إدارة أولى")
    await _create_department(client, auth_headers, "إدارة ثانية")

    listing = await client.get("/api/v1/departments", headers=auth_headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 2


async def test_non_super_admin_cannot_list_departments(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    قرار موثّق: endpoint الإدارات بالكامل مقصور على super_admin. بقية
    الأدوار يشوفون إدارتهم عبر GET /users/me بدل هذا المسار.
    """
    dep_id = await _create_department(client, auth_headers, "إدارة الموظف")
    member_headers = await _create_admin_in_department(
        client, auth_headers, roles_by_name, username="member_dep_forbidden_list", dep_id=dep_id
    )

    listing = await client.get("/api/v1/departments", headers=member_headers)
    assert listing.status_code == 403


async def test_non_super_admin_cannot_get_department_by_id(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    dep_id = await _create_department(client, auth_headers, "إدارة الموظف الثانية")
    member_headers = await _create_admin_in_department(
        client, auth_headers, roles_by_name, username="member_dep_forbidden_get", dep_id=dep_id
    )

    response = await client.get(f"/api/v1/departments/{dep_id}", headers=member_headers)
    assert response.status_code == 403
