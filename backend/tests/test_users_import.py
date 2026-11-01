"""
الهدف:
اختبارات رفع ملف المستخدمين (users.import — 2026-11-01): النموذج، الإنشاء
الكامل (اسم مستخدم + كلمة مرور مؤقتة + بريد لكل واحد)، الكل أو لا شيء،
مطابقة الأدوار، الإدارات الجديدة ومديرها، المسميات، حدود الملف، والصلاحيات
(بدون صلاحية، نطاق الإدارة، منع تصعيد الصلاحيات، منع إسناد المسؤول الأعلى).

البريد لا يُرسل فعليًا — notify_imported_users_credentials مُستبدَلة بدالة
تلتقط (البريد، الاسم، اسم المستخدم، كلمة المرور).
"""

import asyncio
import io
import uuid

import pytest
from httpx import AsyncClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import select

from app.core import background
from app.core.security import hash_password, validate_password_policy
from app.db.session import AsyncSessionLocal
from app.models.department import Department
from app.models.job_title import JobTitle
from app.models.role import Role
from app.models.user import User
from app.services import notification_service
from app.services.user_import_service import (
    MAX_ROWS,
    TEMPLATE_HEADERS,
    generate_temporary_password,
    unique_username,
    username_base_from_email,
)

IMPORT = "/api/v1/users/import"
TEMPLATE = "/api/v1/users/import/template"
MANAGER = "مدير إدارة (أدمن)"


def _xlsx(rows: list[list[str | None]], headers: list[str] = TEMPLATE_HEADERS, sheet: str = "المستخدمين") -> bytes:
    workbook = Workbook()
    ws = workbook.active
    ws.title = sheet
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def _upload(client: AsyncClient, headers: dict, content: bytes, filename: str = "users.xlsx"):
    return await client.post(
        IMPORT,
        files={"file": (filename, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )


async def _flush_background() -> None:
    pending = list(background._pending_tasks)
    if pending:
        await asyncio.wait(pending, timeout=10)


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    captured: list[tuple] = []

    async def fake_notify(accounts, *, login_url):
        captured.extend(accounts)

    monkeypatch.setattr(notification_service, "notify_imported_users_credentials", fake_notify)
    return captured


async def _user_count() -> int:
    async with AsyncSessionLocal() as db:
        return len((await db.execute(select(User).where(User.deleted_at.is_(None)))).scalars().all())


async def _job_title(name: str) -> None:
    async with AsyncSessionLocal() as db:
        exists = (await db.execute(select(JobTitle).where(JobTitle.name == name))).scalar_one_or_none()
        if exists is None:
            db.add(JobTitle(name=name))
            await db.commit()


async def _system_user_role() -> None:
    """دور "مستخدم نظام" غير موجود بالـmigrations (أُنشئ يدويًا بالإنتاج)."""
    async with AsyncSessionLocal() as db:
        db.add(Role(name="مستخدم نظام", description="موظف في الشركة", is_system=False, is_super_admin=False))
        await db.commit()


async def _department(name: str, code: str, manager: User | None) -> Department:
    async with AsyncSessionLocal() as db:
        department = Department(name=name, code=code, manager_user_id=manager.user_id if manager else None)
        db.add(department)
        await db.commit()
        await db.refresh(department)
        return department


# ---------------------------------------------------------------- وحدات صغيرة


def test_username_from_email_rules() -> None:
    assert username_base_from_email("Ahmed.Ali@wadimakkah.sa") == "ahmed.ali"
    assert username_base_from_email("mohammed-q+hr@x.com") == "mohammed_q"
    assert username_base_from_email("ab@x.com") == "user"
    taken = {"ahmed.ali"}
    assert unique_username("ahmed.ali", taken) == "ahmed.ali2"
    assert unique_username("ahmed.ali", taken) == "ahmed.ali3"


def test_temporary_password_meets_policy() -> None:
    for _ in range(200):
        password = generate_temporary_password()
        assert len(password) == 12 and validate_password_policy(password)


# ---------------------------------------------------------------- النموذج


async def test_template_has_headers_and_role_choices(client: AsyncClient, auth_headers) -> None:
    await _system_user_role()
    response = await client.get(TEMPLATE, headers=auth_headers)
    assert response.status_code == 200
    workbook = load_workbook(io.BytesIO(response.content))
    assert [c.value for c in workbook["المستخدمين"][1]] == TEMPLATE_HEADERS
    roles = [r[0] for r in workbook["القوائم"].iter_rows(min_row=2, values_only=True) if r[0]]
    for label in ("الرئيس التنفيذي", "المكتب التنفيذي", MANAGER, "مستخدم نظام"):
        assert label in roles
    assert "super_admin" not in roles  # المسؤول الأعلى لا يُسند عبر الملف


# ---------------------------------------------------------------- النجاح


async def test_import_creates_users_departments_and_sends_credentials(
    client: AsyncClient, auth_headers, sent
) -> None:
    await _system_user_role()
    await _job_title("محلل بيانات")
    content = _xlsx(
        [
            ["سارة", "محمد", "العتيبي", "Sara.Otaibi@example.com", "إدارة الابتكار", "محلل بيانات", MANAGER],
            ["خالد", "علي", "الحربي", "khalid@example.com", "إدارة الابتكار", None, "مستخدم نظام"],
            [None, None, None, None, None, None, None],  # صف فارغ يُتجاهل
            ["نورة", "سعد", "القحطاني", "noura@example.com", None, None, "الرئيس التنفيذي"],
        ]
    )
    response = await _upload(client, auth_headers, content)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created_count"] == 3 and body["emails_queued"] == 3
    assert body["departments_created"] == [{"name": "إدارة الابتكار", "code": "DEP-001"}]
    by_email = {u["email"]: u for u in body["users"]}
    assert by_email["Sara.Otaibi@example.com"]["username"] == "sara.otaibi"
    assert by_email["Sara.Otaibi@example.com"]["is_department_manager"] is True
    assert by_email["khalid@example.com"]["row"] == 3
    assert "password" not in response.text.lower()  # لا كلمات مرور بالاستجابة

    await _flush_background()
    assert len(sent) == 3
    credentials = {email: (username, password) for email, _, username, password in sent}

    async with AsyncSessionLocal() as db:
        department = (await db.execute(select(Department).where(Department.name == "إدارة الابتكار"))).scalar_one()
        users = {u.email: u for u in (await db.execute(select(User).where(User.deleted_at.is_(None)))).scalars()}
    sara = users["Sara.Otaibi@example.com"]
    assert department.manager_user_id == sara.user_id
    assert users["khalid@example.com"].dep_id == department.dep_id
    assert users["noura@example.com"].dep_id is None
    assert all(users[e].must_change_password for e in credentials)

    # كلمة المرور المؤقتة المرسلة تعمل فعليًا، والحساب يطلب تغييرها
    username, password = credentials["khalid@example.com"]
    login = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True


async def test_username_collision_gets_suffix(client: AsyncClient, auth_headers, super_admin_user, sent) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                first_name="أ", middle_name="ب", last_name="ج", username="ahmed", email="ahmed@old.com",
                password_hash=hash_password("StrongPass1"),
            )
        )
        await db.commit()
    response = await _upload(
        client, auth_headers, _xlsx([["أحمد", "علي", "الزهراني", "ahmed@new.com", None, None, None]])
    )
    assert response.status_code == 201, response.text
    assert response.json()["users"][0]["username"] == "ahmed2"


async def test_existing_department_without_manager_gets_manager(client: AsyncClient, auth_headers, sent) -> None:
    department = await _department("إدارة قائمة", "OLD", None)
    response = await _upload(
        client, auth_headers, _xlsx([["ريم", "خالد", "الشهري", "reem@example.com", "إدارة قائمة", None, MANAGER]])
    )
    assert response.status_code == 201, response.text
    assert response.json()["departments_created"] == []
    async with AsyncSessionLocal() as db:
        refreshed = await db.get(Department, department.dep_id)
        reem = (await db.execute(select(User).where(User.email == "reem@example.com"))).scalar_one()
    assert refreshed.manager_user_id == reem.user_id and reem.dep_id == department.dep_id


# ---------------------------------------------------------------- الأخطاء (الكل أو لا شيء)


async def test_any_invalid_row_creates_nobody(client: AsyncClient, auth_headers, super_admin_user, sent) -> None:
    before = await _user_count()
    content = _xlsx(
        [
            ["سارة", "محمد", "العتيبي", "sara@example.com", None, None, None],  # صالح
            ["", "علي", "الحربي", "not-an-email", None, "مسمى غير موجود", "دور غير موجود"],
            ["نورة", "سعد", "القحطاني", "SARA@example.com", None, None, None],  # مكرر بالملف
            ["فهد", "سعد", "الدوسري", "super_admin_test@example.com", None, None, None],  # موجود بالنظام
        ]
    )
    response = await _upload(client, auth_headers, content)
    assert response.status_code == 400
    detail = response.json()["detail"]
    errors = {(e["row"], e["field"]) for e in detail["errors"]}
    assert (3, "الاسم الأول") in errors
    assert (3, "البريد الإلكتروني") in errors
    assert (3, "المسمى الوظيفي") in errors
    assert (3, "الدور في النظام") in errors
    assert (4, "البريد الإلكتروني") in errors
    assert (5, "البريد الإلكتروني") in errors
    assert "لم يُضف أي مستخدم" in detail["message"]
    await _flush_background()
    assert await _user_count() == before and sent == []


async def test_new_department_requires_exactly_one_manager(client: AsyncClient, auth_headers, sent) -> None:
    no_manager = await _upload(
        client, auth_headers, _xlsx([["خالد", "علي", "الحربي", "k@example.com", "إدارة جديدة", None, None]])
    )
    assert no_manager.status_code == 400
    assert "تحتاج مديرًا" in no_manager.json()["detail"]["errors"][0]["message"]

    two_managers = await _upload(
        client,
        auth_headers,
        _xlsx(
            [
                ["أ", "ب", "ج", "a1@example.com", "إدارة جديدة", None, MANAGER],
                ["د", "ه", "و", "a2@example.com", "إدارة جديدة", None, MANAGER],
            ]
        ),
    )
    assert two_managers.status_code == 400
    assert two_managers.json()["detail"]["errors"][0]["row"] == 3


async def test_existing_department_with_manager_rejects_new_manager(
    client: AsyncClient, auth_headers, super_admin_user, sent
) -> None:
    await _department("إدارة لها مدير", "HASM", super_admin_user)
    response = await _upload(
        client, auth_headers, _xlsx([["أ", "ب", "ج", "m@example.com", "إدارة لها مدير", None, MANAGER]])
    )
    assert response.status_code == 400
    assert "صفحة الإدارات" in response.json()["detail"]["errors"][0]["message"]


async def test_super_admin_role_cannot_be_assigned(client: AsyncClient, auth_headers, sent) -> None:
    response = await _upload(client, auth_headers, _xlsx([["أ", "ب", "ج", "x@example.com", None, None, "super_admin"]]))
    assert response.status_code == 400
    assert response.json()["detail"]["errors"][0]["field"] == "الدور في النظام"


# ---------------------------------------------------------------- حدود الملف


async def test_file_level_errors(client: AsyncClient, auth_headers, sent) -> None:
    wrong_headers = await _upload(client, auth_headers, _xlsx([], headers=["الاسم", "البريد"]))
    assert wrong_headers.status_code == 400 and "أعمدة الملف" in wrong_headers.json()["detail"]

    empty = await _upload(client, auth_headers, _xlsx([]))
    assert empty.status_code == 400 and "لا يحتوي" in empty.json()["detail"]

    not_excel = await _upload(client, auth_headers, b"hello", filename="users.xlsx")
    assert not_excel.status_code == 400

    csv = await _upload(client, auth_headers, b"a,b", filename="users.csv")
    assert csv.status_code == 400

    too_many = _xlsx([["أ", "ب", "ج", f"u{i}@example.com", None, None, None] for i in range(MAX_ROWS + 1)])
    response = await _upload(client, auth_headers, too_many)
    assert response.status_code == 400 and str(MAX_ROWS) in response.json()["detail"]


async def test_first_sheet_used_when_named_differently(client: AsyncClient, auth_headers, sent) -> None:
    response = await _upload(
        client, auth_headers, _xlsx([["أ", "ب", "ج", "s1@example.com", None, None, None]], sheet="Sheet1")
    )
    assert response.status_code == 201, response.text


# ---------------------------------------------------------------- الصلاحيات


async def _login_with_role(
    client: AsyncClient, auth_headers, *, codes: list[str], scopes: dict[str, str], dep_id=None
) -> dict[str, str]:
    role = await client.post(
        "/api/v1/roles",
        json={"name": f"مستورد {uuid.uuid4().hex[:6]}", "permission_codes": codes, "permission_scopes": scopes},
        headers=auth_headers,
    )
    assert role.status_code == 201, role.text
    username = f"importer_{uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                first_name="م", middle_name="س", last_name="ت", username=username, email=f"{username}@example.com",
                password_hash=hash_password("StrongPass1"), role_id=role.json()["role_id"], dep_id=dep_id,
            )
        )
        await db.commit()
    login = await client.post("/api/v1/auth/login", json={"username": username, "password": "StrongPass1"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_without_permission_forbidden(client: AsyncClient, auth_headers, sent) -> None:
    headers = await _login_with_role(client, auth_headers, codes=["users.create"], scopes={})
    assert (await _upload(client, headers, _xlsx([["أ", "ب", "ج", "z@example.com", None, None, None]]))).status_code == 403
    assert (await client.get(TEMPLATE, headers=headers)).status_code == 403


async def test_department_scope_limited_to_own_department(
    client: AsyncClient, auth_headers, super_admin_user, sent
) -> None:
    own = await _department("إدارتي", "MINE", super_admin_user)
    await _department("إدارة أخرى", "OTHR", super_admin_user)
    headers = await _login_with_role(
        client, auth_headers, codes=["users.import", "users.view"], scopes={"users.import": "department"}, dep_id=own.dep_id
    )

    ok = await _upload(client, headers, _xlsx([["أ", "ب", "ج", "own1@example.com", None, None, None]]))
    assert ok.status_code == 201, ok.text
    async with AsyncSessionLocal() as db:
        created = (await db.execute(select(User).where(User.email == "own1@example.com"))).scalar_one()
    assert created.dep_id == own.dep_id  # الفارغ = إدارة المُستورِد

    other = await _upload(client, headers, _xlsx([["أ", "ب", "ج", "o@example.com", "إدارة أخرى", None, None]]))
    assert other.status_code == 400 and "لإدارتك فقط" in other.json()["detail"]["errors"][0]["message"]

    new = await _upload(client, headers, _xlsx([["أ", "ب", "ج", "n@example.com", "إدارة جديدة", None, MANAGER]]))
    assert new.status_code == 400
    assert any("إنشاء إدارات" in e["message"] for e in new.json()["detail"]["errors"])

    # منع تصعيد الصلاحيات: دور "مدير إدارة" يملك صلاحيات لا يملكها المستورِد
    escalate = await _upload(client, headers, _xlsx([["أ", "ب", "ج", "e@example.com", None, None, "الرئيس التنفيذي"]]))
    assert escalate.status_code == 400
    assert "لا تملك صلاحية إسناد" in escalate.json()["detail"]["errors"][0]["message"]
