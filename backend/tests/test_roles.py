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
    # مراجعة لاما 2026-09-01: فئة "committee_roles" المصطنعة أُزيلت
    # (db/migrations/0017_remove_committee_roles_category.sql) — أدوار
    # اللجان (رئيس/عضو) تختار الآن من نفس هذه الأقسام الحقيقية تمامًا،
    # فكل صلاحيات الكتالوج الحالي kind='system'.
    assert all(p["kind"] == "system" for p in body)


async def test_permissions_catalog_marks_enforced_categories(
    client: AsyncClient, auth_headers
) -> None:
    """
    departments/users/committees/job_titles عليها endpoints تتحقق منها
    فعليًا حاليًا (job_titles أُضيفت بعد Phase 7 — المسميات الوظيفية) —
    الحقل is_enforced يسمح للواجهة بعرض بقية الأقسام كـ "قريبًا" بدون
    تكرار هذه القائمة يدويًا في الفرونت.

    مراجعة لاما 2026-09-01: فئة "committee_roles" المصطنعة أُزيلت — لا حاجة
    بعد الآن لاستثناءات على مستوى الكود الفردي (schemas/role.py كان فيه
    ENFORCED_PERMISSION_CODES، أُزيل أيضًا)، لأن الإنفاذ الفعلي لعضوية
    اللجنة أصبح يعتمد على الكود الحقيقي "committees.view" الذي يغطيه أصلًا
    is_enforced على مستوى قسم "committees" كاملًا.
    """
    response = await client.get("/api/v1/permissions", headers=auth_headers)
    body = response.json()
    enforced = {p["category"] for p in body if p["is_enforced"]}
    not_enforced = {p["category"] for p in body if not p["is_enforced"]}
    assert enforced == {"departments", "users", "committees", "job_titles"}
    assert "meetings" in not_enforced and "tasks" in not_enforced


async def test_system_roles_seeded(client: AsyncClient, auth_headers) -> None:
    """
    الأدوار النظامية الخمسة (kind='user') — لا علاقة لها بـ"أدوار اللجان"
    (مراجعة لاما 2026-08-31): "رئيس اللجنة"/"عضو اللجنة" (kind='committee')
    موجودان أيضًا في نفس استجابة GET /roles (الفرونت يفلتر حسب kind لعرضهما
    بقسم منفصل — راجعي RolesPermissionsPage.tsx)، لكن هذا الاختبار يفحص
    الأدوار النظامية فقط، فيستبعدهما صراحة.

    ملاحظة: أسماء الأدوار النظامية الخمسة قابلة لإعادة التسمية من الواجهة
    (قرار موثّق 2026-08-27 — is_system لم يعد يحمي من ذلك)، فقد لا تطابق
    الأسماء الإنجليزية الأصلية إن أُعيدت تسميتها فعليًا على بيئة التشغيل —
    هذا الاختبار يتحقق من العدد والانفصال عن أدوار اللجان فقط، وليس الأسماء
    النصية الحرفية.
    """
    response = await client.get("/api/v1/roles", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()

    committee_roles = [r for r in body if r["kind"] == "committee"]
    assert {r["committee_role_slug"] for r in committee_roles} == {"chair", "member"}
    assert {r["name"] for r in committee_roles} == {"رئيس اللجنة", "عضو اللجنة"}

    user_roles = [r for r in body if r["kind"] == "user"]
    assert len(user_roles) == 5
    assert all(r["committee_role_slug"] is None for r in user_roles)

    super_admin = next(r for r in user_roles if r["is_super_admin"])
    assert super_admin["is_super_admin"] is True


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


async def test_create_and_update_role_with_permission_scopes(
    client: AsyncClient, auth_headers
) -> None:
    """
    مراجعة لاما 2026-08-30: كل (دور، صلاحية) يحمل نطاق وصول مستقل
    (own/department/all) — يُنشأ ويُعدَّل عبر permission_scopes، ويُرجَع في
    RoleDetailOut.permissions[].scope. أي كود غير مذكور بـpermission_scopes
    يأخذ 'all' افتراضيًا (نفس فلسفة migration 0014).
    """
    create = await client.post(
        "/api/v1/roles",
        json={
            "name": "مراجع نطاقات",
            "permission_codes": ["departments.view", "users.view"],
            "permission_scopes": {"users.view": "own"},
        },
        headers=auth_headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    scopes = {p["code"]: p["scope"] for p in body["permissions"]}
    assert scopes == {"departments.view": "all", "users.view": "own"}

    role_id = body["role_id"]
    update = await client.patch(
        f"/api/v1/roles/{role_id}",
        json={
            "permission_codes": ["departments.view", "users.view"],
            "permission_scopes": {"users.view": "department"},
        },
        headers=auth_headers,
    )
    assert update.status_code == 200, update.text
    updated_scopes = {p["code"]: p["scope"] for p in update.json()["permissions"]}
    assert updated_scopes == {"departments.view": "all", "users.view": "department"}

    # إزالة صلاحية من التحديث تحذف ربطها بالكامل (وليس فقط تصفيرها).
    shrink = await client.patch(
        f"/api/v1/roles/{role_id}",
        json={"permission_codes": ["users.view"]},
        headers=auth_headers,
    )
    assert shrink.status_code == 200, shrink.text
    assert {p["code"] for p in shrink.json()["permissions"]} == {"users.view"}


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
