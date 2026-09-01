"""
اختبارات وحدة "إدارة الاجتماعات" — Phase 2 (FR-MEET-001 → FR-MEET-005).

تغطي: إنشاء اجتماع من رئيس اللجنة (نجاح)، رفض إنشاء اجتماع من عضو ليس
رئيسًا (403)، عرض الاجتماع لعضو اللجنة، تعديل/حذف اجتماع من رئيس اللجنة،
ورفض حذف الاجتماع من مستخدم خارج اللجنة تمامًا.

بدون Teams/AI — راجعي رأس meeting_service.py للقرار الموثّق.
"""

from httpx import AsyncClient

from app.models.user import User


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
    client: AsyncClient, auth_headers: dict[str, str], roles_by_name: dict[str, str]
) -> dict:
    """
    ينشئ لجنة معتمدة فعليًا (draft → submitted → pending_approval →
    approved) عبر الـAPI، برئيس وعضو إضافي — بنفس أسلوب test_committees.py
    (لا توجد بيانات كتالوج جاهزة للجان، ولا تُستثنى من التنظيف بين
    الاختبارات، فيجب إنشاؤها من الصفر في كل اختبار يحتاجها).
    """
    admin_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="mt_admin", role_name="admin"
    )
    office_headers, _ = await _create_user_with_role(
        client,
        auth_headers,
        roles_by_name,
        username="mt_office",
        role_name="executive_office_manager",
    )
    ceo_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="mt_ceo", role_name="executive_president"
    )
    chair_headers, chair_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="mt_chair", role_name="admin"
    )
    member_headers, member_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="mt_member", role_name="admin"
    )
    outsider_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="mt_outsider", role_name="admin"
    )

    create = await client.post(
        "/api/v1/committee-requests",
        json={
            "committee_name": "لجنة الاجتماعات التجريبية",
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

    await client.post(
        f"/api/v1/committee-requests/{request_id}/submit", headers=admin_headers
    )
    await client.post(
        f"/api/v1/committee-requests/{request_id}/escalate", headers=office_headers
    )
    approve = await client.post(
        f"/api/v1/committee-requests/{request_id}/approve", headers=ceo_headers
    )
    assert approve.status_code == 200, approve.text
    committee_id = approve.json()["committee_id"]

    return {
        "committee_id": committee_id,
        "chair_headers": chair_headers,
        "chair_id": chair_id,
        "member_headers": member_headers,
        "member_id": member_id,
        "outsider_headers": outsider_headers,
    }


async def test_chair_can_create_meeting(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)

    response = await client.post(
        "/api/v1/meetings",
        json={
            "committee_id": ctx["committee_id"],
            "title": "الاجتماع الأول",
            "description": "وصف",
            "meeting_type": "عادي",
            "scheduled_at": "2026-09-15T10:00:00Z",
            "participant_ids": [ctx["chair_id"], ctx["member_id"]],
            "agenda_items": [{"title": "بند 1", "sort_order": 0}],
        },
        headers=ctx["chair_headers"],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "الاجتماع الأول"
    assert body["status"] == "upcoming"
    assert len(body["participants"]) == 2
    assert len(body["agenda_items"]) == 1


async def test_non_chair_member_cannot_create_meeting(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)

    response = await client.post(
        "/api/v1/meetings",
        json={
            "committee_id": ctx["committee_id"],
            "title": "محاولة غير مصرح بها",
            "scheduled_at": "2026-09-15T10:00:00Z",
            "participant_ids": [ctx["member_id"]],
        },
        headers=ctx["member_headers"],
    )
    assert response.status_code == 403, response.text


async def test_member_can_view_but_not_delete_meeting(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)

    create = await client.post(
        "/api/v1/meetings",
        json={
            "committee_id": ctx["committee_id"],
            "title": "اجتماع للعرض",
            "scheduled_at": "2026-09-20T09:00:00Z",
            "participant_ids": [ctx["chair_id"], ctx["member_id"]],
        },
        headers=ctx["chair_headers"],
    )
    assert create.status_code == 201, create.text
    meeting_id = create.json()["meeting_id"]

    view = await client.get(f"/api/v1/meetings/{meeting_id}", headers=ctx["member_headers"])
    assert view.status_code == 200, view.text

    delete_attempt = await client.delete(
        f"/api/v1/meetings/{meeting_id}", headers=ctx["member_headers"]
    )
    assert delete_attempt.status_code == 403


async def test_outsider_cannot_view_meeting(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)

    create = await client.post(
        "/api/v1/meetings",
        json={
            "committee_id": ctx["committee_id"],
            "title": "اجتماع خاص",
            "scheduled_at": "2026-09-22T09:00:00Z",
            "participant_ids": [ctx["chair_id"]],
        },
        headers=ctx["chair_headers"],
    )
    assert create.status_code == 201, create.text
    meeting_id = create.json()["meeting_id"]

    view = await client.get(f"/api/v1/meetings/{meeting_id}", headers=ctx["outsider_headers"])
    assert view.status_code == 403


async def test_chair_can_update_and_delete_meeting(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)

    create = await client.post(
        "/api/v1/meetings",
        json={
            "committee_id": ctx["committee_id"],
            "title": "عنوان قديم",
            "scheduled_at": "2026-09-25T09:00:00Z",
            "participant_ids": [ctx["chair_id"]],
        },
        headers=ctx["chair_headers"],
    )
    meeting_id = create.json()["meeting_id"]

    update = await client.patch(
        f"/api/v1/meetings/{meeting_id}",
        json={"title": "عنوان جديد"},
        headers=ctx["chair_headers"],
    )
    assert update.status_code == 200, update.text
    assert update.json()["title"] == "عنوان جديد"

    delete = await client.delete(f"/api/v1/meetings/{meeting_id}", headers=ctx["chair_headers"])
    assert delete.status_code == 204

    get_after_delete = await client.get(
        f"/api/v1/meetings/{meeting_id}", headers=ctx["chair_headers"]
    )
    assert get_after_delete.status_code == 404


async def test_agenda_item_crud_by_chair(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)

    create = await client.post(
        "/api/v1/meetings",
        json={
            "committee_id": ctx["committee_id"],
            "title": "اجتماع بجدول أعمال",
            "scheduled_at": "2026-09-28T09:00:00Z",
            "participant_ids": [ctx["chair_id"]],
        },
        headers=ctx["chair_headers"],
    )
    meeting_id = create.json()["meeting_id"]

    add_item = await client.post(
        f"/api/v1/meetings/{meeting_id}/agenda-items",
        json={"title": "بند جديد", "sort_order": 1},
        headers=ctx["chair_headers"],
    )
    assert add_item.status_code == 201, add_item.text
    agenda_item_id = add_item.json()["agenda_item_id"]

    update_item = await client.patch(
        f"/api/v1/meetings/agenda-items/{agenda_item_id}",
        json={"title": "بند معدَّل"},
        headers=ctx["chair_headers"],
    )
    assert update_item.status_code == 200, update_item.text
    assert update_item.json()["title"] == "بند معدَّل"

    delete_item = await client.delete(
        f"/api/v1/meetings/agenda-items/{agenda_item_id}", headers=ctx["chair_headers"]
    )
    assert delete_item.status_code == 204
