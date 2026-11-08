"""
اختبارات تعدد الأدوار للمستخدم الواحد (migration 0046 — صاحب المشروع 2026-11-08).

السيناريو المرجعي: نائب الرئيس التنفيذي يحمل دورين — "مكتب الرئيس التنفيذي"
و"ادمن" — ويبدّل بينهما من الشريط العلوي، ويشتغل بصلاحيات دوره الحالي فقط.

يغطي:
- إسناد أكثر من دور عند الإنشاء والتعديل، وضبط الدور الحالي.
- رفض أدوار اللجان والأدوار غير الموجودة.
- تبديل الدور الحالي: الصلاحيات تتبع الدور الحالي فقط، ولا يُقبل دور غير مسند.
- فحص رأس X-Active-Role (409) والمسارات المعفاة منه.
- /users/me: كل الأدوار + صلاحيات كل دور، بنفس عدد الاستعلامات السابق.
- حماية آخر super_admin مبنية على الأدوار المسندة وليس الدور الحالي.
- عدّاد مستخدمي الدور وحذف الدور يعتمدان على الأدوار المسندة.
- الإشعارات تصل عبر أي دور مسند.
- سجل التدقيق يسجّل الصفة (الدور الحالي) اللي نُفّذت بها العملية.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.user import UserStatus
from app.models.user_role import UserRole
from app.services import notification_service, user_service
from tests.test_meetings_query_budget import _QueryCounter, _drain_background_tasks

PASSWORD = "StrongPass1"


async def _custom_role(client: AsyncClient, headers: dict, *, codes: list[str], scope: str = "all") -> str:
    """دور مخصص بصلاحيات محددة (نطاق موحّد) — يرجّع role_id."""
    response = await client.post(
        "/api/v1/roles",
        json={
            "name": f"دور {uuid.uuid4().hex[:6]}",
            "permission_codes": codes,
            "permission_scopes": {code: scope for code in codes},
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["role_id"]


async def _create_user(client: AsyncClient, headers: dict, **fields) -> dict:
    username = fields.pop("username", f"u_{uuid.uuid4().hex[:8]}")
    payload = {
        "first_name": "نائب",
        "middle_name": "الرئيس",
        "last_name": "التنفيذي",
        "username": username,
        "email": f"{username}@example.com",
        "password": PASSWORD,
        **fields,
    }
    response = await client.post("/api/v1/users", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _login(client: AsyncClient, username: str) -> tuple[dict, dict]:
    """يرجّع (headers, user من رد الدخول)."""
    response = await client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


async def _assigned_role_ids(user_id: str) -> set[str]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(select(UserRole.role_id).where(UserRole.user_id == uuid.UUID(user_id)))
        return {str(r) for r in rows.scalars().all()}


# ============================ الإسناد عند الإنشاء والتعديل ============================


async def test_create_user_with_multiple_roles(client: AsyncClient, auth_headers, roles_by_name) -> None:
    """إنشاء مستخدم بدورين: كلاهما مسند، والدور الحالي = أول دور بالقائمة."""
    office, admin = roles_by_name["executive_office_manager"], roles_by_name["admin"]
    user = await _create_user(client, auth_headers, role_ids=[office, admin])

    assert user["role"]["role_id"] == office
    assert {r["role_id"] for r in user["roles"]} == {office, admin}
    assert await _assigned_role_ids(user["user_id"]) == {office, admin}


async def test_create_user_explicit_active_role(client: AsyncClient, auth_headers, roles_by_name) -> None:
    """role_id مع role_ids = الدور الحالي المطلوب."""
    office, admin = roles_by_name["executive_office_manager"], roles_by_name["admin"]
    user = await _create_user(client, auth_headers, role_ids=[office, admin], role_id=admin)
    assert user["role"]["role_id"] == admin


async def test_create_user_legacy_single_role_still_works(client: AsyncClient, auth_headers, roles_by_name) -> None:
    """role_id وحده (الطريقة القديمة) = دور واحد مسند وحالي."""
    admin = roles_by_name["admin"]
    user = await _create_user(client, auth_headers, role_id=admin)
    assert user["role"]["role_id"] == admin
    assert [r["role_id"] for r in user["roles"]] == [admin]


async def test_create_user_without_roles(client: AsyncClient, auth_headers) -> None:
    """الدور اختياري (قرار 2026-08-30) — يبقى كذلك مع تعدد الأدوار."""
    user = await _create_user(client, auth_headers)
    assert user["role"] is None and user["roles"] == []


async def test_create_user_rejects_invalid_role_selection(client: AsyncClient, auth_headers, roles_by_name) -> None:
    """دور لجنة، دور غير موجود، أو دور حالي ليس ضمن الأدوار → 400 بلا إنشاء."""
    office = roles_by_name["executive_office_manager"]
    cases = [
        {"role_ids": [office, roles_by_name["رئيس اللجنة"]]},
        {"role_ids": [office, str(uuid.uuid4())]},
        {"role_ids": [office], "role_id": roles_by_name["admin"]},
    ]
    for extra in cases:
        username = f"bad_{uuid.uuid4().hex[:6]}"
        response = await client.post(
            "/api/v1/users",
            json={
                "first_name": "أ", "middle_name": "ب", "last_name": "ج",
                "username": username, "email": f"{username}@example.com", "password": PASSWORD, **extra,
            },
            headers=auth_headers,
        )
        assert response.status_code == 400, (extra, response.text)


async def test_update_user_roles_replace_and_active_fallback(client: AsyncClient, auth_headers, roles_by_name) -> None:
    """
    استبدال الأدوار: الدور الحالي يبقى لو ما زال مسندًا، وإلا يصير أول دور
    بالقائمة الجديدة، و[] = بلا أدوار.
    """
    office, admin, president = (
        roles_by_name["executive_office_manager"], roles_by_name["admin"], roles_by_name["executive_president"],
    )
    user = await _create_user(client, auth_headers, role_ids=[office, admin])
    url = f"/api/v1/users/{user['user_id']}"

    kept = await client.patch(url, json={"role_ids": [president, office]}, headers=auth_headers)
    assert kept.status_code == 200, kept.text
    assert kept.json()["role"]["role_id"] == office
    assert {r["role_id"] for r in kept.json()["roles"]} == {president, office}
    assert await _assigned_role_ids(user["user_id"]) == {president, office}

    fallback = await client.patch(url, json={"role_ids": [admin]}, headers=auth_headers)
    assert fallback.json()["role"]["role_id"] == admin

    cleared = await client.patch(url, json={"role_ids": []}, headers=auth_headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["role"] is None and cleared.json()["roles"] == []
    assert await _assigned_role_ids(user["user_id"]) == set()


async def test_update_without_role_fields_keeps_roles(client: AsyncClient, auth_headers, roles_by_name) -> None:
    """تعديل الاسم فقط لا يلمس الأدوار."""
    office, admin = roles_by_name["executive_office_manager"], roles_by_name["admin"]
    user = await _create_user(client, auth_headers, role_ids=[office, admin])
    response = await client.patch(
        f"/api/v1/users/{user['user_id']}", json={"first_name": "جديد"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert {r["role_id"] for r in response.json()["roles"]} == {office, admin}


async def test_users_list_and_detail_include_all_roles(client: AsyncClient, auth_headers, roles_by_name) -> None:
    office, admin = roles_by_name["executive_office_manager"], roles_by_name["admin"]
    user = await _create_user(client, auth_headers, role_ids=[office, admin])

    listing = await client.get("/api/v1/users", headers=auth_headers)
    row = next(u for u in listing.json() if u["user_id"] == user["user_id"])
    assert {r["role_id"] for r in row["roles"]} == {office, admin}

    detail = await client.get(f"/api/v1/users/{user['user_id']}", headers=auth_headers)
    assert {r["role_id"] for r in detail.json()["roles"]} == {office, admin}


# ============================ تبديل الدور الحالي ============================


async def test_permissions_follow_active_role_and_switch(client: AsyncClient, auth_headers) -> None:
    """
    دور (أ) يملك users.view، ودور (ب) لا يملكها: بالدور (ب) الطلب مرفوض،
    وبعد التبديل لـ(أ) مسموح — الصلاحيات من الدور الحالي فقط، لا مجموع الأدوار.
    """
    viewer = await _custom_role(client, auth_headers, codes=["users.view"])
    other = await _custom_role(client, auth_headers, codes=["documents.view"])
    user = await _create_user(client, auth_headers, role_ids=[other, viewer])
    headers, me = await _login(client, user["username"])

    assert me["role"]["role_id"] == other
    assert "users.view" not in me["permissions"]
    assert (await client.get("/api/v1/users", headers=headers)).status_code == 403

    switched = await client.post("/api/v1/users/me/active-role", json={"role_id": viewer}, headers=headers)
    assert switched.status_code == 200, switched.text
    assert switched.json()["role"]["role_id"] == viewer
    assert "users.view" in switched.json()["permissions"]
    assert (await client.get("/api/v1/users", headers=headers)).status_code == 200


async def test_switch_rejects_unassigned_and_committee_roles(client: AsyncClient, auth_headers, roles_by_name) -> None:
    office = roles_by_name["executive_office_manager"]
    user = await _create_user(client, auth_headers, role_ids=[office])
    headers, _ = await _login(client, user["username"])

    for role_id in (roles_by_name["super_admin"], roles_by_name["رئيس اللجنة"], str(uuid.uuid4())):
        response = await client.post("/api/v1/users/me/active-role", json={"role_id": role_id}, headers=headers)
        assert response.status_code == 400, response.text

    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.json()["role"]["role_id"] == office


async def test_switch_is_audited_with_new_role(client: AsyncClient, auth_headers, roles_by_name) -> None:
    office, admin = roles_by_name["executive_office_manager"], roles_by_name["admin"]
    user = await _create_user(client, auth_headers, role_ids=[office, admin])
    headers, _ = await _login(client, user["username"])
    response = await client.post("/api/v1/users/me/active-role", json={"role_id": admin}, headers=headers)
    assert response.status_code == 200

    async with AsyncSessionLocal() as db:
        entry = (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.target_id == uuid.UUID(user["user_id"]), AuditLog.actor_user_id == uuid.UUID(user["user_id"]))
                .order_by(AuditLog.created_at.desc())
            )
        ).scalars().first()
    assert entry is not None
    assert entry.metadata_["event"] == "switch_active_role"
    assert entry.metadata_["from"] == "executive_office_manager" and entry.metadata_["to"] == "admin"
    assert str(entry.actor_role_id) == admin


# ============================ رأس X-Active-Role ============================


async def test_stale_active_role_header_gets_409(client: AsyncClient, auth_headers, roles_by_name) -> None:
    """
    تبويب يعرض الدور القديم بعد تبديله من تبويب آخر: طلباته ترجع 409
    (active_role_changed)، بينما /users/me وتبديل الدور معفيان (طريق التعافي).
    """
    viewer = await _custom_role(client, auth_headers, codes=["users.view"])
    office = roles_by_name["executive_office_manager"]
    user = await _create_user(client, auth_headers, role_ids=[viewer, office])
    headers, _ = await _login(client, user["username"])

    current = {**headers, "X-Active-Role": viewer}
    assert (await client.get("/api/v1/users", headers=current)).status_code == 200

    await client.post("/api/v1/users/me/active-role", json={"role_id": office}, headers=headers)

    stale = await client.get("/api/v1/users", headers=current)
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "active_role_changed"
    assert stale.json()["detail"]["active_role_id"] == office

    me = await client.get("/api/v1/users/me", headers=current)
    assert me.status_code == 200 and me.json()["role"]["role_id"] == office
    back = await client.post("/api/v1/users/me/active-role", json={"role_id": viewer}, headers=current)
    assert back.status_code == 200

    # بلا رأس = بلا فحص (عملاء قديمة)، والصلاحيات تبقى من قاعدة البيانات.
    assert (await client.get("/api/v1/users", headers=headers)).status_code == 200


# ============================ /users/me ============================


async def test_me_lists_roles_with_their_permissions_in_two_statements(
    client: AsyncClient, auth_headers, roles_by_name
) -> None:
    """
    /users/me لمستخدم متعدد الأدوار: كل الأدوار + صلاحيات كل دور، وعدد
    الاستعلامات نفس الحد السابق (≤2: المصادقة + استعلام الأعلام والأدوار).
    """
    viewer = await _custom_role(client, auth_headers, codes=["users.view", "documents.view"])
    office = roles_by_name["executive_office_manager"]
    user = await _create_user(client, auth_headers, role_ids=[office, viewer])
    headers, login_user = await _login(client, user["username"])

    await _drain_background_tasks()
    with _QueryCounter() as counter:
        me = await client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200, me.text
    assert counter.count <= 2, f"/users/me uses {counter.count} SQL statements"

    body = me.json()
    assert {r["role_id"] for r in body["roles"]} == {office, viewer}
    assert set(body["roles_permissions"]) == {office, viewer}
    assert sorted(body["roles_permissions"][viewer]) == ["documents.view", "users.view"]
    assert body["roles_permissions"][office]  # المكتب التنفيذي يملك صلاحيات طلبات التشكيل
    # صلاحيات الحساب الفعلية = الدور الحالي فقط
    assert set(body["permissions"]) == set(body["roles_permissions"][office])

    for payload in (login_user, body):
        payload.pop("updated_at"), payload.pop("last_login_at")
    assert login_user == body


async def test_me_for_user_without_roles(client: AsyncClient, auth_headers) -> None:
    user = await _create_user(client, auth_headers)
    headers, _ = await _login(client, user["username"])
    body = (await client.get("/api/v1/users/me", headers=headers)).json()
    assert body["role"] is None and body["roles"] == [] and body["roles_permissions"] == {}


# ============================ حماية آخر super_admin ============================


async def test_last_super_admin_protection_uses_assigned_roles(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    """
    - إزالة دور super_admin عن السوبر ادمن الوحيد → 400.
    - لو فيه سوبر ادمن ثاني دوره *الحالي* "ادمن" لكنه يحمل دور super_admin،
      يُحسب كسوبر ادمن قادر → الإزالة عن الأول مسموحة.
    """
    super_admin, admin = roles_by_name["super_admin"], roles_by_name["admin"]
    url = f"/api/v1/users/{super_admin_user.user_id}"

    blocked = await client.patch(url, json={"role_ids": [admin]}, headers=auth_headers)
    assert blocked.status_code == 400, blocked.text

    second = await _create_user(client, auth_headers, role_ids=[admin, super_admin])
    assert second["role"]["role_id"] == admin  # دوره الحالي ليس super_admin

    allowed = await client.patch(url, json={"role_ids": [admin]}, headers=auth_headers)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["role"]["role_id"] == admin


async def test_cannot_delete_or_suspend_super_admin_whose_active_role_is_other(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    """
    آخر حامل لدور super_admin بدّل دوره الحالي لـ"ادمن": يبقى محميًا من
    الحذف والإيقاف (الحماية على الأدوار المسندة، مو الدور الحالي).
    """
    super_admin, admin = roles_by_name["super_admin"], roles_by_name["admin"]
    second = await _create_user(client, auth_headers, role_ids=[super_admin, admin])
    # الأول يتنازل عن super_admin (مسموح لأن الثاني يحمله)
    response = await client.patch(
        f"/api/v1/users/{super_admin_user.user_id}", json={"role_ids": [admin]}, headers=auth_headers
    )
    assert response.status_code == 200, response.text

    second_headers, _ = await _login(client, second["username"])
    switched = await client.post("/api/v1/users/me/active-role", json={"role_id": admin}, headers=second_headers)
    assert switched.json()["role"]["role_id"] == admin

    second_id = uuid.UUID(second["user_id"])
    async with AsyncSessionLocal() as db:
        with pytest.raises(ValueError, match="آخر super_admin"):
            await user_service.soft_delete_user(db, actor_user_id=super_admin_user.user_id, user_id=second_id)
    async with AsyncSessionLocal() as db:
        with pytest.raises(ValueError, match="آخر super_admin"):
            await user_service.set_user_status(
                db, actor_user_id=super_admin_user.user_id, user_id=second_id, status=UserStatus.suspended
            )


# ============================ الأدوار: العدّاد والحذف ============================


async def test_role_user_count_and_delete_use_assigned_roles(client: AsyncClient, auth_headers, roles_by_name) -> None:
    """دور مسند لمستخدم كدور غير حالي: يُحسب بعدّاد الدور، ويُمنع حذفه."""
    extra = await _custom_role(client, auth_headers, codes=["documents.view"])
    office = roles_by_name["executive_office_manager"]
    await _create_user(client, auth_headers, role_ids=[office, extra])

    detail = await client.get(f"/api/v1/roles/{extra}", headers=auth_headers)
    assert detail.json()["user_count"] == 1
    listing = await client.get("/api/v1/roles", headers=auth_headers)
    assert next(r for r in listing.json() if r["role_id"] == extra)["user_count"] == 1

    delete = await client.delete(f"/api/v1/roles/{extra}", headers=auth_headers)
    assert delete.status_code == 400, delete.text


# ============================ الإشعارات ============================


async def test_notification_targets_include_non_active_roles(client: AsyncClient, auth_headers, roles_by_name) -> None:
    """
    مستخدم دوره الحالي "ادمن" ويحمل دور المكتب التنفيذي: يُستهدف بإشعارات
    صلاحية المكتب (committees.request.view) — ما تفوته الطلبات وهو بدور آخر.
    """
    office, admin = roles_by_name["executive_office_manager"], roles_by_name["admin"]
    user = await _create_user(client, auth_headers, role_ids=[office, admin], role_id=admin)

    async with AsyncSessionLocal() as db:
        targets = await notification_service._users_with_permission(db, "committees.request.view")
    assert uuid.UUID(user["user_id"]) in targets


# ============================ سجل التدقيق: الصفة ============================


async def test_audit_log_records_actor_role(client: AsyncClient, auth_headers, roles_by_name) -> None:
    """عملية ينفّذها مستخدم مسجَّل الدخول تُسجَّل بصفته (دوره الحالي)، وتظهر بسجل النشاط."""
    await _create_user(client, auth_headers, role_id=roles_by_name["admin"])
    page = await client.get("/api/v1/audit-logs?target_type=user&limit=5", headers=auth_headers)
    assert page.status_code == 200, page.text
    latest = page.json()["items"][0]
    assert latest["action_type"] == "create"
    assert latest["actor_role_name"] == "super_admin"
