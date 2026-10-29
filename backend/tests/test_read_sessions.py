"""
اختبارات تحسين أداء 2026-10-28 (راجعي app/db/session.py):

- طلبات القراءة (GET) تعمل بجلسة AUTOCOMMIT — بلا رحلتي BEGIN/ROLLBACK.
- أي طلب كتابة، وأي راوت GET مُعلَّم بـ@writes_on_read، يبقى بمعاملة كاملة.
- GET /roles/options يرجّع الأدوار بدون الصلاحيات (للقوائم المنسدلة).
"""

from httpx import AsyncClient
from sqlalchemy import event

from app.db.session import engine


class _IsolationRecorder:
    """يسجّل مستوى العزل لكل جملة SQL تُنفَّذ أثناء الطلب."""

    def __init__(self) -> None:
        self.levels: list[str | None] = []

    def __enter__(self) -> "_IsolationRecorder":
        event.listen(engine.sync_engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *exc) -> None:
        event.remove(engine.sync_engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, conn, *args, **kwargs) -> None:
        self.levels.append(conn.get_execution_options().get("isolation_level"))


async def test_get_request_runs_without_transaction(client: AsyncClient, auth_headers) -> None:
    with _IsolationRecorder() as rec:
        response = await client.get("/api/v1/users/me", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert rec.levels, "expected SQL statements"
    assert all(level == "AUTOCOMMIT" for level in rec.levels), rec.levels


async def test_write_request_keeps_full_transaction(client: AsyncClient, super_admin_user) -> None:
    with _IsolationRecorder() as rec:
        response = await client.post(
            "/api/v1/auth/login", json={"username": "super_admin_test", "password": "StrongPass1"}
        )
    assert response.status_code == 200, response.text
    assert rec.levels and all(level != "AUTOCOMMIT" for level in rec.levels), rec.levels
    # رد الدخول ما زال يحمل الملف الشخصي كاملًا (يُبنى الآن داخل نفس المعاملة).
    body = response.json()
    assert body["user"]["username"] == "super_admin_test"
    assert "has_any_committee_membership" in body["user"]


async def test_get_route_marked_writes_on_read_keeps_transaction(client: AsyncClient, auth_headers) -> None:
    # list_decisions قد يغلق تصويتًا انتهت مدته أثناء القراءة — مُعلَّم بـ@writes_on_read.
    with _IsolationRecorder() as rec:
        response = await client.get("/api/v1/decisions", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert rec.levels and all(level != "AUTOCOMMIT" for level in rec.levels), rec.levels


async def test_role_options_are_light(client: AsyncClient, auth_headers) -> None:
    full = await client.get("/api/v1/roles", headers=auth_headers)
    options = await client.get("/api/v1/roles/options", headers=auth_headers)
    assert full.status_code == 200 and options.status_code == 200, options.text

    by_id = {r["role_id"]: r for r in options.json()}
    assert set(by_id) == {r["role_id"] for r in full.json()}
    for role in full.json():
        option = by_id[role["role_id"]]
        assert option["name"] == role["name"] and option["kind"] == role["kind"]
        assert "permissions" not in option and "user_count" not in option


async def test_role_options_require_super_admin(client: AsyncClient) -> None:
    response = await client.get("/api/v1/roles/options")
    assert response.status_code == 401
