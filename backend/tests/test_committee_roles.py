"""
اختبارات "أدوار اللجان" (Committee Roles: رئيس اللجنة/عضو اللجنة) — بلاغ
لاما 2026-08-31. راجعي db/migrations/0016، app/models/committee.py،
app/services/committee_service.py::get_committee_role_permission_codes،
وapp/api/v1/committees.py::get_committee للتصميم الكامل.

نقطة مهمة (تختلف عن بقية ملفات الاختبار هنا عمدًا): لا نستخدم أسماء
الأدوار النظامية الخمسة الثابتة (roles_by_name["admin"] ...) لبناء ممثلي
طلب التشكيل (admin/office/ceo) — نبني أدوارًا مخصَّصة بصلاحيات محددة صراحة
(بنفس نمط _create_role_and_login في test_committees.py)، لأن هذه الاختبارات
تعمل ضد قاعدة بيانات حقيقية قد تكون فيها الأدوار النظامية الخمسة أعيدت
تسميتها فعليًا من واجهة الإنتاج (is_system لم يعد يمنع إعادة التسمية —
قرار موثّق 2026-08-27) — الاعتماد على اسم دور نظامي ثابت هش هنا تحديدًا.

الاستثناء الوحيد: "مستخدم نظام" — مذكور صراحة بنص متطلب لاما 2026-08-31
كـSystem Role لمستخدم الاختبار الرئيسي (User A)، ومؤكَّد أنه لا يملك أي
صلاحية committees.view (فقط users.view بنطاق own) — فهو مثالي لإثبات أن
الوصول هنا يأتي فعليًا من عضوية اللجنة (Committee Role) لا من أي صلاحية
نظامية.
"""

from httpx import AsyncClient

from app.db.session import AsyncSessionLocal
from app.models.role import Role


async def _actor(
    client: AsyncClient,
    auth_headers: dict[str, str],
    *,
    username: str,
    permission_codes: list[str],
) -> dict[str, str]:
    """يبني دورًا مخصصًا بصلاحيات محددة صراحة + مستخدمًا يحملها، ويرجع headers جاهزة."""
    role = await client.post(
        "/api/v1/roles",
        json={"name": f"role_{username}", "permission_codes": permission_codes},
        headers=auth_headers,
    )
    assert role.status_code == 201, role.text
    create = await client.post(
        "/api/v1/users",
        json={
            "first_name": "أ",
            "middle_name": "ب",
            "last_name": "ج",
            "username": username,
            "email": f"{username}@example.com",
            "password": "StrongPass1",
            "role_id": role.json()["role_id"],
            "dep_id": None,
        },
        headers=auth_headers,
    )
    assert create.status_code == 201, create.text
    login = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "StrongPass1"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _create_system_user(
    client: AsyncClient,
    auth_headers: dict[str, str],
    roles_by_name: dict[str, str],
    *,
    username: str,
) -> tuple[dict[str, str], str]:
    """مستخدم بدوره النظامي "مستخدم نظام" حرفيًا (راجعي docstring أعلى الملف)."""
    create = await client.post(
        "/api/v1/users",
        json={
            "first_name": "أ",
            "middle_name": "ب",
            "last_name": "ج",
            "username": username,
            "email": f"{username}@example.com",
            "password": "StrongPass1",
            "role_id": roles_by_name["مستخدم نظام"],
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
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, user_id


async def _approve_committee(
    client: AsyncClient,
    *,
    admin_headers: dict[str, str],
    office_headers: dict[str, str],
    ceo_headers: dict[str, str],
    name: str,
    member_ids: list[str],
    chair_id: str,
) -> str:
    """دورة حياة كاملة (draft → submitted → pending_approval → approved) وترجع committee_id."""
    payload = {
        "committee_name": name,
        "statement": "بيان اللجنة",
        "start_date": "2026-09-01",
        "end_date": "2026-12-01",
        "proposed_member_ids": member_ids,
        "chair_user_id": chair_id,
    }
    create = await client.post("/api/v1/committee-requests", json=payload, headers=admin_headers)
    assert create.status_code == 201, create.text
    request_id = create.json()["request_id"]
    submit = await client.post(
        f"/api/v1/committee-requests/{request_id}/submit", headers=admin_headers
    )
    assert submit.status_code == 200, submit.text
    escalate = await client.post(
        f"/api/v1/committee-requests/{request_id}/escalate", headers=office_headers
    )
    assert escalate.status_code == 200, escalate.text
    approve = await client.post(
        f"/api/v1/committee-requests/{request_id}/approve", headers=ceo_headers
    )
    assert approve.status_code == 200, approve.text
    return approve.json()["committee_id"]


async def _setup_request_actors(
    client: AsyncClient, auth_headers: dict[str, str]
) -> dict[str, dict[str, str]]:
    admin_headers = await _actor(
        client, auth_headers, username="cr_admin", permission_codes=["committees.request.create"]
    )
    office_headers = await _actor(
        client,
        auth_headers,
        username="cr_office",
        permission_codes=["committees.request.update", "committees.request.escalate"],
    )
    ceo_headers = await _actor(
        client, auth_headers, username="cr_ceo", permission_codes=["committees.request.approve"]
    )
    return {"admin_headers": admin_headers, "office_headers": office_headers, "ceo_headers": ceo_headers}


def _member_role_slug(committee_body: dict, user_id: str) -> str | None:
    for entry in committee_body["member_roles"]:
        if entry["user"]["user_id"] == user_id:
            return entry["committee_role"]["committee_role_slug"]
    return None


async def test_committee_role_permission_scoped_to_specific_committee_membership(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    السيناريو المطلوب صراحة (بلاغ لاما 2026-08-31): مستخدم System Role
    "مستخدم نظام" — رئيس بلجنة A، عضو بلجنة B، وليس عضوًا بلجنة C إطلاقًا.
    يجب أن تنطبق صلاحيات "رئيس اللجنة" فقط داخل A، وصلاحيات "عضو اللجنة"
    فقط داخل B، ولا شيء إطلاقًا بخصوص C — رغم أن "مستخدم نظام" لا يملك أي
    صلاحية committees.view نظامية أصلًا (النطاق هنا عضوية اللجنة نفسها، لا
    own/department/all).
    """
    actors = await _setup_request_actors(client, auth_headers)
    chair_headers, chair_id = await _create_system_user(
        client, auth_headers, roles_by_name, username="cr_chair"
    )
    _, user_a_id = await _create_system_user(client, auth_headers, roles_by_name, username="cr_user_a")
    _, user_b_id = await _create_system_user(client, auth_headers, roles_by_name, username="cr_user_b")

    committee_a = await _approve_committee(
        client,
        **actors,
        name="لجنة A — رئيس",
        member_ids=[chair_id, user_a_id],
        chair_id=chair_id,
    )
    committee_b = await _approve_committee(
        client,
        **actors,
        name="لجنة B — عضو",
        member_ids=[user_b_id, chair_id],
        chair_id=user_b_id,
    )
    committee_c = await _approve_committee(
        client,
        **actors,
        name="لجنة C — بلا عضوية",
        member_ids=[user_a_id, user_b_id],
        chair_id=user_b_id,
    )

    resp_a = await client.get(f"/api/v1/committees/{committee_a}", headers=chair_headers)
    assert resp_a.status_code == 200, resp_a.text
    assert _member_role_slug(resp_a.json(), chair_id) == "chair"

    resp_b = await client.get(f"/api/v1/committees/{committee_b}", headers=chair_headers)
    assert resp_b.status_code == 200, resp_b.text
    assert _member_role_slug(resp_b.json(), chair_id) == "member"

    resp_c = await client.get(f"/api/v1/committees/{committee_c}", headers=chair_headers)
    assert resp_c.status_code == 403, resp_c.text


async def test_editing_committee_chair_permissions_propagates_to_all_committees_immediately(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    السيناريو الثاني المطلوب صراحة: تعديل صلاحيات "رئيس اللجنة" من صفحة
    الأدوار والصلاحيات ينعكس فورًا على كل من يحمل هذا الدور بأي لجنة —
    بدون أي تعديل يدوي لكل لجنة/مستخدم على حدة (مصدر الحقيقة الوحيد هو
    role_permissions، تُقرأ حيًا في كل طلب — راجعي
    committee_service.get_committee_role_permission_codes).
    """
    actors = await _setup_request_actors(client, auth_headers)
    chair_headers, chair_id = await _create_system_user(
        client, auth_headers, roles_by_name, username="cr_chair2"
    )
    _, user_a_id = await _create_system_user(client, auth_headers, roles_by_name, username="cr_user_a2")

    committee_id = await _approve_committee(
        client,
        **actors,
        name="لجنة اختبار انعكاس الصلاحيات",
        member_ids=[chair_id, user_a_id],
        chair_id=chair_id,
    )

    baseline = await client.get(f"/api/v1/committees/{committee_id}", headers=chair_headers)
    assert baseline.status_code == 200, baseline.text

    chair_role_id = roles_by_name["رئيس اللجنة"]
    role_detail = await client.get(f"/api/v1/roles/{chair_role_id}", headers=auth_headers)
    assert role_detail.status_code == 200, role_detail.text
    original_codes = [p["code"] for p in role_detail.json()["permissions"]]
    original_scopes = {p["code"]: p["scope"] for p in role_detail.json()["permissions"]}
    assert "committees.view" in original_codes  # تأكيد افتراض الحالة الأولية قبل التعديل

    try:
        reduced_codes = [c for c in original_codes if c != "committees.view"]
        patch = await client.patch(
            f"/api/v1/roles/{chair_role_id}",
            json={"permission_codes": reduced_codes},
            headers=auth_headers,
        )
        assert patch.status_code == 200, patch.text

        after = await client.get(f"/api/v1/committees/{committee_id}", headers=chair_headers)
        assert after.status_code == 403, after.text
    finally:
        # استرجاع الحالة الأصلية إلزاميًا — هذا دور حقيقي مشترك بكل اللجان
        # (وقاعدة بيانات إنتاج فعلية بحسب إعداد الاختبارات الحالي بالمشروع)،
        # وليس بيانات اختبار مؤقتة تُنظَّف تلقائيًا بين الاختبارات.
        restore = await client.patch(
            f"/api/v1/roles/{chair_role_id}",
            json={"permission_codes": original_codes, "permission_scopes": original_scopes},
            headers=auth_headers,
        )
        assert restore.status_code == 200, restore.text


async def test_delete_role_rejects_committee_kind_roles(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """"رئيس اللجنة"/"عضو اللجنة" دوران بنيويان ثابتان — لا يمكن حذفهما إطلاقًا."""
    chair_role_id = roles_by_name["رئيس اللجنة"]
    response = await client.delete(f"/api/v1/roles/{chair_role_id}", headers=auth_headers)
    assert response.status_code == 400, response.text
    assert "أدوار اللجان" in response.json()["detail"]

    still_exists = await client.get(f"/api/v1/roles/{chair_role_id}", headers=auth_headers)
    assert still_exists.status_code == 200


async def test_approve_request_assigns_chair_and_member_committee_roles_correctly(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    اعتماد طلب تشكيل يُنشئ عضوية اللجنة بدور صحيح لكل عضو تلقائيًا: رئيس
    واحد (chair_user_id بالطلب)، والبقية أعضاء — بدون أي تدخل يدوي، وبدون
    أي تأثير على System Role لأي منهم (يبقى "مستخدم نظام" كما هو).
    """
    actors = await _setup_request_actors(client, auth_headers)
    chair_headers, chair_id = await _create_system_user(
        client, auth_headers, roles_by_name, username="cr_chair3"
    )
    _, user_a_id = await _create_system_user(client, auth_headers, roles_by_name, username="cr_user_a3")
    _, user_b_id = await _create_system_user(client, auth_headers, roles_by_name, username="cr_user_b3")

    committee_id = await _approve_committee(
        client,
        **actors,
        name="لجنة اختبار تعيين الأدوار",
        member_ids=[chair_id, user_a_id, user_b_id],
        chair_id=chair_id,
    )

    fetched = await client.get(f"/api/v1/committees/{committee_id}", headers=chair_headers)
    assert fetched.status_code == 200, fetched.text
    body = fetched.json()
    assert _member_role_slug(body, chair_id) == "chair"
    assert _member_role_slug(body, user_a_id) == "member"
    assert _member_role_slug(body, user_b_id) == "member"

    # System Role لكل الأعضاء يبقى "مستخدم نظام" كما هو — الاعتماد لم يغيّره إطلاقًا.
    async with AsyncSessionLocal() as db:
        chair_role = await db.get(Role, roles_by_name["مستخدم نظام"])
        assert chair_role is not None  # الدور نفسه لم يُمس؛ نتأكد فقط من عدم كسره
    me = await client.get("/api/v1/users/me", headers=chair_headers)
    assert me.status_code == 200
    assert me.json()["role"]["role_id"] == roles_by_name["مستخدم نظام"]


async def test_list_committees_visible_to_committee_member_without_system_permission(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    بلاغ لاما 2026-09-01 ("جود وسعود ما يظهر لهم قسم اللجان"): GET /committees
    (قائمة اللجان — نقطة الدخول الفعلية لقسم "اللجان" بالواجهة) كان يتطلب
    committees.view على مستوى System Role حصرًا، بدون أي مسار بديل عبر
    عضوية اللجنة الفعلية — عكس GET /committees/{id} (لجنة واحدة) اللي فيه
    هذا المسار البديل أصلًا منذ مراجعة 2026-08-31. عضو System Role "مستخدم
    نظام" (بدون أي committees.view نظامي) لكنه رئيس/عضو فعلي بلجنة معتمدة
    يجب أن يرى لجنته بالقائمة الآن، بينما مستخدم غير عضو بأي لجنة إطلاقًا
    (وبدون صلاحية نظامية) يبقى مرفوضًا 403 كما هو متوقع.
    """
    actors = await _setup_request_actors(client, auth_headers)
    chair_headers, chair_id = await _create_system_user(
        client, auth_headers, roles_by_name, username="cr_list_chair"
    )
    member_headers, member_id = await _create_system_user(
        client, auth_headers, roles_by_name, username="cr_list_member"
    )
    outsider_headers, _ = await _create_system_user(
        client, auth_headers, roles_by_name, username="cr_list_outsider"
    )

    committee_id = await _approve_committee(
        client,
        **actors,
        name="لجنة اختبار ظهور القائمة",
        member_ids=[chair_id, member_id],
        chair_id=chair_id,
    )

    # الرئيس (System Role بلا committees.view) يرى لجنته بالقائمة.
    chair_list = await client.get("/api/v1/committees", headers=chair_headers)
    assert chair_list.status_code == 200, chair_list.text
    assert committee_id in [c["committee_id"] for c in chair_list.json()]

    # العضو العادي (System Role بلا committees.view) يرى لجنته بالقائمة أيضًا.
    member_list = await client.get("/api/v1/committees", headers=member_headers)
    assert member_list.status_code == 200, member_list.text
    assert committee_id in [c["committee_id"] for c in member_list.json()]

    # مستخدم غير عضو بأي لجنة وبلا صلاحية نظامية — يبقى مرفوضًا 403.
    outsider_list = await client.get("/api/v1/committees", headers=outsider_headers)
    assert outsider_list.status_code == 403, outsider_list.text

    # نفس الشيء ينعكس بـ/users/me عبر has_committee_membership_access —
    # الحقل اللي تعتمد عليه القائمة الجانبية بالواجهة لإظهار قسم "اللجان".
    chair_me = await client.get("/api/v1/users/me", headers=chair_headers)
    assert chair_me.json()["has_committee_membership_access"] is True
    outsider_me = await client.get("/api/v1/users/me", headers=outsider_headers)
    assert outsider_me.json()["has_committee_membership_access"] is False
