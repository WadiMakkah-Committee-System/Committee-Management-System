"""اختبارات نظام الأدوار والصلاحيات الديناميكي (Roles & Permissions)."""

from httpx import AsyncClient


async def test_permissions_catalog_has_all_categories(client: AsyncClient, auth_headers) -> None:
    response = await client.get("/api/v1/permissions", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    categories = {p["category"] for p in body}
    assert categories == {
        "departments",
        "users",
        "committees",
        "meetings",
        "tasks",
        "decisions",
        "ai_items",
        "documents",
        "minutes",
    }


async def test_permissions_catalog_marks_enforced_categories(
    client: AsyncClient, auth_headers
) -> None:
    """
    departments/users فقط عليها endpoints تتحقق منها فعليًا حاليًا — الحقل
    is_enforced يسمح للواجهة بعرض بقية الأقسام كـ "قريبًا" بدون تكرار هذه
    القائمة يدويًا في الفرونت.
    """
    response = await client.get("/api/v1/permissions", headers=auth_headers)
    body = response.json()
    enforced = {p["category"] for p in body if p["is_enforced"]}
    not_enforced = {p["category"] for p in body if not p["is_enforced"]}
    assert enforced == {"departments", "users"}
    assert "committees" in not_enforced and "meetings" in not_enforced


async def test_system_roles_seeded(client: AsyncClient, auth_headers) -> None:
    response = await client.get("/api/v1/roles", headers=auth_headers)
    assert response.status_code == 200
    names = {r["name"] for r in response.json()}
    assert names == {
        "super_admin",
        "admin",
        "executive_president",
        "executive_office_manager",
        "executive_office_secretary",
    }
    super_admin = next(r for r in response.json() if r["name"] == "super_admin")
    assert super_admin["is_super_admin"] is True
    assert super_admin["permission_count"] == 75


async def test_create_custom_role_with_selected_permissions(
    client: AsyncClient, auth_headers
) -> None:
    response = await client.post(
        "/api/v1/roles",
        json={
            "name": "مسؤول إدارات فقط",
            "description": "دور مخصص يرى ويدير الإدارات فقط",
            "permission_codes": ["departments.view", "departments.create"],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["permission_count"] == 2
    assert body["is_system"] is False
    assert {p["code"] for p in body["permissions"]} == {"departments.view", "departments.create"}


async def test_create_role_with_unknown_permission_rejected(
    client: AsyncClient, auth_headers
) -> None:
    response = await client.post(
        "/api/v1/roles",
        json={"name": "دور غير صالح", "permission_codes": ["not.a.real.permission"]},
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_new_role_grants_matching_access(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    دور جديد يملك departments.view فقط (بدون users.*) يقدر يشوف الإدارات
    لكن لا يقدر يدير المستخدمين — يثبت أن الصلاحيات الديناميكية تُنفَّذ
    فعليًا على مستوى الـ API، وليست مجرد بيانات معروضة.
    """
    role_response = await client.post(
        "/api/v1/roles",
        json={"name": "مشاهد إدارات", "permission_codes": ["departments.view"]},
        headers=auth_headers,
    )
    role_id = role_response.json()["role_id"]

    create_user = await client.post(
        "/api/v1/users",
        json={
            "first_name": "ريم",
            "middle_name": "خالد",
            "last_name": "الغامدي",
            "username": "reem_viewer",
            "email": "reem@example.com",
            "password": "StrongPass1",
            "role_id": role_id,
            "dep_id": None,
        },
        headers=auth_headers,
    )
    assert create_user.status_code == 201

    login = await client.post(
        "/api/v1/auth/login", json={"username": "reem_viewer", "password": "StrongPass1"}
    )
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    can_view = await client.get("/api/v1/departments", headers=viewer_headers)
    assert can_view.status_code == 200

    cannot_manage_users = await client.get("/api/v1/users", headers=viewer_headers)
    assert cannot_manage_users.status_code == 403


async def test_cannot_delete_system_role(client: AsyncClient, auth_headers, roles_by_name: dict[str, str]) -> None:
    response = await client.delete(f"/api/v1/roles/{roles_by_name['admin']}", headers=auth_headers)
    assert response.status_code == 400


async def test_cannot_delete_role_with_active_users(
    client: AsyncClient, auth_headers
) -> None:
    role_response = await client.post(
        "/api/v1/roles",
        json={"name": "دور مستخدَم", "permission_codes": []},
        headers=auth_headers,
    )
    role_id = role_response.json()["role_id"]

    await client.post(
        "/api/v1/users",
        json={
            "first_name": "بدر",
            "middle_name": "سالم",
            "last_name": "القرني",
            "username": "badr_role_user",
            "email": "badr@example.com",
            "password": "StrongPass1",
            "role_id": role_id,
            "dep_id": None,
        },
        headers=auth_headers,
    )

    response = await client.delete(f"/api/v1/roles/{role_id}", headers=auth_headers)
    assert response.status_code == 400
