"""اختبارات إدارة المستخدمين — CRUD + RBAC + Soft Delete + إيقاف/تفعيل."""

from httpx import AsyncClient


async def _create_department(client: AsyncClient, auth_headers, name: str = "إدارة اختبار") -> str:
    response = await client.post(
        "/api/v1/departments", json={"name": name, "description": None}, headers=auth_headers
    )
    return response.json()["dep_id"]


async def test_create_user_success(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    dep_id = await _create_department(client, auth_headers)

    response = await client.post(
        "/api/v1/users",
        json={
            "first_name": "سارة",
            "middle_name": "محمد",
            "last_name": "العتيبي",
            "username": "sarah_m",
            "email": "sarah@example.com",
            "password": "StrongPass1",
            "role_id": roles_by_name["admin"],
            "dep_id": dep_id,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "sarah_m"
    assert body["must_change_password"] is True
    assert "password_hash" not in body
    assert "password" not in body


async def test_create_user_weak_password_rejected(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/users",
        json={
            "first_name": "سارة",
            "middle_name": "محمد",
            "last_name": "العتيبي",
            "username": "sarah_weak",
            "email": "sarah_weak@example.com",
            "password": "weak",  # لا يطابق سياسة كلمة المرور FR-UM-015
            "role_id": roles_by_name["admin"],
            "dep_id": None,
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_create_user_duplicate_username_rejected(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    payload = {
        "first_name": "أ",
        "middle_name": "ب",
        "last_name": "ج",
        "username": "dup_user",
        "email": "dup1@example.com",
        "password": "StrongPass1",
        "role_id": roles_by_name["admin"],
        "dep_id": None,
    }
    first = await client.post("/api/v1/users", json=payload, headers=auth_headers)
    assert first.status_code == 201

    payload["email"] = "dup2@example.com"
    second = await client.post("/api/v1/users", json=payload, headers=auth_headers)
    assert second.status_code == 400


async def test_suspend_and_reactivate_blocks_and_restores_login(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    create = await client.post(
        "/api/v1/users",
        json={
            "first_name": "خالد",
            "middle_name": "علي",
            "last_name": "الزهراني",
            "username": "khalid_z",
            "email": "khalid@example.com",
            "password": "StrongPass1",
            "role_id": roles_by_name["admin"],
            "dep_id": None,
        },
        headers=auth_headers,
    )
    user_id = create.json()["user_id"]

    suspend = await client.post(f"/api/v1/users/{user_id}/suspend", headers=auth_headers)
    assert suspend.status_code == 200
    assert suspend.json()["status"] == "suspended"

    login_while_suspended = await client.post(
        "/api/v1/auth/login", json={"username": "khalid_z", "password": "StrongPass1"}
    )
    assert login_while_suspended.status_code == 401

    reactivate = await client.post(f"/api/v1/users/{user_id}/reactivate", headers=auth_headers)
    assert reactivate.status_code == 200
    assert reactivate.json()["status"] == "active"

    login_after_reactivate = await client.post(
        "/api/v1/auth/login", json={"username": "khalid_z", "password": "StrongPass1"}
    )
    assert login_after_reactivate.status_code == 200


async def test_soft_delete_user(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    create = await client.post(
        "/api/v1/users",
        json={
            "first_name": "نورة",
            "middle_name": "سعد",
            "last_name": "القحطاني",
            "username": "noura_q",
            "email": "noura@example.com",
            "password": "StrongPass1",
            "role_id": roles_by_name["admin"],
            "dep_id": None,
        },
        headers=auth_headers,
    )
    user_id = create.json()["user_id"]

    delete = await client.delete(f"/api/v1/users/{user_id}", headers=auth_headers)
    assert delete.status_code == 204

    get_after = await client.get(f"/api/v1/users/{user_id}", headers=auth_headers)
    assert get_after.status_code == 404


async def test_non_super_admin_cannot_manage_users(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    # ننشئ مستخدم admin عادي، ثم نتحقق أنه لا يقدر يدير المستخدمين
    create = await client.post(
        "/api/v1/users",
        json={
            "first_name": "عبدالله",
            "middle_name": "فهد",
            "last_name": "الدوسري",
            "username": "abdullah_d",
            "email": "abdullah@example.com",
            "password": "StrongPass1",
            "role_id": roles_by_name["admin"],
            "dep_id": None,
        },
        headers=auth_headers,
    )
    assert create.status_code == 201

    login = await client.post(
        "/api/v1/auth/login", json={"username": "abdullah_d", "password": "StrongPass1"}
    )
    admin_token = login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    response = await client.get("/api/v1/users", headers=admin_headers)
    assert response.status_code == 403


async def test_me_returns_own_profile_with_embedded_department(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    GET /users/me متاح لأي مستخدم مسجّل دخول (بلا قيد دور)، ويرجع بيانات
    إدارته كاملة (اسم + وصف) مضمَّنة مباشرة — بدل الحاجة لطلب منفصل لصفحة
    الإدارات (المقصورة على super_admin أصلًا).
    """
    dep_id = await _create_department(client, auth_headers, "إدارة الأعضاء")

    await client.post(
        "/api/v1/users",
        json={
            "first_name": "منى",
            "middle_name": "صالح",
            "last_name": "الحربي",
            "username": "mona_h",
            "email": "mona@example.com",
            "password": "StrongPass1",
            "role_id": roles_by_name["admin"],
            "dep_id": dep_id,
        },
        headers=auth_headers,
    )
    login = await client.post(
        "/api/v1/auth/login", json={"username": "mona_h", "password": "StrongPass1"}
    )
    member_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    me = await client.get("/api/v1/users/me", headers=member_headers)
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == "mona_h"
    assert body["dep_id"] == dep_id
    assert body["department"]["dep_id"] == dep_id
    assert body["department"]["name"] == "إدارة الأعضاء"


async def test_me_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 401


async def test_me_for_super_admin_without_department_returns_null_department(
    client: AsyncClient, auth_headers
) -> None:
    """super_admin عادة بدون dep_id — يجب أن يرجع department=None بدل خطأ."""
    me = await client.get("/api/v1/users/me", headers=auth_headers)
    assert me.status_code == 200
    body = me.json()
    assert body["dep_id"] is None
    assert body["department"] is None


async def _create_second_super_admin(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], username: str = "super_admin_2"
) -> str:
    """ينشئ super_admin ثاني عبر super_admin الأول (auth_headers)، ويرجع user_id."""
    response = await client.post(
        "/api/v1/users",
        json={
            "first_name": "س",
            "middle_name": "ص",
            "last_name": "ض",
            "username": username,
            "email": f"{username}@example.com",
            "password": "StrongPass1",
            "role_id": roles_by_name["super_admin"],
            "dep_id": None,
        },
        headers=auth_headers,
    )
    return response.json()["user_id"]


async def test_cannot_delete_last_super_admin(client: AsyncClient, auth_headers) -> None:
    """
    حماية أساسية: يمنع حذف آخر super_admin نشط في النظام، وإلا يبقى النظام
    بدون أي حساب قادر على إدارته.
    """
    me = await client.get("/api/v1/users/me", headers=auth_headers)
    self_id = me.json()["user_id"]

    response = await client.delete(f"/api/v1/users/{self_id}", headers=auth_headers)
    assert response.status_code == 400
    assert "آخر" in response.json()["detail"]

    # يتأكد إنه فعلًا لسه موجود ونشط (ما انحذف)
    still_there = await client.get(f"/api/v1/users/{self_id}", headers=auth_headers)
    assert still_there.status_code == 200


async def test_can_delete_super_admin_when_another_exists(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    second_id = await _create_second_super_admin(client, auth_headers, roles_by_name)

    response = await client.delete(f"/api/v1/users/{second_id}", headers=auth_headers)
    assert response.status_code == 204


async def test_cannot_suspend_last_super_admin(client: AsyncClient, auth_headers) -> None:
    me = await client.get("/api/v1/users/me", headers=auth_headers)
    self_id = me.json()["user_id"]

    response = await client.post(f"/api/v1/users/{self_id}/suspend", headers=auth_headers)
    assert response.status_code == 400
    assert "آخر" in response.json()["detail"]


async def test_can_suspend_super_admin_when_another_exists(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    second_id = await _create_second_super_admin(
        client, auth_headers, roles_by_name, username="super_admin_3"
    )

    response = await client.post(f"/api/v1/users/{second_id}/suspend", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "suspended"


async def test_cannot_change_role_of_last_super_admin(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    me = await client.get("/api/v1/users/me", headers=auth_headers)
    self_id = me.json()["user_id"]

    response = await client.patch(
        f"/api/v1/users/{self_id}", json={"role_id": roles_by_name["admin"]}, headers=auth_headers
    )
    assert response.status_code == 400
    assert "آخر" in response.json()["detail"]
