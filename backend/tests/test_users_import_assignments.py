"""
الهدف:
اختبارات تعدد الإدارات (migration 0052 — قرار لاما 2026-11-22): مستخدم في
أكثر من إدارة بدور مختلف في كل إدارة.

تغطي:
- رفع الملف بالنموذج الجديد (صف لكل تعيين): الصفوف بنفس البريد = مستخدم
  واحد، إنشاء الإدارة الجديدة تحت أمّها، المعاينة بلا كتابة، وقواعد الأخطاء.
- النطاق: الدور الحالي يغطي إداراته هو فقط (معاذ كأدمن لا يدير مكتب الرئيس).
- إنشاء/تعديل مستخدم بالتعيينات عبر الـAPI، وحفظ تعيينات خارج نطاق المنفّذ.
"""

import io
import uuid

import pytest
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.department import Department
from app.models.user import User
from app.models.user_department_role import UserDepartmentRole
from app.models.user_role import UserRole
from app.services import notification_service
from app.services.user_import_service import TEMPLATE_HEADERS
from tests.test_users import _create_custom_role

IMPORT = "/api/v1/users/import"
PREVIEW = "/api/v1/users/import/preview"
MANAGER = "مدير إدارة (أدمن)"


def _xlsx(rows: list[list[str | None]]) -> bytes:
    workbook = Workbook()
    ws = workbook.active
    ws.title = "المستخدمين"
    ws.append(TEMPLATE_HEADERS)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def _post(client: AsyncClient, url: str, headers: dict, content: bytes):
    return await client.post(
        url,
        files={"file": ("users.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    captured: list[tuple] = []

    async def fake_notify(accounts, *, login_url):
        captured.extend(accounts)

    monkeypatch.setattr(notification_service, "notify_imported_users_credentials", fake_notify)
    return captured


async def _department(name: str, code: str, *, parent: Department | None = None) -> Department:
    async with AsyncSessionLocal() as db:
        department = Department(name=name, code=code, parent_dep_id=parent.dep_id if parent else None)
        db.add(department)
        await db.commit()
        await db.refresh(department)
        return department


async def _org() -> dict[str, Department]:
    """مكتب الرئيس + القانونية + الخدمات المشتركة (أم) وتحتها الموارد البشرية."""
    office = await _department("مكتب الرئيس التنفيذي", "CEO")
    legal = await _department("الإدارة القانونية", "LEG")
    shared = await _department("إدارة الخدمات المشتركة", "SS")
    hr = await _department("الموارد البشرية", "HR", parent=shared)
    return {"office": office, "legal": legal, "shared": shared, "hr": hr}


def _moath_rows(admin_role: str, office_role: str) -> list[list[str | None]]:
    base = ["معاذ", "محمد", "العتيبي", "moath@example.com", "نائب الرئيس التنفيذي"]
    return [
        [*base, None, "مكتب الرئيس التنفيذي", office_role, "نعم"],
        [*base, None, "الإدارة القانونية", admin_role, None],
        [*base, None, "إدارة الخدمات المشتركة", admin_role, None],
    ]


async def _scoped_role(client, auth_headers, name: str, scope: str) -> str:
    return await _create_custom_role(
        client,
        auth_headers,
        name=name,
        permission_codes=["users.view", "users.update"],
        permission_scopes={"users.view": scope, "users.update": scope},
    )


async def _assignments(email: str) -> tuple[User, set[tuple[uuid.UUID, uuid.UUID]], set[uuid.UUID]]:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        rows = (
            await db.execute(
                select(UserDepartmentRole.role_id, UserDepartmentRole.dep_id).where(
                    UserDepartmentRole.user_id == user.user_id
                )
            )
        ).all()
        roles = set((await db.execute(select(UserRole.role_id).where(UserRole.user_id == user.user_id))).scalars())
        return user, {(r.role_id, r.dep_id) for r in rows}, roles


# ---------------------------------------------------------------- رفع الملف


async def test_same_email_rows_create_one_user_with_assignments(
    client: AsyncClient, auth_headers, super_admin_user, sent
) -> None:
    org = await _org()
    admin = await _scoped_role(client, auth_headers, "أدمن تجريبي", "department_tree")
    office = await _scoped_role(client, auth_headers, "مكتب تنفيذي تجريبي", "department")

    preview = await _post(client, PREVIEW, auth_headers, _xlsx(_moath_rows("أدمن تجريبي", "مكتب تنفيذي تجريبي")))
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["users_count"] == 1 and plan["assignments_count"] == 3
    assert plan["users"][0]["primary_department"] == "مكتب الرئيس التنفيذي"
    async with AsyncSessionLocal() as db:
        assert (await db.execute(select(User).where(User.email == "moath@example.com"))).scalar_one_or_none() is None

    response = await _post(client, IMPORT, auth_headers, _xlsx(_moath_rows("أدمن تجريبي", "مكتب تنفيذي تجريبي")))
    assert response.status_code == 201, response.text
    assert response.json()["created_count"] == 1
    assert response.json()["assignments_count"] == 3

    user, rows, roles = await _assignments("moath@example.com")
    assert user.dep_id == org["office"].dep_id
    # الدور الحالي عند أول دخول = دور صف الإدارة الأساسية.
    assert str(user.role_id) == office
    assert roles == {uuid.UUID(admin), uuid.UUID(office)}
    assert rows == {
        (uuid.UUID(office), org["office"].dep_id),
        (uuid.UUID(admin), org["legal"].dep_id),
        (uuid.UUID(admin), org["shared"].dep_id),
    }
    from tests.test_users_import import _flush_background

    await _flush_background()
    assert len(sent) == 1  # بريد ترحيب واحد للشخص، مو ثلاثة


async def test_active_role_scope_covers_only_its_departments(
    client: AsyncClient, auth_headers, super_admin_user, sent
) -> None:
    """معاذ كأدمن (department_tree): القانونية + الخدمات المشتركة وتوابعها، وليس مكتب الرئيس."""
    org = await _org()
    admin = await _scoped_role(client, auth_headers, "أدمن تجريبي", "department_tree")
    await _scoped_role(client, auth_headers, "مكتب تنفيذي تجريبي", "department")
    rows = _moath_rows("أدمن تجريبي", "مكتب تنفيذي تجريبي")
    staff = [
        ["سارة", "أ", "ب", "sara@example.com", None, "إدارة الخدمات المشتركة", "الموارد البشرية", None, None],
        ["ريم", "أ", "ب", "reem@example.com", None, None, "مكتب الرئيس التنفيذي", None, None],
        ["هند", "أ", "ب", "hind@example.com", None, None, "الإدارة القانونية", None, None],
    ]
    assert (await _post(client, IMPORT, auth_headers, _xlsx(rows + staff))).status_code == 201

    login = await client.post("/api/v1/auth/login", json={"username": "moath", "password": "Wa123456"})
    assert login.status_code == 200, login.text
    moath = {"Authorization": f"Bearer {login.json()['access_token']}"}
    switched = await client.post("/api/v1/users/me/active-role", json={"role_id": admin}, headers=moath)
    assert switched.status_code == 200, switched.text

    listed = {u["email"] for u in (await client.get("/api/v1/users", headers=moath)).json()}
    assert {"sara@example.com", "hind@example.com"} <= listed
    assert "reem@example.com" not in listed

    reem = (await client.get("/api/v1/users", headers=auth_headers)).json()
    reem_id = next(u["user_id"] for u in reem if u["email"] == "reem@example.com")
    assert (await client.get(f"/api/v1/users/{reem_id}", headers=moath)).status_code == 403
    assert org["hr"].parent_dep_id == org["shared"].dep_id


async def test_new_department_created_under_parent(client: AsyncClient, auth_headers, super_admin_user, sent) -> None:
    org = await _org()
    content = _xlsx(
        [
            ["خالد", "أ", "ب", "khaled@example.com", None, "إدارة الخدمات المشتركة", "المشتريات", MANAGER, None],
            ["نوف", "أ", "ب", "nouf@example.com", None, "إدارة الخدمات المشتركة", "المشتريات", None, None],
        ]
    )
    preview = await _post(client, PREVIEW, auth_headers, content)
    assert preview.json()["departments_to_create"] == [
        {"name": "المشتريات", "parent_name": "إدارة الخدمات المشتركة"}
    ]
    response = await _post(client, IMPORT, auth_headers, content)
    assert response.status_code == 201, response.text
    assert response.json()["departments_created"][0]["parent_name"] == "إدارة الخدمات المشتركة"
    async with AsyncSessionLocal() as db:
        purchasing = (await db.execute(select(Department).where(Department.name == "المشتريات"))).scalar_one()
        khaled = (await db.execute(select(User).where(User.email == "khaled@example.com"))).scalar_one()
        nouf = (await db.execute(select(User).where(User.email == "nouf@example.com"))).scalar_one()
    assert purchasing.parent_dep_id == org["shared"].dep_id
    assert purchasing.manager_user_id == khaled.user_id
    assert nouf.dep_id == purchasing.dep_id


async def test_assignment_rules_errors(client: AsyncClient, auth_headers, super_admin_user, sent) -> None:
    await _org()
    await _scoped_role(client, auth_headers, "أدمن تجريبي", "department")
    admin = "أدمن تجريبي"
    content = _xlsx(
        [
            # 2-3: نفس البريد باسم مختلف
            ["أحمد", "أ", "ب", "ahmed@example.com", None, None, "الإدارة القانونية", admin, None],
            ["أحمد", "س", "ب", "ahmed@example.com", None, None, "مكتب الرئيس التنفيذي", admin, None],
            # 4-5: «نعم» مرتين
            ["منى", "أ", "ب", "mona@example.com", None, None, "الإدارة القانونية", admin, "نعم"],
            ["منى", "أ", "ب", "mona@example.com", None, None, "مكتب الرئيس التنفيذي", admin, "نعم"],
            # 6: إدارة أم غير موجودة
            ["علي", "أ", "ب", "ali@example.com", None, "إدارة غير موجودة", "الإدارة القانونية", admin, None],
            # 7: الأم المكتوبة إدارة تابعة (مستوى ثالث)
            ["لينا", "أ", "ب", "lina@example.com", None, "الموارد البشرية", "التوظيف", MANAGER, None],
            # 8: إدارة موجودة بأم غير أمها الفعلية
            ["رنا", "أ", "ب", "rana@example.com", None, "إدارة الخدمات المشتركة", "الإدارة القانونية", admin, None],
            # 9-10: نفس الإدارة والدور مكررين للشخص
            ["سلمى", "أ", "ب", "salma@example.com", None, None, "الإدارة القانونية", admin, None],
            ["سلمى", "أ", "ب", "salma@example.com", None, None, "الإدارة القانونية", admin, None],
            # 11-12: شخص بصفين وصف بلا دور
            ["دانة", "أ", "ب", "dana@example.com", None, None, "الإدارة القانونية", admin, None],
            ["دانة", "أ", "ب", "dana@example.com", None, None, "مكتب الرئيس التنفيذي", None, None],
            # 13: قيمة غير «نعم» بعمود الإدارة الأساسية
            ["هيا", "أ", "ب", "haya@example.com", None, None, "الإدارة القانونية", admin, "ايه"],
        ]
    )
    response = await _post(client, PREVIEW, auth_headers, content)
    assert response.status_code == 400
    errors = {(e["row"], e["field"]) for e in response.json()["detail"]["errors"]}
    assert (3, "الاسم الأول") in errors
    assert (5, "الإدارة الأساسية") in errors
    assert (6, "الإدارة الأم") in errors
    assert (7, "الإدارة الأم") in errors
    assert (8, "الإدارة الأم") in errors
    assert (10, "الدور في الإدارة") in errors
    assert (12, "الدور في الإدارة") in errors
    assert (13, "الإدارة الأساسية") in errors


async def test_new_department_with_two_parents_rejected(client: AsyncClient, auth_headers, super_admin_user, sent) -> None:
    await _org()
    await _department("تطوير الأعمال", "BD")
    content = _xlsx(
        [
            ["خالد", "أ", "ب", "khaled@example.com", None, "إدارة الخدمات المشتركة", "المشتريات", MANAGER, None],
            ["نوف", "أ", "ب", "nouf@example.com", None, "تطوير الأعمال", "المشتريات", None, None],
        ]
    )
    response = await _post(client, IMPORT, auth_headers, content)
    assert response.status_code == 400
    assert (3, "الإدارة الأم") in {(e["row"], e["field"]) for e in response.json()["detail"]["errors"]}


# ---------------------------------------------------------------- الـAPI


async def _create_with_assignments(client, auth_headers, assignments, *, username: str, dep_id=None):
    payload = {
        "first_name": "م",
        "middle_name": "س",
        "last_name": "ت",
        "username": username,
        "email": f"{username}@example.com",
        "password": "StrongPass1",
        "assignments": assignments,
    }
    if dep_id:
        payload["dep_id"] = dep_id
    return await client.post("/api/v1/users", json=payload, headers=auth_headers)


async def test_api_create_and_update_with_assignments(client: AsyncClient, auth_headers, super_admin_user) -> None:
    org = await _org()
    admin = await _scoped_role(client, auth_headers, "أدمن تجريبي", "department")
    office = await _scoped_role(client, auth_headers, "مكتب تنفيذي تجريبي", "department")
    created = await _create_with_assignments(
        client,
        auth_headers,
        [
            {"role_id": office, "dep_id": str(org["office"].dep_id)},
            {"role_id": admin, "dep_id": str(org["legal"].dep_id)},
        ],
        username="moath2",
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["dep_id"] == str(org["office"].dep_id)
    assert body["role"]["role_id"] == office
    assert {(a["department"]["dep_id"], a["role"]["role_id"]) for a in body["assignments"]} == {
        (str(org["office"].dep_id), office),
        (str(org["legal"].dep_id), admin),
    }

    updated = await client.patch(
        f"/api/v1/users/{body['user_id']}",
        json={"assignments": [{"role_id": admin, "dep_id": str(org["shared"].dep_id)}]},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    out = updated.json()
    # الإدارة الأساسية لم تعد من إداراته ← أول إدارة بالتعيينات، والدور الحالي يتبع.
    assert out["dep_id"] == str(org["shared"].dep_id)
    assert out["role"]["role_id"] == admin
    assert [a["department"]["name"] for a in out["assignments"]] == ["إدارة الخدمات المشتركة"]


async def test_scoped_admin_keeps_assignments_outside_scope(
    client: AsyncClient, auth_headers, super_admin_user
) -> None:
    """مدير القانونية يعدّل تعيينات معاذ بالقانونية فقط — دوره بمكتب الرئيس يبقى كما هو."""
    org = await _org()
    admin = await _scoped_role(client, auth_headers, "أدمن تجريبي", "department")
    office = await _scoped_role(client, auth_headers, "مكتب تنفيذي تجريبي", "department")
    other = await _scoped_role(client, auth_headers, "دور ثالث", "department")
    moath = (
        await _create_with_assignments(
            client,
            auth_headers,
            [
                {"role_id": office, "dep_id": str(org["office"].dep_id)},
                {"role_id": admin, "dep_id": str(org["legal"].dep_id)},
            ],
            username="moath3",
        )
    ).json()
    legal_admin = await _create_with_assignments(
        client, auth_headers, [{"role_id": admin, "dep_id": str(org["legal"].dep_id)}], username="legal_admin"
    )
    assert legal_admin.status_code == 201
    login = await client.post("/api/v1/auth/login", json={"username": "legal_admin", "password": "StrongPass1"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # يرى معاذ (عضو بالقانونية) ويقدر يعدّل تعيينه فيها.
    response = await client.patch(
        f"/api/v1/users/{moath['user_id']}",
        json={"assignments": [{"role_id": other, "dep_id": str(org["legal"].dep_id)}]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    pairs = {(a["department"]["dep_id"], a["role"]["role_id"]) for a in response.json()["assignments"]}
    assert pairs == {(str(org["office"].dep_id), office), (str(org["legal"].dep_id), other)}

    # ولا يقدر يضيف له إدارة خارج نطاقه.
    outside = await client.patch(
        f"/api/v1/users/{moath['user_id']}",
        json={"assignments": [{"role_id": admin, "dep_id": str(org["hr"].dep_id)}]},
        headers=headers,
    )
    assert outside.status_code == 403


async def test_department_detail_lists_multi_department_members(
    client: AsyncClient, auth_headers, super_admin_user
) -> None:
    org = await _org()
    admin = await _scoped_role(client, auth_headers, "أدمن تجريبي", "department")
    office = await _scoped_role(client, auth_headers, "مكتب تنفيذي تجريبي", "department")
    created = await _create_with_assignments(
        client,
        auth_headers,
        [
            {"role_id": office, "dep_id": str(org["office"].dep_id)},
            {"role_id": admin, "dep_id": str(org["legal"].dep_id)},
        ],
        username="moath4",
    )
    user_id = created.json()["user_id"]
    for dep in ("office", "legal"):
        detail = (await client.get(f"/api/v1/departments/{org[dep].dep_id}", headers=auth_headers)).json()
        assert user_id in {m["user_id"] for m in detail["members"]}
    filtered = await client.get(f"/api/v1/users?dep_id={org['legal'].dep_id}", headers=auth_headers)
    assert user_id in {u["user_id"] for u in filtered.json()}
