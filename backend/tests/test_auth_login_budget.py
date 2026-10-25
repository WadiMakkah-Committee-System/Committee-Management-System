"""
تسجيل الدخول وGET /users/me (تحسين أداء 2026-10-24): عدد استعلامات ثابت
وصغير، ونفس النتائج تمامًا. كان تسجيل الدخول 10 استعلامات (المستخدم بشجرة
دوره وصلاحياته مرتين: قبل التحقق وبعد commit)، و/users/me 3.
"""

import uuid

from httpx import AsyncClient

from app.db.session import AsyncSessionLocal
from app.services import committee_service
from tests.test_decisions import _create_approved_committee
from tests.test_meetings_query_budget import _QueryCounter, _drain_background_tasks


async def test_login_uses_few_statements_and_still_works(
    client: AsyncClient, super_admin_user
) -> None:
    await _drain_background_tasks()
    with _QueryCounter() as counter:
        response = await client.post(
            "/api/v1/auth/login", json={"username": super_admin_user.username, "password": "StrongPass1"}
        )
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]
    # 2026-10-25: +1 (أعلام عضوية اللجان) لأن الرد صار يتضمن بيانات
    # المستخدم بشكل /users/me — مقابل إلغاء طلب /users/me كامل بعده.
    assert counter.count <= 5, f"login uses {counter.count} SQL statements"

    me = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {response.json()['access_token']}"},
    )
    assert me.status_code == 200 and me.json()["user_id"] == str(super_admin_user.user_id)
    # نفس بيانات /users/me بالضبط (updated_at يحدّثه trigger بقاعدة البيانات
    # عند تسجيل الدخول نفسه، ولا تعرضه الواجهة).
    login_user = dict(response.json()["user"])
    me_body = dict(me.json())
    login_user.pop("updated_at"), me_body.pop("updated_at")
    assert login_user == me_body


async def test_login_user_matches_me_for_committee_member(
    client: AsyncClient, auth_headers, roles_by_name
) -> None:
    ctx = await _create_approved_committee(
        client, auth_headers, roles_by_name, suffix="loginme", member_count=1
    )
    me = (await client.get("/api/v1/users/me", headers=ctx["member_headers_list"][0])).json()
    response = await client.post(
        "/api/v1/auth/login", json={"username": me["username"], "password": "StrongPass1"}
    )
    assert response.status_code == 200, response.text
    login_user = dict(response.json()["user"])
    assert login_user["has_any_committee_membership"] is True
    for body in (login_user, me):
        body.pop("updated_at"), body.pop("last_login_at")
    assert login_user == me


async def test_refresh_does_not_include_user(client: AsyncClient, super_admin_user) -> None:
    tokens = (
        await client.post(
            "/api/v1/auth/login", json={"username": super_admin_user.username, "password": "StrongPass1"}
        )
    ).json()
    refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200 and refreshed.json()["user"] is None


async def test_me_committee_flags_match_previous_checks(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    ctx = await _create_approved_committee(
        client, auth_headers, roles_by_name, suffix="meflags", member_count=1
    )
    cases = [
        (ctx["member_headers_list"][0], ctx["member_ids"][0]),
        (ctx["chair_headers"], ctx["chair_id"]),
        (auth_headers, str(super_admin_user.user_id)),
    ]
    for headers, user_id in cases:
        await _drain_background_tasks()
        with _QueryCounter() as counter:
            me = await client.get("/api/v1/users/me", headers=headers)
        assert me.status_code == 200, me.text
        assert counter.count <= 2, f"/users/me uses {counter.count} SQL statements"
        async with AsyncSessionLocal() as db:
            uid = uuid.UUID(user_id)
            expected_access = await committee_service.user_has_committee_role_view_access(db, user_id=uid)
            expected_any = await committee_service.user_has_any_committee_membership(db, user_id=uid)
        body = me.json()
        assert body["has_committee_membership_access"] == expected_access
        assert body["has_any_committee_membership"] == expected_any
    assert me.json()["has_any_committee_membership"] is False  # super admin ليس عضوًا
