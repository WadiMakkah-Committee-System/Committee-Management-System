"""اختبارات سجل النشاط (Activity Log) — GET /audit-logs."""

from httpx import AsyncClient


async def test_audit_log_records_department_creation(client: AsyncClient, auth_headers) -> None:
    await client.post(
        "/api/v1/departments", json={"name": "إدارة السجل", "description": None}, headers=auth_headers
    )

    response = await client.get("/api/v1/audit-logs?target_type=department", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    entry = body["items"][0]
    assert entry["action_type"] == "create"
    assert entry["target_type"] == "department"
    assert entry["actor_name"] is not None


async def test_audit_log_requires_super_admin(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    await client.post(
        "/api/v1/users",
        json={
            "first_name": "ماجد",
            "middle_name": "علي",
            "last_name": "الشهري",
            "username": "majed_audit",
            "email": "majed@example.com",
            "password": "StrongPass1",
            "role_id": roles_by_name["admin"],
            "dep_id": None,
        },
        headers=auth_headers,
    )
    login = await client.post(
        "/api/v1/auth/login", json={"username": "majed_audit", "password": "StrongPass1"}
    )
    admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = await client.get("/api/v1/audit-logs", headers=admin_headers)
    assert response.status_code == 403
