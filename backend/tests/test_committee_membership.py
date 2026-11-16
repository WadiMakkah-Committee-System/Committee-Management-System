"""
اختبارات تعديل عضوية اللجنة الدائمة بعد الاعتماد + تمديد الفترة + سجل
التغييرات (migration 0050 — طلب لاما 2026-11-16)، وتقسيم الصلاحيات الجديد.

تغطي:
- إضافة عضو / حذف عضو / تغيير الرئيس / تعيين وإلغاء أمين السر / التمديد،
  وظهور كل تغيير بالسجل بالترتيب.
- اللجنة المؤقتة: تعديل العضوية مرفوض (400)، والتمديد مسموح.
- قواعد العمل: لا حذف للرئيس، لا تكرار عضو، الرئيس الجديد من الأعضاء،
  التمديد لازم بعد النهاية الحالية.
- من لا يملك الصلاحية يُرفض (403).
- الكتالوج يحوي الأكواد الجديدة، والمنح التلقائي حفظ صلاحيات الأدوار الحالية.
"""

from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.role import Permission, Role, RolePermission
from tests.test_committee_duration_type import _approve, _permanent_payload
from tests.test_committees import _create_user_with_role, _setup_actors, _valid_payload


async def _permanent_committee(client: AsyncClient, auth_headers, roles_by_name) -> tuple[dict, str, list[str]]:
    """لجنة دائمة معتمدة: رئيس (member_id) + عضوان. يرجع (actors, committee_id, [m2, m3])."""
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    _, m2 = await _create_user_with_role(client, auth_headers, roles_by_name, username="pm_m2", role_name="admin")
    _, m3 = await _create_user_with_role(client, auth_headers, roles_by_name, username="pm_m3", role_name="admin")
    payload = _permanent_payload(actors["member_id"], name="لجنة الحوكمة الدائمة")
    payload["proposed_member_ids"] = [actors["member_id"], m2, m3]
    create = await client.post("/api/v1/committee-requests", json=payload, headers=actors["admin_headers"])
    assert create.status_code == 201, create.text
    committee_id = await _approve(client, actors, create.json()["request_id"])
    return actors, committee_id, [m2, m3]


def _member_roles(committee: dict) -> dict[str, str]:
    return {m["user"]["user_id"]: m["committee_role"]["committee_role_slug"] for m in committee["member_roles"]}


async def test_permanent_committee_membership_changes_and_history(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors, committee_id, (m2, m3) = await _permanent_committee(client, auth_headers, roles_by_name)
    office = actors["office_headers"]  # المكتب التنفيذي: committees.update ⇒ منح تلقائي للصلاحيات الجديدة
    _, newcomer = await _create_user_with_role(client, auth_headers, roles_by_name, username="pm_new", role_name="admin")

    candidates = await client.get(f"/api/v1/committees/{committee_id}/member-candidates", headers=office)
    assert candidates.status_code == 200, candidates.text
    candidate_ids = {u["user_id"] for u in candidates.json()}
    assert newcomer in candidate_ids and m2 not in candidate_ids

    added = await client.post(
        f"/api/v1/committees/{committee_id}/members",
        json={"user_id": newcomer, "reason": "انضمام ممثل الإدارة"},
        headers=office,
    )
    assert added.status_code == 200, added.text
    assert _member_roles(added.json())[newcomer] == "member"

    duplicate = await client.post(f"/api/v1/committees/{committee_id}/members", json={"user_id": newcomer}, headers=office)
    assert duplicate.status_code == 400

    secretary = await client.put(f"/api/v1/committees/{committee_id}/secretary", json={"user_id": m3}, headers=office)
    assert secretary.status_code == 200, secretary.text
    assert secretary.json()["secretary_user_id"] == m3
    assert _member_roles(secretary.json())[m3] == "secretary"

    chair = await client.put(f"/api/v1/committees/{committee_id}/chair", json={"user_id": m2}, headers=office)
    assert chair.status_code == 200, chair.text
    roles = _member_roles(chair.json())
    assert chair.json()["chair_user_id"] == m2
    assert roles[m2] == "chair" and roles[actors["member_id"]] == "member"

    remove_chair = await client.post(f"/api/v1/committees/{committee_id}/members/{m2}/remove", json={}, headers=office)
    assert remove_chair.status_code == 400

    removed = await client.post(
        f"/api/v1/committees/{committee_id}/members/{m3}/remove", json={"reason": "انتهاء التكليف"}, headers=office
    )
    assert removed.status_code == 200, removed.text
    assert m3 not in _member_roles(removed.json())
    assert removed.json()["secretary_user_id"] is None

    too_short = await client.post(f"/api/v1/committees/{committee_id}/extend", json={"end_date": "2027-01-01"}, headers=office)
    assert too_short.status_code == 400
    extended = await client.post(
        f"/api/v1/committees/{committee_id}/extend", json={"end_date": "2028-09-01", "reason": "تجديد سنوي"}, headers=office
    )
    assert extended.status_code == 200, extended.text
    assert extended.json()["end_date"] == "2028-09-01"

    history = await client.get(f"/api/v1/committees/{committee_id}/changes", headers=office)
    assert history.status_code == 200, history.text
    types = [c["change_type"] for c in history.json()]
    assert types == ["period_extended", "member_removed", "chair_changed", "secretary_changed", "member_added"]
    assert history.json()[0]["details"] == {"previous_end_date": "2027-09-01", "new_end_date": "2028-09-01"}
    assert history.json()[1]["reason"] == "انتهاء التكليف"
    assert history.json()[2]["previous_user"]["user_id"] == actors["member_id"]

    # عضو اللجنة يشوف السجل
    member_view = await client.get(f"/api/v1/committees/{committee_id}/changes", headers=actors["admin_headers"])
    assert member_view.status_code == 200


async def test_membership_changes_forbidden_without_permission(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors, committee_id, (m2, _m3) = await _permanent_committee(client, auth_headers, roles_by_name)
    # الأدمن (مقدّم الطلب) لا يملك committees.members.* ولا committees.extend
    _, outsider = await _create_user_with_role(client, auth_headers, roles_by_name, username="pm_out", role_name="admin")
    admin = actors["admin_headers"]
    assert (await client.post(f"/api/v1/committees/{committee_id}/members", json={"user_id": outsider}, headers=admin)).status_code == 403
    assert (await client.post(f"/api/v1/committees/{committee_id}/members/{m2}/remove", json={}, headers=admin)).status_code == 403
    assert (await client.put(f"/api/v1/committees/{committee_id}/chair", json={"user_id": m2}, headers=admin)).status_code == 403
    assert (await client.post(f"/api/v1/committees/{committee_id}/extend", json={"end_date": "2030-01-01"}, headers=admin)).status_code == 403


async def test_temporary_committee_members_locked_but_extendable(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    _, outsider = await _create_user_with_role(client, auth_headers, roles_by_name, username="tmp_out", role_name="admin")
    create = await client.post(
        "/api/v1/committee-requests", json=_valid_payload(actors["member_id"]), headers=actors["admin_headers"]
    )
    committee_id = await _approve(client, actors, create.json()["request_id"])
    office = actors["office_headers"]

    blocked = await client.post(f"/api/v1/committees/{committee_id}/members", json={"user_id": outsider}, headers=office)
    assert blocked.status_code == 400
    assert "الدائمة" in blocked.json()["detail"]

    extended = await client.post(f"/api/v1/committees/{committee_id}/extend", json={"end_date": "2027-03-01"}, headers=office)
    assert extended.status_code == 200, extended.text


async def test_split_permissions_backfilled_from_source_codes() -> None:
    """كل دور يملك الكود المصدر حصل على الكود الجديد بنفس النطاق (لا تغيّر في السلوك)."""
    pairs = {
        "meetings.extend": "meetings.update",
        "minutes.return": "minutes.approve",
        "minutes.send_signature": "minutes.approve",
        "minutes.review": "minutes.approve",
        "tasks.reassign": "tasks.update",
        "tasks.attachments.manage": "tasks.status.update",
        "decisions.attachments.add": "decisions.create",
        "meetings.attendance.view": "meetings.view",
        "committees.extend": "committees.update",
    }
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Permission.code, RolePermission.role_id, RolePermission.scope)
                .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
                .join(Role, Role.role_id == RolePermission.role_id)
            )
        ).all()
    grants: dict[str, dict] = {}
    for code, role_id, scope in rows:
        grants.setdefault(code, {})[role_id] = scope
    for new_code, source in pairs.items():
        assert new_code in {c for c, *_ in rows} or not grants.get(source), new_code
        for role_id, scope in grants.get(source, {}).items():
            assert grants.get(new_code, {}).get(role_id) == scope, (new_code, role_id)
