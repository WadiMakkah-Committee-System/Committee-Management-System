"""
انتفاخ الاستعلامات لوحدة المهام (إعادة هيكلة 2026-10-24): عدد استعلامات
SQL لقائمة المهام وتفاصيلها لا يكبر مع عدد المهام أو طول مسار الإسناد
(كانت قائمة المهام 30 استعلامًا على بيانات القياس).
"""

from httpx import AsyncClient

from tests.test_meetings_query_budget import _count
from tests.test_tasks import _create_approved_committee, _create_task


async def _add_tasks(client: AsyncClient, ctx: dict, how_many: int) -> list[str]:
    ids = []
    for i in range(how_many):
        created = await _create_task(
            client, ctx, assignee_id=ctx["member_ids"][i % 2], title=f"مهمة {i}"
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["task_id"]
        # مسار إسناد أطول من سطر واحد لكل مهمة.
        reassigned = await client.post(
            f"/api/v1/tasks/{task_id}/reassign",
            json={"assignee_user_id": ctx["member_ids"][(i + 1) % 2]},
            headers=ctx["chair_headers"],
        )
        assert reassigned.status_code == 200, reassigned.text
        ids.append(task_id)
    return ids


async def test_tasks_list_query_count_does_not_grow_with_tasks(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="tqbudget")
    headers = ctx["chair_headers"]

    await _add_tasks(client, ctx, 2)
    few, few_body = await _count(client, "/api/v1/tasks", headers)

    await _add_tasks(client, ctx, 6)
    many, many_body = await _count(client, "/api/v1/tasks", headers)

    assert len(few_body) == 2 and len(many_body) == 8
    assert many == few, f"list query count grew with item count: {few} -> {many}"
    assert many <= 7, f"tasks list uses {many} SQL statements"
    item = many_body[0]
    assert item["assignee"]["user_id"] and item["creator"]["user_id"]
    assert len(item["assignment_history"]) == 2
    assert item["assignment_history"][-1]["changer"]["user_id"] == ctx["chair_id"]


async def test_task_detail_and_activity_query_count_is_constant(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name, suffix="tqdetail")
    task_id = (await _add_tasks(client, ctx, 1))[0]

    detail, body = await _count(client, f"/api/v1/tasks/{task_id}", ctx["chair_headers"])
    assert body["assignee"]["user_id"] == ctx["member_ids"][1]
    assert detail <= 7, f"task detail uses {detail} SQL statements"

    activity, entries = await _count(client, f"/api/v1/tasks/{task_id}/activity", ctx["chair_headers"])
    assert len(entries) >= 2
    assert activity <= 9, f"task activity uses {activity} SQL statements"
