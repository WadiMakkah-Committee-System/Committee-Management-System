"""
اختبارات وحدة "لوحة التحكم" (GET /dashboard/summary).

مبدأ الاختبار: **لا نعيد اختبار منطق الصلاحيات/النطاق لكل وحدة هنا** —
ذاك مغطّى بالكامل بملفات test_meetings.py وtest_decisions.py وtest_tasks.py
وtest_committees.py الخاصة بكل وحدة. الهدف هنا فقط التأكد من أن التجميع
نفسه صحيح: الأعداد والمعاينات تعكس فعليًا ما تُرجعه كل خدمة أصلية، ومن
يملك بيانات (لجنة/اجتماع/قرار بانتظار تصويته/مهمة مفتوحة) يشوفها بلوحة
تحكمه، ومن لا يملك شيئًا يشوف لوحة فارغة (أصفار)، بلا أي استثناء أو خطأ.
"""

from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.role import Permission, Role, RolePermission
from app.models.user import User


async def _grant_committee_role_permissions(codes: list[str], *, slug: str) -> None:
    """Idempotent — راجعي شرح مماثل بـtest_decisions.py."""
    async with AsyncSessionLocal() as db:
        role = (
            await db.execute(select(Role).where(Role.committee_role_slug == slug))
        ).scalar_one()
        perms = (
            await db.execute(select(Permission).where(Permission.code.in_(codes)))
        ).scalars().all()
        assert len(perms) == len(codes), f"بعض الأكواد غير موجودة بالكتالوج: {codes}"

        existing = (
            await db.execute(
                select(RolePermission.permission_id).where(RolePermission.role_id == role.role_id)
            )
        ).scalars().all()
        existing_ids = set(existing)

        for p in perms:
            if p.permission_id in existing_ids:
                continue
            db.add(RolePermission(role_id=role.role_id, permission_id=p.permission_id, scope="all"))
        await db.commit()


async def _create_user_with_role(
    client: AsyncClient,
    auth_headers: dict[str, str],
    roles_by_name: dict[str, str],
    *,
    username: str,
    role_name: str | None,
) -> tuple[dict[str, str], str]:
    create = await client.post(
        "/api/v1/users",
        json={
            "first_name": "أ",
            "middle_name": "ب",
            "last_name": "ج",
            "username": username,
            "email": f"{username}@example.com",
            "password": "StrongPass1",
            "role_id": roles_by_name[role_name] if role_name else None,
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
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user_id


async def _create_approved_committee(
    client: AsyncClient, auth_headers: dict[str, str], roles_by_name: dict[str, str], *, suffix: str
) -> dict:
    admin_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username=f"db_admin_{suffix}", role_name="admin"
    )
    office_headers, _ = await _create_user_with_role(
        client,
        auth_headers,
        roles_by_name,
        username=f"db_office_{suffix}",
        role_name="executive_office_manager",
    )
    ceo_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username=f"db_ceo_{suffix}", role_name="executive_president"
    )
    chair_headers, chair_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username=f"db_chair_{suffix}", role_name="admin"
    )
    member_headers, member_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username=f"db_member_{suffix}", role_name="admin"
    )

    create = await client.post(
        "/api/v1/committee-requests",
        json={
            "committee_name": f"لجنة لوحة التحكم التجريبية {suffix}",
            "statement": "بيان",
            "start_date": "2026-09-01",
            "end_date": "2026-12-01",
            "proposed_member_ids": [chair_id, member_id],
            "chair_user_id": chair_id,
        },
        headers=admin_headers,
    )
    assert create.status_code == 201, create.text
    request_id = create.json()["request_id"]

    await client.post(f"/api/v1/committee-requests/{request_id}/submit", headers=admin_headers)
    await client.post(f"/api/v1/committee-requests/{request_id}/escalate", headers=office_headers)
    approve = await client.post(
        f"/api/v1/committee-requests/{request_id}/approve", headers=ceo_headers
    )
    assert approve.status_code == 200, approve.text
    committee_id = approve.json()["committee_id"]

    await _grant_committee_role_permissions(
        [
            "meetings.schedule",
            "meetings.view",
            "decisions.create",
            "decisions.view",
            "decisions.update",
            "decisions.vote.open",
            "decisions.vote.cast",
            "decisions.vote.view_result",
            "decisions.approve",
            "tasks.create",
            "tasks.view",
            "tasks.view_details",
        ],
        slug="chair",
    )
    await _grant_committee_role_permissions(
        ["decisions.view", "decisions.vote.cast", "tasks.view"], slug="member"
    )

    return {
        "committee_id": committee_id,
        "chair_headers": chair_headers,
        "chair_id": chair_id,
        "member_headers": member_headers,
        "member_id": member_id,
    }


async def test_dashboard_reflects_chair_pending_vote_and_open_task(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="main")

    # لجنة واحدة على الأقل — رئيسة اللجنة.
    baseline = await client.get("/api/v1/dashboard/summary", headers=ctx["chair_headers"])
    assert baseline.status_code == 200, baseline.text
    assert baseline.json()["committees_count"] >= 1
    committee_ids_preview = {c["committee_id"] for c in baseline.json()["committees_preview"]}
    assert ctx["committee_id"] in committee_ids_preview

    # قرار خاضع للتصويت، مطروح فعليًا، الرئيسة لم تصوّت عليه بعد.
    create_decision = await client.post(
        "/api/v1/decisions",
        json={
            "committee_id": ctx["committee_id"],
            "title": "قرار بانتظار تصويت الرئيسة",
            "classification": "voting",
            "start_date": "2026-09-10",
            "end_date": "2026-10-10",
        },
        headers=ctx["chair_headers"],
    )
    assert create_decision.status_code == 201, create_decision.text
    decision_id = create_decision.json()["decision_id"]
    open_vote = await client.post(
        f"/api/v1/decisions/{decision_id}/open-voting",
        json={"options": [{"label": "موافق", "is_approving": True}, {"label": "غير موافق", "is_approving": False}]},
        headers=ctx["chair_headers"],
    )
    assert open_vote.status_code == 200, open_vote.text

    # مهمة مفتوحة (todo) مسندة للرئيسة نفسها.
    create_task = await client.post(
        "/api/v1/tasks",
        json={
            "committee_id": ctx["committee_id"],
            "title": "مهمة مفتوحة للرئيسة",
            "start_date": "2026-09-10",
            "end_date": "2026-10-10",
            "assignee_user_id": ctx["chair_id"],
        },
        headers=ctx["chair_headers"],
    )
    assert create_task.status_code == 201, create_task.text

    summary = await client.get("/api/v1/dashboard/summary", headers=ctx["chair_headers"])
    assert summary.status_code == 200, summary.text
    body = summary.json()

    assert body["pending_votes_count"] >= 1
    pending_titles = {d["title"] for d in body["pending_votes_preview"]}
    assert "قرار بانتظار تصويت الرئيسة" in pending_titles

    assert body["open_tasks_count"] >= 1
    open_task_titles = {t["title"] for t in body["open_tasks_preview"]}
    assert "مهمة مفتوحة للرئيسة" in open_task_titles

    # بعد ما تصوّت الرئيسة: القرار ما عاد "بانتظار تصويتها".
    approve_option_id = next(
        o["option_id"] for o in open_vote.json()["vote_options"] if o["label"] == "موافق"
    )
    await client.post(
        f"/api/v1/decisions/{decision_id}/vote",
        json={"option_id": approve_option_id},
        headers=ctx["chair_headers"],
    )
    summary_after_vote = await client.get(
        "/api/v1/dashboard/summary", headers=ctx["chair_headers"]
    )
    after_titles = {d["title"] for d in summary_after_vote.json()["pending_votes_preview"]}
    assert "قرار بانتظار تصويت الرئيسة" not in after_titles


async def test_dashboard_empty_for_unrelated_user(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    """مستخدم ما عنده أي علاقة بأي لجنة → لوحة تحكم فارغة (أصفار)، بلا أي خطأ."""
    outsider_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="db_outsider", role_name="admin"
    )

    response = await client.get("/api/v1/dashboard/summary", headers=outsider_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["committees_count"] == 0
    assert body["upcoming_meetings_count"] == 0
    assert body["pending_votes_count"] == 0
    assert body["open_tasks_count"] == 0
