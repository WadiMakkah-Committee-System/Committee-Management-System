"""
اختبارات هيكل الإدارات على مستويين + نطاق "إدارته وما تحتها" (department_tree)
— migration 0048، قرار لاما 2026-11-15.

تغطي:
- ربط إدارة تابعة بإدارة أم، وعرض الأم/التوابع بصفحة التفاصيل.
- قواعد الهيكل: لا مستوى ثالث، لا ربط بالنفس، لا تحويل أم لها توابع إلى
  تابعة، لا حذف أم لها توابع، لا ربط بإدارة غير موجودة.
- نطاق department_tree على المستخدمين واللجان، وعدم تغيّر معنى department.
"""

import uuid

from httpx import AsyncClient

from app.models.department import Department
from app.models.user import User
from tests.test_committee_duration_type import _approve, _permanent_payload
from tests.test_committees import _setup_actors
from tests.test_documents import _upload_document
from tests.test_users import _create_custom_role, _create_user_and_login


async def _create_department(
    client: AsyncClient,
    auth_headers: dict[str, str],
    manager_id: uuid.UUID | str,
    *,
    name: str,
    code: str,
    parent_dep_id: str | None = None,
) -> str:
    """ينشئ إدارة (اختياريًا تحت إدارة أم) ويرجع dep_id — يفشل الاختبار لو رُفضت."""
    payload = {"name": name, "code": code, "description": None, "manager_user_id": str(manager_id)}
    if parent_dep_id is not None:
        payload["parent_dep_id"] = parent_dep_id
    response = await client.post("/api/v1/departments", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()["dep_id"]


async def _create_plain_user(
    client: AsyncClient, auth_headers: dict[str, str], *, username: str, dep_id: str | None
) -> str:
    """مستخدم بلا دور بإدارة محددة — يرجع user_id."""
    response = await client.post(
        "/api/v1/users",
        json={
            "first_name": "م",
            "middle_name": "س",
            "last_name": "ت",
            "username": username,
            "email": f"{username}@example.com",
            "password": "StrongPass1",
            "dep_id": dep_id,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["user_id"]


async def _structure(client: AsyncClient, auth_headers, super_admin_user: User) -> dict[str, str]:
    """إدارتان أم، تحت الأولى إدارتان تابعتان، وتحت الثانية واحدة."""
    shared = await _create_department(client, auth_headers, super_admin_user.user_id, name="الخدمات المشتركة", code="SS")
    business = await _create_department(client, auth_headers, super_admin_user.user_id, name="تطوير الأعمال", code="BD")
    hr = await _create_department(
        client, auth_headers, super_admin_user.user_id, name="الموارد البشرية", code="HR", parent_dep_id=shared
    )
    it = await _create_department(
        client, auth_headers, super_admin_user.user_id, name="تقنية المعلومات", code="IT", parent_dep_id=shared
    )
    property_ = await _create_department(
        client, auth_headers, super_admin_user.user_id, name="إدارة الأملاك", code="PM", parent_dep_id=business
    )
    return {"shared": shared, "business": business, "hr": hr, "it": it, "property": property_}


# ============================ الهيكل ============================


async def test_child_department_linked_and_shown_in_details(
    client: AsyncClient, auth_headers, super_admin_user: User
) -> None:
    deps = await _structure(client, auth_headers, super_admin_user)
    await _create_plain_user(client, auth_headers, username="hr_emp", dep_id=deps["hr"])

    listed = await client.get("/api/v1/departments", headers=auth_headers)
    parents = {d["dep_id"]: d["parent_dep_id"] for d in listed.json()}
    assert parents[deps["shared"]] is None
    assert parents[deps["hr"]] == deps["shared"]

    parent_detail = (await client.get(f"/api/v1/departments/{deps['shared']}", headers=auth_headers)).json()
    assert parent_detail["parent"] is None
    children = {c["dep_id"]: c["member_count"] for c in parent_detail["children"]}
    assert set(children) == {deps["hr"], deps["it"]}
    assert children[deps["hr"]] == 1

    child_detail = (await client.get(f"/api/v1/departments/{deps['hr']}", headers=auth_headers)).json()
    assert child_detail["parent"]["dep_id"] == deps["shared"]
    assert child_detail["children"] == []


async def test_third_level_rejected(client: AsyncClient, auth_headers, super_admin_user: User) -> None:
    deps = await _structure(client, auth_headers, super_admin_user)
    response = await client.post(
        "/api/v1/departments",
        json={
            "name": "مستوى ثالث",
            "code": "L3",
            "description": None,
            "manager_user_id": str(super_admin_user.user_id),
            "parent_dep_id": deps["hr"],
        },
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "مستويان" in response.json()["detail"]


async def test_missing_parent_rejected(client: AsyncClient, auth_headers, super_admin_user: User) -> None:
    response = await client.post(
        "/api/v1/departments",
        json={
            "name": "بلا أم",
            "code": "NP",
            "description": None,
            "manager_user_id": str(super_admin_user.user_id),
            "parent_dep_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_update_parent_rules(client: AsyncClient, auth_headers, super_admin_user: User) -> None:
    deps = await _structure(client, auth_headers, super_admin_user)

    # ربط الإدارة بنفسها
    self_link = await client.patch(
        f"/api/v1/departments/{deps['business']}", json={"parent_dep_id": deps["business"]}, headers=auth_headers
    )
    assert self_link.status_code == 400

    # إدارة أم تحتها توابع لا تصير تابعة
    parent_to_child = await client.patch(
        f"/api/v1/departments/{deps['shared']}", json={"parent_dep_id": deps["business"]}, headers=auth_headers
    )
    assert parent_to_child.status_code == 400

    # نقل إدارة تابعة لأم أخرى
    moved = await client.patch(
        f"/api/v1/departments/{deps['it']}", json={"parent_dep_id": deps["business"]}, headers=auth_headers
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["parent_dep_id"] == deps["business"]

    # تعديل بدون الحقل لا يغيّر الأم
    renamed = await client.patch(
        f"/api/v1/departments/{deps['it']}", json={"name": "التقنية"}, headers=auth_headers
    )
    assert renamed.json()["parent_dep_id"] == deps["business"]

    # null صريح = فكّها من الأم
    detached = await client.patch(
        f"/api/v1/departments/{deps['it']}", json={"parent_dep_id": None}, headers=auth_headers
    )
    assert detached.status_code == 200
    assert detached.json()["parent_dep_id"] is None


async def test_delete_parent_with_children_blocked(
    client: AsyncClient, auth_headers, super_admin_user: User
) -> None:
    deps = await _structure(client, auth_headers, super_admin_user)

    blocked = await client.delete(f"/api/v1/departments/{deps['business']}", headers=auth_headers)
    assert blocked.status_code == 409

    child_deleted = await client.delete(f"/api/v1/departments/{deps['property']}", headers=auth_headers)
    assert child_deleted.status_code == 204
    parent_deleted = await client.delete(f"/api/v1/departments/{deps['business']}", headers=auth_headers)
    assert parent_deleted.status_code == 204


# ============================ نطاق department_tree ============================


async def test_role_accepts_department_tree_scope(client: AsyncClient, auth_headers) -> None:
    await _create_custom_role(
        client,
        auth_headers,
        name="tree_role_probe",
        permission_codes=["users.view"],
        permission_scopes={"users.view": "department_tree"},
    )


async def test_users_view_department_tree_scope(
    client: AsyncClient, auth_headers, super_admin_user: User
) -> None:
    """
    مدير الإدارة الأم بنطاق department_tree يشوف موظفي إدارته وكل إداراتها
    التابعة فقط — لا الإدارة الأم الأخرى ولا توابعها. ونطاق department بنفس
    الإدارة الأم يبقى على إدارته وحدها.
    """
    deps = await _structure(client, auth_headers, super_admin_user)
    hr_emp = await _create_plain_user(client, auth_headers, username="tree_hr", dep_id=deps["hr"])
    await _create_plain_user(client, auth_headers, username="tree_it", dep_id=deps["it"])
    other_emp = await _create_plain_user(client, auth_headers, username="tree_prop", dep_id=deps["property"])

    tree_role = await _create_custom_role(
        client,
        auth_headers,
        name="gm_tree",
        permission_codes=["users.view"],
        permission_scopes={"users.view": "department_tree"},
    )
    dept_role = await _create_custom_role(
        client,
        auth_headers,
        name="gm_dept",
        permission_codes=["users.view"],
        permission_scopes={"users.view": "department"},
    )
    gm_headers = await _create_user_and_login(
        client, auth_headers, username="gm_shared", role_id=tree_role, dep_id=deps["shared"]
    )
    dept_headers = await _create_user_and_login(
        client, auth_headers, username="gm_shared_flat", role_id=dept_role, dep_id=deps["shared"]
    )
    child_tree_headers = await _create_user_and_login(
        client, auth_headers, username="hr_head_tree", role_id=tree_role, dep_id=deps["hr"]
    )

    tree_list = {u["username"] for u in (await client.get("/api/v1/users", headers=gm_headers)).json()}
    assert {"tree_hr", "tree_it", "gm_shared", "gm_shared_flat"} <= tree_list
    assert "tree_prop" not in tree_list

    # فلتر dep_id ضمن النطاق يُحترم
    filtered = await client.get("/api/v1/users", params={"dep_id": deps["hr"]}, headers=gm_headers)
    assert {u["username"] for u in filtered.json()} == {"tree_hr", "hr_head_tree"}

    # فلتر dep_id خارج النطاق يُتجاهل (لا يوسّع النطاق)
    outside = await client.get("/api/v1/users", params={"dep_id": deps["property"]}, headers=gm_headers)
    assert "tree_prop" not in {u["username"] for u in outside.json()}

    assert (await client.get(f"/api/v1/users/{hr_emp}", headers=gm_headers)).status_code == 200
    assert (await client.get(f"/api/v1/users/{other_emp}", headers=gm_headers)).status_code == 403

    flat_list = {u["username"] for u in (await client.get("/api/v1/users", headers=dept_headers)).json()}
    assert "tree_hr" not in flat_list
    assert (await client.get(f"/api/v1/users/{hr_emp}", headers=dept_headers)).status_code == 403

    # department_tree لموظف بإدارة تابعة = إدارته فقط (لا يطلع للأم ولا للشقيقة)
    child_list = {u["username"] for u in (await client.get("/api/v1/users", headers=child_tree_headers)).json()}
    assert "tree_it" not in child_list
    assert "gm_shared" not in child_list
    assert "tree_hr" in child_list


async def test_committees_department_tree_scope(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    """لجنة رئيسها من إدارة تابعة تظهر لمدير الإدارة الأم بنطاق department_tree فقط."""
    deps = await _structure(client, auth_headers, super_admin_user)
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    create = await client.post(
        "/api/v1/committee-requests",
        json=_permanent_payload(actors["member_id"], name="لجنة الموارد"),
        headers=actors["admin_headers"],
    )
    assert create.status_code == 201, create.text
    committee_id = await _approve(client, actors, create.json()["request_id"])
    moved = await client.patch(
        f"/api/v1/users/{actors['member_id']}", json={"dep_id": deps["hr"]}, headers=auth_headers
    )
    assert moved.status_code == 200, moved.text

    tree_role = await _create_custom_role(
        client,
        auth_headers,
        name="committees_tree",
        permission_codes=["committees.view"],
        permission_scopes={"committees.view": "department_tree"},
    )
    flat_role = await _create_custom_role(
        client,
        auth_headers,
        name="committees_flat",
        permission_codes=["committees.view"],
        permission_scopes={"committees.view": "department"},
    )
    gm_headers = await _create_user_and_login(
        client, auth_headers, username="cm_gm", role_id=tree_role, dep_id=deps["shared"]
    )
    flat_headers = await _create_user_and_login(
        client, auth_headers, username="cm_flat", role_id=flat_role, dep_id=deps["shared"]
    )
    other_gm_headers = await _create_user_and_login(
        client, auth_headers, username="cm_other_gm", role_id=tree_role, dep_id=deps["business"]
    )

    gm_list = {c["committee_id"] for c in (await client.get("/api/v1/committees", headers=gm_headers)).json()}
    assert committee_id in gm_list
    assert (await client.get(f"/api/v1/committees/{committee_id}", headers=gm_headers)).status_code == 200

    flat_list = {c["committee_id"] for c in (await client.get("/api/v1/committees", headers=flat_headers)).json()}
    assert committee_id not in flat_list
    assert (await client.get(f"/api/v1/committees/{committee_id}", headers=flat_headers)).status_code == 403

    other_list = {
        c["committee_id"] for c in (await client.get("/api/v1/committees", headers=other_gm_headers)).json()
    }
    assert committee_id not in other_list


# ============================ الوثائق عبر الهيكل ============================


async def test_department_documents_visible_across_hierarchy(
    client: AsyncClient, auth_headers, super_admin_user: User
) -> None:
    """
    قرار لاما 2026-11-15: وثيقة مشاركة مع إدارة تصل لإدارتها الأم ولإداراتها
    التابعة بالاتجاهين — لا للإدارة الشقيقة ولا للإدارة الأم الأخرى.
    """
    deps = await _structure(client, auth_headers, super_admin_user)
    viewer_role = await _create_custom_role(
        client,
        auth_headers,
        name="doc_viewer",
        permission_codes=["documents.view"],
        permission_scopes={"documents.view": "department"},
    )

    async def viewer(username: str, dep_key: str) -> dict[str, str]:
        return await _create_user_and_login(
            client, auth_headers, username=username, role_id=viewer_role, dep_id=deps[dep_key]
        )

    gm_headers = await viewer("doc_gm", "shared")
    hr_headers = await viewer("doc_hr", "hr")
    it_headers = await viewer("doc_it", "it")
    other_headers = await viewer("doc_prop", "property")

    to_parent = await _upload_document(client, auth_headers, title="تعميم الخدمات", department_ids=deps["shared"])
    to_child = await _upload_document(client, auth_headers, title="ملف الموارد", department_ids=deps["hr"])
    assert to_parent.status_code == 201, to_parent.text
    parent_doc, child_doc = to_parent.json()["document_id"], to_child.json()["document_id"]

    async def can_see(headers: dict[str, str], document_id: str) -> bool:
        return (await client.get(f"/api/v1/documents/{document_id}", headers=headers)).status_code == 200

    # مشاركة مع الأم ← تصل لكل توابعها
    assert await can_see(gm_headers, parent_doc)
    assert await can_see(hr_headers, parent_doc)
    assert await can_see(it_headers, parent_doc)
    assert not await can_see(other_headers, parent_doc)

    # مشاركة مع تابعة ← تصل لأمها، لا لشقيقتها
    assert await can_see(hr_headers, child_doc)
    assert await can_see(gm_headers, child_doc)
    assert not await can_see(it_headers, child_doc)
    assert not await can_see(other_headers, child_doc)

    listed = {d["document_id"] for d in (await client.get("/api/v1/documents", headers=hr_headers)).json()}
    assert {parent_doc, child_doc} <= listed


# ============================ إسناد الإدارة عند إنشاء/تعديل مستخدم ============================


async def test_user_department_assignment_limited_to_scope(
    client: AsyncClient, auth_headers, super_admin_user: User
) -> None:
    """
    إصلاح ثغرة (طلب لاما 2026-11-15): من يملك users.create/users.update بنطاق
    إدارة لا يقدر يسند مستخدمًا لإدارة خارج نطاقه (ولا بلا إدارة) عبر الـAPI.
    """
    deps = await _structure(client, auth_headers, super_admin_user)
    tree_role = await _create_custom_role(
        client,
        auth_headers,
        name="hr_admin_tree",
        permission_codes=["users.view", "users.create", "users.update"],
        permission_scopes={"users.view": "department_tree", "users.create": "department_tree", "users.update": "department_tree"},
    )
    gm_headers = await _create_user_and_login(
        client, auth_headers, username="assign_gm", role_id=tree_role, dep_id=deps["shared"]
    )

    def body(username: str, dep_id: str | None) -> dict:
        return {
            "first_name": "أ",
            "middle_name": "ب",
            "last_name": "ج",
            "username": username,
            "email": f"{username}@example.com",
            "password": "StrongPass1",
            "dep_id": dep_id,
        }

    inside = await client.post("/api/v1/users", json=body("assign_ok", deps["hr"]), headers=gm_headers)
    assert inside.status_code == 201, inside.text
    outside = await client.post("/api/v1/users", json=body("assign_bad", deps["property"]), headers=gm_headers)
    assert outside.status_code == 403
    no_dep = await client.post("/api/v1/users", json=body("assign_none", None), headers=gm_headers)
    assert no_dep.status_code == 403

    user_id = inside.json()["user_id"]
    move_inside = await client.patch(f"/api/v1/users/{user_id}", json={"dep_id": deps["it"]}, headers=gm_headers)
    assert move_inside.status_code == 200, move_inside.text
    move_outside = await client.patch(
        f"/api/v1/users/{user_id}", json={"dep_id": deps["property"]}, headers=gm_headers
    )
    assert move_outside.status_code == 403

    # super_admin (نطاق all) بلا قيود
    admin_move = await client.patch(
        f"/api/v1/users/{user_id}", json={"dep_id": deps["property"]}, headers=auth_headers
    )
    assert admin_move.status_code == 200


# ============================ وحدة (بدون قاعدة) ============================


def test_department_ids_for_scope_unit() -> None:
    parent_id, child_id = uuid.uuid4(), uuid.uuid4()
    department = Department(dep_id=parent_id, name="أم")
    department.child_dep_ids = [child_id]
    user = User(dep_id=parent_id)
    user.department = department

    assert user.department_ids_for_scope("department") == {parent_id}
    assert user.department_ids_for_scope("department_tree") == {parent_id, child_id}
    assert user.department_ids_for_scope("all") == set()
    assert user.department_ids_for_scope("own") == set()
    assert user.scope_covers_department("department_tree", child_id)
    assert not user.scope_covers_department("department", child_id)
    assert not user.scope_covers_department("department_tree", None)

    no_dep = User(dep_id=None)
    assert no_dep.department_ids_for_scope("department_tree") == set()
