"""
لوحة التحكم (تحسين أداء 2026-10-24): عدد استعلامات ثابت لا يكبر مع عدد
القرارات/المهام، وأرقامها تطابق صفحات الوحدات نفسها (نفس دوال القوائم).
"""

from httpx import AsyncClient

from tests.test_decisions import _create_approved_committee
from tests.test_decisions_query_budget import _add_voted_decisions, _new_voting_decision
from tests.test_meetings_query_budget import _count


async def test_dashboard_query_count_is_constant_and_matches_pages(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    ctx = await _create_approved_committee(
        client, auth_headers, roles_by_name, suffix="dashq", member_count=2
    )
    member = ctx["member_headers_list"][0]
    await _add_voted_decisions(client, ctx, 1)
    await _new_voting_decision(client, ctx, "قرار بانتظار تصويتي")
    few, few_body = await _count(client, "/api/v1/dashboard/summary", member)

    await _add_voted_decisions(client, ctx, 3)
    for i in range(3):
        await _new_voting_decision(client, ctx, f"قرار آخر {i}")
    many, many_body = await _count(client, "/api/v1/dashboard/summary", member)

    assert many == few, f"dashboard query count grew: {few} -> {many}"
    assert many <= 16, f"dashboard uses {many} SQL statements"
    # العضو لم يصوّت على أي قرار → كل القرارات المفتوحة بانتظار صوته.
    assert few_body["pending_votes_count"] == 2 and many_body["pending_votes_count"] == 8
    committees = (await client.get("/api/v1/committees", headers=member)).json()
    assert many_body["committees_count"] == len(committees)
    assert {c["committee_id"] for c in many_body["committees_preview"]} <= {
        c["committee_id"] for c in committees
    }
