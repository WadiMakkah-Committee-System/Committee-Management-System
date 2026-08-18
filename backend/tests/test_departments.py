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
