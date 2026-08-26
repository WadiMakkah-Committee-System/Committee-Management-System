"""اختبارات نظام الأدوار والصلاحيات الديناميكي (Roles & Permissions)."""

from httpx import AsyncClient

from app.db.session import AsyncSessionLocal
from app.models.role import Role


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
        "job_titles",
    }


async def test_permissions_catalog_marks_enforced_categories(
    client: AsyncClient, auth_headers
) -> None:
    """
    departments/users/committees/job_titles عليها endpoints تتحقق منها
    فعليًا حاليًا (job_titles أُضيفت بعد Phase 7 — المسميات الوظيفية) —
    الحقل is_enforced يسمح للواجهة بعرض بقية الأقسام كـ "قريبًا" بدون
    تكرار هذه القائمة يدويًا في الفرونت.
    """
    response = await client.get("/api/v1/permissions", headers=auth_headers)
    body = response.json()
    enforced = {p["category"] for p in body if p["is_enforced"]}
    not_enforced = {p["category"] for p in body if not p["is_enforced"]}
    assert enforced == {"departments", "users", "committees", "job_titles"}
    assert "meetings" in not_enforced and "tasks" in not_enforced


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
    assert super_admin["permission_count"] == 79


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


async def test_create_role_without_permissions_rejected(
    client: AsyncClient, auth_headers
) -> None:
    """لا يمكن إنشاء دور بدون تحديد صلاحية واحدة على الأقل."""
    response = await client.post(
        "/api/v1/roles",
        json={"name": "دور بلا صلاحيات", "permission_codes": []},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "صلاحية واحدة" in response.json()["detail"]


async def test_create_role_with_omitted_permissions_rejected(
    client: AsyncClient, auth_headers
) -> None:
    """حتى لو لم يُرسل الحقل أصلًا (يعتمد على القيمة الافتراضية []) يُرفض بنفس الطريقة."""
    response = await client.post(
        "/api/v1/roles",
        json={"name": "دور بلا حقل صلاحيات"},
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_update_role_cannot_clear_all_permissions(
    client: AsyncClient, auth_headers
) -> None:
    """لا يمكن تعديل دور موجود بحيث تصبح صلاحياته صفرًا."""
    role_response = await client.post(
        "/api/v1/roles",
        json={"name": "دور قابل للتعديل", "permission_codes": ["departments.view"]},
        headers=auth_headers,
    )
    role_id = role_response.json()["role_id"]

    response = await client.patch(
        f"/api/v1/roles/{role_id}",
        json={"permission_codes": []},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "صلاحية واحدة" in response.json()["detail"]


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


async def test_can_delete_system_role_without_users(client: AsyncClient, auth_headers) -> None:
    """
    قرار عمل موثّق: فُكّت الحماية بالكامل عن الأدوار النظامية الخمسة —
    لم يعد is_system يمنع الحذف. نستخدم دورًا مؤقتًا مُعلَّمًا يدويًا
    is_system=true (وليس أحد الأدوار الخمسة الحقيقية المشتركة مع بقية
    ملفات الاختبار عبر roles_by_name) تجنبًا لإفساد تلك البيانات
    للاختبارات الأخرى — الحماية الوحيدة المتبقية هي عدم وجود مستخدمين
    مرتبطين بالدور.
    """
    async with AsyncSessionLocal() as db:
        temp_role = Role(name="دور نظامي مؤقت للاختبار", is_system=True, is_super_admin=False)
        db.add(temp_role)
        await db.commit()
        await db.refresh(temp_role)
        temp_role_id = str(temp_role.role_id)

    response = await client.delete(f"/api/v1/roles/{temp_role_id}", headers=auth_headers)
    assert response.status_code == 204


async def test_cannot_delete_role_with_active_users(
    client: AsyncClient, auth_headers
) -> None:
    role_response = await client.post(
        "/api/v1/roles",
        json={"name": "دور مستخدَم", "permission_codes": ["departments.view"]},
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
