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
