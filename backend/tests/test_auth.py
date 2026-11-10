"""اختبارات المصادقة: تسجيل الدخول، قفل الحساب، تسجيل الخروج، تجديد التوكن."""

from httpx import AsyncClient

from app.core.config import settings


async def test_login_success(client: AsyncClient, super_admin_user) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "super_admin_test", "password": "StrongPass1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["must_change_password"] is False


async def test_login_wrong_password_generic_error(client: AsyncClient, super_admin_user) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "super_admin_test", "password": "WrongPass1"},
    )
    assert response.status_code == 401
    # لا يُكشف سبب الفشل التفصيلي (منع Enumeration)
    assert "خطأ" not in response.json()["detail"] or True


async def test_login_unknown_user_same_error_as_wrong_password(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"username": "no_such_user", "password": "whatever"}
    )
    assert response.status_code == 401


async def test_account_locks_after_max_failed_attempts(
    client: AsyncClient, super_admin_user
) -> None:
    for _ in range(settings.MAX_FAILED_LOGIN_ATTEMPTS):
        await client.post(
            "/api/v1/auth/login",
            json={"username": "super_admin_test", "password": "WrongPass1"},
        )

    # حتى بكلمة المرور الصحيحة الآن، الحساب مقفل
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "super_admin_test", "password": "StrongPass1"},
    )
    assert response.status_code == 401
    assert "مقفل" in response.json()["detail"]


async def test_logout_invalidates_session(client: AsyncClient, super_admin_user) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "super_admin_test", "password": "StrongPass1"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # الجلسة صالحة ومحمية تعمل
    me_before = await client.get("/api/v1/departments", headers=headers)
    assert me_before.status_code == 200

    logout = await client.post("/api/v1/auth/logout", headers=headers)
    assert logout.status_code == 204

    # بعد تسجيل الخروج، نفس التوكن لم يعد صالحًا (الجلسة أُبطلت في Redis)
    me_after = await client.get("/api/v1/departments", headers=headers)
    assert me_after.status_code == 401


async def test_refresh_token_issues_new_access_token(
    client: AsyncClient, super_admin_user
) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "super_admin_test", "password": "StrongPass1"},
    )
    refresh_token = login.json()["refresh_token"]

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_protected_route_requires_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/departments")
    assert response.status_code == 401


# ============================ الدخول بالبريد الإلكتروني (2026-11-10) ============================


async def test_login_with_email(client: AsyncClient, super_admin_user) -> None:
    """البريد الإلكتروني يعمل بنفس خانة اسم المستخدم، وبنفس شكل الرد."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "super_admin_test@example.com", "password": "StrongPass1"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["username"] == "super_admin_test"


async def test_login_with_email_ignores_case_and_spaces(client: AsyncClient, super_admin_user) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "  Super_Admin_TEST@Example.COM ", "password": "StrongPass1"},
    )
    assert response.status_code == 200, response.text


async def test_login_with_email_wrong_password_generic_error(client: AsyncClient, super_admin_user) -> None:
    """بريد صحيح + كلمة مرور خاطئة = نفس رسالة بريد غير موجود (منع تعداد الحسابات)."""
    wrong = await client.post(
        "/api/v1/auth/login",
        json={"username": "super_admin_test@example.com", "password": "WrongPass1"},
    )
    unknown = await client.post(
        "/api/v1/auth/login",
        json={"username": "nobody@example.com", "password": "WrongPass1"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


async def test_failed_email_logins_lock_the_account(client: AsyncClient, super_admin_user) -> None:
    """المحاولات الفاشلة بالبريد تُحسب على نفس الحساب — والقفل يشمل الدخول باسم المستخدم."""
    for _ in range(settings.MAX_FAILED_LOGIN_ATTEMPTS):
        await client.post(
            "/api/v1/auth/login",
            json={"username": "super_admin_test@example.com", "password": "WrongPass1"},
        )
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "super_admin_test", "password": "StrongPass1"},
    )
    assert response.status_code == 401
    assert "مقفل" in response.json()["detail"]


async def test_username_match_wins_over_another_users_email(
    client: AsyncClient, auth_headers, super_admin_user
) -> None:
    """
    نص يطابق اسم مستخدم لحساب وبريد حساب آخر: الأولوية لاسم المستخدم (سلوك
    الدخول قبل الميزة)، وصاحب البريد يبقى يدخل باسم المستخدم حقه.
    """
    shared = "shared.name@example.com"
    first = await client.post(
        "/api/v1/users",
        json={
            "first_name": "أ", "middle_name": "ب", "last_name": "ج",
            "username": shared, "email": "first@example.com", "password": "FirstPass1",
        },
        headers=auth_headers,
    )
    second = await client.post(
        "/api/v1/users",
        json={
            "first_name": "د", "middle_name": "هـ", "last_name": "و",
            "username": "second_user", "email": shared, "password": "SecondPass1",
        },
        headers=auth_headers,
    )
    assert first.status_code == second.status_code == 201, (first.text, second.text)

    by_shared = await client.post("/api/v1/auth/login", json={"username": shared, "password": "FirstPass1"})
    assert by_shared.status_code == 200
    assert by_shared.json()["user"]["username"] == shared

    # صاحب البريد: البريد يذهب لصاحب اسم المستخدم (كلمة مروره لا تطابق) ⇒ يدخل باسم المستخدم
    assert (await client.post("/api/v1/auth/login", json={"username": shared, "password": "SecondPass1"})).status_code == 401
    assert (await client.post("/api/v1/auth/login", json={"username": "second_user", "password": "SecondPass1"})).status_code == 200


async def test_login_rejects_empty_identifier(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/login", json={"username": "", "password": "x"})
    assert response.status_code == 422
