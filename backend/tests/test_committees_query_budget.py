"""
انتفاخ الاستعلامات لطلبات تشكيل اللجان واللجان المعتمدة (إعادة هيكلة
2026-10-24): عدد استعلامات SQL للقوائم لا يكبر مع عدد العناصر (كانت قائمة
الطلبات 31 استعلامًا على بيانات القياس وتزيد مع كل طلب).
"""

from httpx import AsyncClient

from tests.test_committees import _approve_full_flow, _create_user_with_role, _setup_actors
from tests.test_meetings_query_budget import _count


async def _members(client, auth_headers, roles_by_name, prefix: str, how_many: int) -> list[str]:
    ids = []
    for i in range(how_many):
        _, user_id = await _create_user_with_role(
            client, auth_headers, roles_by_name, username=f"{prefix}{i}", role_name="admin"
        )
        ids.append(user_id)
    return ids


async def _approve_many(client, actors, member_ids: list[str], start: int, how_many: int) -> None:
    for i in range(start, start + how_many):
        await _approve_full_flow(
            client, actors, name=f"لجنة {i}", member_ids=member_ids, chair_id=member_ids[0]
        )


async def test_committee_requests_and_committees_lists_do_not_grow(
    client: AsyncClient, auth_headers, roles_by_name
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    member_ids = await _members(client, auth_headers, roles_by_name, "qbm", 3)
    member_ids.append(actors["member_id"])

    await _approve_many(client, actors, member_ids, 0, 2)
    req_few, req_few_body = await _count(client, "/api/v1/committee-requests", actors["admin_headers"])
    com_few, com_few_body = await _count(client, "/api/v1/committees", actors["admin_headers"])

    await _approve_many(client, actors, member_ids, 2, 5)
    req_many, req_many_body = await _count(client, "/api/v1/committee-requests", actors["admin_headers"])
    com_many, com_many_body = await _count(client, "/api/v1/committees", actors["admin_headers"])

    assert len(req_few_body) == 2 and len(req_many_body) == 7
    assert req_many == req_few, f"requests list grew: {req_few} -> {req_many}"
    assert req_many <= 6, f"committee requests list uses {req_many} SQL statements"
    request = req_many_body[0]
    assert request["committee_id"] and request["requester"]["user_id"] and request["chair"]["user_id"]
    assert len(request["proposed_members"]) == 4 and "job_title" in request["proposed_members"][0]

    assert len(com_many_body) == len(com_few_body) + 5
    assert com_many == com_few, f"committees list grew: {com_few} -> {com_many}"
    assert com_many <= 9, f"committees list uses {com_many} SQL statements"
    committee = com_many_body[0]
    assert len(committee["members"]) == 4 and committee["member_roles"][0]["committee_role"]["name"]
