"""اختبارات إدارة المستخدمين — CRUD + RBAC + Soft Delete + إيقاف/تفعيل."""

from httpx import AsyncClient

from app.models.user import User


async def _create_department(
    client: AsyncClient,
    auth_headers,
    super_admin_user: User,
    name: str = "إدارة اختبار",
    code: str = "TST",
) -> str:
    response = await client.post(
        "/api/v1/departments",
        json={
            "name": name,
            "code": code,
            "description": None,
            "manager_user_id": str(super_admin_user.user_id),
        },
        headers=auth_headers,
    )
    return response.json()["dep_id"]


async def test_create_user_success(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    dep_id = await _create_department(client, auth_headers, super_admin_user)

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
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    """
    GET /users/me متاح لأي مستخدم مسجّل دخول (بلا قيد دور)، ويرجع بيانات
    إدارته كاملة (اسم + وصف) مضمَّنة مباشرة — بدل الحاجة لطلب منفصل لصفحة
    الإدارات (المقصورة على super_admin أصلًا).
    """
    dep_id = await _create_department(client, auth_headers, super_admin_user, "إدارة الأعضاء", "MEM")

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


# ==========================================================================
# مراجعة لاما 2026-08-30: الدور اختياري + فصل الصلاحية عن نطاق الوصول
# ==========================================================================


async def test_create_user_without_role_succeeds_and_can_login(
    client: AsyncClient, auth_headers
) -> None:
    """
    "لا تجعل حقل الدور إجباريًا عند إضافة مستخدم" — role_id غير مُرسَل
    إطلاقًا (وليس فقط null) يُنشئ المستخدم بنجاح، ويقدر يسجّل دخول، ويصل
    لـ /users/me فقط (بلا أي صلاحيات إضافية، role=None، permissions=[]).
    """
    create = await client.post(
        "/api/v1/users",
        json={
            "first_name": "بلا",
            "middle_name": "دور",
            "last_name": "بعد",
            "username": "no_role_user",
            "email": "no_role@example.com",
            "password": "StrongPass1",
            # role_id غير مُرسَل عمدًا — يجب أن يكون اختياريًا بالكامل
        },
        headers=auth_headers,
    )
    assert create.status_code == 201, create.text
    assert create.json()["role"] is None

    login = await client.post(
        "/api/v1/auth/login", json={"username": "no_role_user", "password": "StrongPass1"}
    )
    assert login.status_code == 200, login.text
    no_role_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    me = await client.get("/api/v1/users/me", headers=no_role_headers)
    assert me.status_code == 200
    assert me.json()["role"] is None
    assert me.json()["permissions"] == []

    # بلا أي صلاحية users.* — يُرفض فورًا (403)، وليس انهيارًا (500).
    forbidden = await client.get("/api/v1/users", headers=no_role_headers)
    assert forbidden.status_code == 403


async def _create_custom_role(
    client: AsyncClient,
    auth_headers: dict[str, str],
    *,
    name: str,
    permission_codes: list[str],
    permission_scopes: dict[str, str],
) -> str:
    response = await client.post(
        "/api/v1/roles",
        json={
            "name": name,
            "permission_codes": permission_codes,
            "permission_scopes": permission_scopes,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["role_id"]


async def _create_user_and_login(
    client: AsyncClient,
    auth_headers: dict[str, str],
    *,
    username: str,
    role_id: str,
    dep_id: str | None = None,
) -> dict[str, str]:
    create = await client.post(
        "/api/v1/users",
        json={
            "first_name": "أ",
            "middle_name": "ب",
            "last_name": "ج",
            "username": username,
            "email": f"{username}@example.com",
            "password": "StrongPass1",
            "role_id": role_id,
            "dep_id": dep_id,
        },
        headers=auth_headers,
    )
    assert create.status_code == 201, create.text
    login = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "StrongPass1"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_users_view_own_scope_sees_only_self(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    مراجعة لاما 2026-08-30: "لا تجعل نفس صلاحية العرض تعني تلقائيًا الوصول
    إلى جميع مستخدمي النظام" — نطاق own على users.view يقصر GET /users
    على المستخدم نفسه فقط، ويمنع GET /users/{id} لأي مستخدم آخر (403).
    """
    role_id = await _create_custom_role(
        client,
        auth_headers,
        name="viewer_own",
        permission_codes=["users.view"],
        permission_scopes={"users.view": "own"},
    )
    viewer_headers = await _create_user_and_login(
        client, auth_headers, username="own_scope_viewer", role_id=role_id
    )
    other_id = await _create_second_super_admin(
        client, auth_headers, roles_by_name, username="own_scope_other"
    )

    listed = await client.get("/api/v1/users", headers=viewer_headers)
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert body[0]["username"] == "own_scope_viewer"

    forbidden = await client.get(f"/api/v1/users/{other_id}", headers=viewer_headers)
    assert forbidden.status_code == 403

    me = await client.get("/api/v1/users/me", headers=viewer_headers)
    allowed = await client.get(f"/api/v1/users/{me.json()['user_id']}", headers=viewer_headers)
    assert allowed.status_code == 200


async def test_users_view_department_scope_limits_to_same_department(
    client: AsyncClient, auth_headers, super_admin_user: User
) -> None:
    """نطاق department على users.view يقصر النتيجة على مستخدمي إدارة actor نفسها فقط."""
    dep_a = await _create_department(client, auth_headers, super_admin_user, "إدارة أ", "DPA")
    dep_b = await _create_department(client, auth_headers, super_admin_user, "إدارة ب", "DPB")

    role_id = await _create_custom_role(
        client,
        auth_headers,
        name="viewer_department",
        permission_codes=["users.view"],
        permission_scopes={"users.view": "department"},
    )
    viewer_headers = await _create_user_and_login(
        client, auth_headers, username="dep_scope_viewer", role_id=role_id, dep_id=dep_a
    )

    await client.post(
        "/api/v1/users",
        json={
            "first_name": "ز",
            "middle_name": "ح",
            "last_name": "ط",
            "username": "dep_a_colleague",
            "email": "dep_a_colleague@example.com",
            "password": "StrongPass1",
            "role_id": role_id,
            "dep_id": dep_a,
        },
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/users",
        json={
            "first_name": "ي",
            "middle_name": "ك",
            "last_name": "ل",
            "username": "dep_b_stranger",
            "email": "dep_b_stranger@example.com",
            "password": "StrongPass1",
            "role_id": role_id,
            "dep_id": dep_b,
        },
        headers=auth_headers,
    )

    listed = await client.get("/api/v1/users", headers=viewer_headers)
    assert listed.status_code == 200
    usernames = {u["username"] for u in listed.json()}
    assert usernames == {"dep_scope_viewer", "dep_a_colleague"}


async def test_users_view_department_scope_excludes_ceo_and_super_admin(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    """
    مراجعة لاما 2026-08-31 (بلاغ خطأ): Admin بنطاق department على
    users.view ما يقدر يشوف الرئيس التنفيذي ولا Super Admin ولا أي
    مستخدم من إدارة ثانية — حتى لو هم بلا إدارة مسجَّلة (dep_id=None)،
    القائمة تبقى مقصورة فعليًا على إدارته هو فقط.
    """
    dep_finance = await _create_department(
        client, auth_headers, super_admin_user, "الإدارة المالية اختبار", "FINX"
    )
    dep_bank = await _create_department(
        client, auth_headers, super_admin_user, "إدارة البنك اختبار", "BNKX"
    )

    role_id = await _create_custom_role(
        client,
        auth_headers,
        name="ادمن_مالية_اختبار",
        permission_codes=["users.view"],
        permission_scopes={"users.view": "department"},
    )
    finance_admin_headers = await _create_user_and_login(
        client, auth_headers, username="finance_admin_x", role_id=role_id, dep_id=dep_finance
    )
    await client.post(
        "/api/v1/users",
        json={
            "first_name": "س",
            "middle_name": "ص",
            "last_name": "ض",
            "username": "bank_user_x",
            "email": "bank_user_x@example.com",
            "password": "StrongPass1",
            "role_id": role_id,
            "dep_id": dep_bank,
        },
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/users",
        json={
            "first_name": "ط",
            "middle_name": "ظ",
            "last_name": "ع",
            "username": "ceo_user_x",
            "email": "ceo_user_x@example.com",
            "password": "StrongPass1",
            "role_id": roles_by_name["executive_president"],
            "dep_id": None,
        },
        headers=auth_headers,
    )

    listed = await client.get("/api/v1/users", headers=finance_admin_headers)
    assert listed.status_code == 200
    usernames = {u["username"] for u in listed.json()}
    assert usernames == {"finance_admin_x"}
    assert "bank_user_x" not in usernames
    assert "ceo_user_x" not in usernames
    assert super_admin_user.username not in usernames


async def test_me_returns_permission_scopes_matching_role(
    client: AsyncClient, auth_headers
) -> None:
    """
    مراجعة لاما 2026-08-31 (بلاغ خطأ): /users/me كان يرجع permissions
    كقائمة أكواد فقط، بلا أي نطاق — فكانت الواجهة الأمامية تُظهر إجراءات
    مقيَّدة بنطاق (مثال: "إرجاع لمقدّم الطلب" بطلبات تشكيل اللجان) لمن
    يملك الصلاحية بنطاق own فقط (كمقدّم الطلب نفسه)، لأنها لا تقدر تفرّق
    بين النطاقات. الآن يجب أن يرجع permission_scopes مطابقًا تمامًا لما
    هو مسجَّل بدور المستخدم.
    """
    role_id = await _create_custom_role(
        client,
        auth_headers,
        name="دور_نطاقات_اختبار",
        permission_codes=["committees.request.create", "committees.request.update"],
        permission_scopes={
            "committees.request.create": "own",
            "committees.request.update": "own",
        },
    )
    member_headers = await _create_user_and_login(
        client, auth_headers, username="scopes_probe_x", role_id=role_id
    )

    me = await client.get("/api/v1/users/me", headers=member_headers)
    assert me.status_code == 200
    body = me.json()
    assert body["permission_scopes"]["committees.request.create"] == "own"
    assert body["permission_scopes"]["committees.request.update"] == "own"
    assert set(body["permissions"]) == {
        "committees.request.create",
        "committees.request.update",
    }
