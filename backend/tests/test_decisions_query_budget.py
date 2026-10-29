"""
اختبارات وحدة القرارات بعد إعادة الهيكلة (2026-10-24):

1. انتفاخ الاستعلامات: عدد استعلامات SQL لقائمة القرارات لا يكبر مع عدد
   القرارات (كانت 47 استعلامًا على بيانات القياس، ويزيد مع كل قرار).
2. فقدان بيانات: تحرير الأصوات لمن لا يملك decisions.vote.view_result كان
   يحذف أصوات بقية الأعضاء فعليًا من القاعدة (delete-orphan) — راجعي
   docstring decision_service.access._redact_votes_if_unauthorized.
"""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import delete, func, select, update

from app.db.session import AsyncSessionLocal
from app.models.decision import Decision, DecisionVote
from app.models.role import Permission, Role, RolePermission
from tests.test_decisions import _create_approved_committee
from tests.test_meetings_query_budget import _QueryCounter, _count, _drain_background_tasks


async def _new_voting_decision(client: AsyncClient, ctx: dict, title: str) -> tuple[str, str]:
    created = await client.post(
        "/api/v1/decisions",
        json={
            "committee_id": ctx["committee_id"],
            "title": title,
            "classification": "voting",
            "start_date": "2026-11-01",
            "end_date": "2026-11-30",
        },
        headers=ctx["chair_headers"],
    )
    assert created.status_code == 201, created.text
    decision_id = created.json()["decision_id"]
    opened = await client.post(
        f"/api/v1/decisions/{decision_id}/open-voting",
        json={"options": [{"label": "موافق", "is_approving": True}, {"label": "غير موافق"}]},
        headers=ctx["chair_headers"],
    )
    assert opened.status_code == 200, opened.text
    return decision_id, opened.json()["vote_options"][0]["option_id"]


async def _add_voted_decisions(client: AsyncClient, ctx: dict, how_many: int) -> None:
    for i in range(how_many):
        decision_id, option_id = await _new_voting_decision(client, ctx, f"قرار {i}")
        vote = await client.post(
            f"/api/v1/decisions/{decision_id}/vote",
            json={"option_id": option_id},
            headers=ctx["chair_headers"],
        )
        assert vote.status_code == 200, vote.text


async def test_decisions_list_query_count_does_not_grow_with_decisions(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    ctx = await _create_approved_committee(
        client, auth_headers, roles_by_name, suffix="qbudget", member_count=2
    )
    headers = ctx["member_headers_list"][0]

    await _add_voted_decisions(client, ctx, 2)
    few, few_body = await _count(client, "/api/v1/decisions", headers)

    await _add_voted_decisions(client, ctx, 6)
    many, many_body = await _count(client, "/api/v1/decisions", headers)

    assert len(few_body) == 2 and len(many_body) == 8
    assert many == few, f"list query count grew with item count: {few} -> {many}"
    assert many <= 9, f"decisions list uses {many} SQL statements"
    # الشكل الكامل ما زال كما هو (لوحة القرارات بغرفة الاجتماع تعتمد عليه).
    item = many_body[0]
    assert item["creator"]["user_id"] and item["assignees"] and len(item["vote_options"]) == 2
    assert item["votes"][0]["voter"]["user_id"] and item["votes"][0]["option"]["label"]


async def test_decision_detail_query_count_is_constant(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    ctx = await _create_approved_committee(
        client, auth_headers, roles_by_name, suffix="qdetail", member_count=2
    )
    await _add_voted_decisions(client, ctx, 1)
    decision_id = (await client.get("/api/v1/decisions", headers=ctx["chair_headers"])).json()[0][
        "decision_id"
    ]
    statements, body = await _count(
        client, f"/api/v1/decisions/{decision_id}", ctx["member_headers_list"][0]
    )
    assert body["votes"] and body["assignees"]
    assert statements <= 9, f"decision detail uses {statements} SQL statements"


async def test_listing_does_not_delete_votes(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    ctx = await _create_approved_committee(
        client, auth_headers, roles_by_name, suffix="voteloss", member_count=1
    )
    # الأقدم: ينتهي موعده فيُغلَق كسليًا أثناء القائمة (فتحدث commit).
    expiring_id, _ = await _new_voting_decision(client, ctx, "قرار ينتهي موعده")
    voted_id, option_id = await _new_voting_decision(client, ctx, "قرار صوّت عليه الرئيس")
    vote = await client.post(
        f"/api/v1/decisions/{voted_id}/vote",
        json={"option_id": option_id},
        headers=ctx["chair_headers"],
    )
    assert vote.status_code == 200, vote.text

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Decision)
            .where(Decision.decision_id == expiring_id)
            .values(voting_deadline=datetime.now(UTC) - timedelta(minutes=1))
        )
        # دور "عضو اللجنة" بلا decisions.vote.view_result (إعداد مسموح من
        # شاشة الأدوار والصلاحيات).
        member_role = (
            await db.execute(select(Role.role_id).where(Role.committee_role_slug == "member"))
        ).scalar_one()
        view_result = (
            await db.execute(
                select(Permission.permission_id).where(
                    Permission.code == "decisions.vote.view_result"
                )
            )
        ).scalar_one()
        await db.execute(
            delete(RolePermission).where(
                RolePermission.role_id == member_role, RolePermission.permission_id == view_result
            )
        )
        await db.commit()

    listed = await client.get("/api/v1/decisions", headers=ctx["member_headers_list"][0])
    assert listed.status_code == 200, listed.text
    voted = next(d for d in listed.json() if d["decision_id"] == voted_id)
    assert voted["votes"] == []  # العضو لا يرى صوت الرئيس…

    async with AsyncSessionLocal() as db:
        remaining = (
            await db.execute(
                select(func.count())
                .select_from(DecisionVote)
                .where(DecisionVote.decision_id == voted_id)
            )
        ).scalar_one()
    assert remaining == 1, "…لكن صوت الرئيس يجب أن يبقى محفوظًا بالقاعدة"


async def test_changing_vote_returns_new_option_and_few_statements(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    """تغيير خيار صوت موجود يرجع الخيار الجديد في نفس الاستجابة (بعد إزالة
    إعادة التحميل الثانية بعد commit — تحسين أداء 2026-10-24)."""
    ctx = await _create_approved_committee(
        client, auth_headers, roles_by_name, suffix="votechange", member_count=2
    )
    decision_id, yes_id = await _new_voting_decision(client, ctx, "قرار تغيير الصوت")
    detail = (await client.get(f"/api/v1/decisions/{decision_id}", headers=ctx["chair_headers"])).json()
    no_id = next(o["option_id"] for o in detail["vote_options"] if o["option_id"] != yes_id)

    first = await client.post(
        f"/api/v1/decisions/{decision_id}/vote", json={"option_id": yes_id}, headers=ctx["chair_headers"]
    )
    assert first.status_code == 200, first.text

    await _drain_background_tasks()
    with _QueryCounter() as counter:
        second = await client.post(
            f"/api/v1/decisions/{decision_id}/vote", json={"option_id": no_id}, headers=ctx["chair_headers"]
        )
    assert second.status_code == 200, second.text
    mine = [v for v in second.json()["votes"] if v["voter"]["user_id"] == ctx["chair_id"]]
    assert len(mine) == 1 and mine[0]["option"]["option_id"] == no_id
    assert counter.count <= 14, f"changing a vote uses {counter.count} SQL statements"


async def test_listing_closes_voting_only_when_every_member_voted(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    """2026-10-25: أعضاء اللجنة (من يحق له التصويت) صاروا يُحمَّلون بالقائمة
    فقط للجان القرارات المفتوحة للتصويت. الإغلاق الكسلي عبر القائمة لازم يبقى
    كما هو: لا يُغلق قبل أن يصوّت الجميع، ويُغلق بمجرد ما يصوّتون."""
    import uuid as _uuid

    ctx = await _create_approved_committee(
        client, auth_headers, roles_by_name, suffix="listclose", member_count=1
    )
    decision_id, option_id = await _new_voting_decision(client, ctx, "قرار للإغلاق عبر القائمة")

    async def _insert_vote(user_id: str) -> None:
        # مباشرة بالقاعدة (لا عبر /vote الذي يغلق فورًا) حتى تكون القائمة
        # هي أول من يرى اكتمال التصويت.
        async with AsyncSessionLocal() as db:
            db.add(
                DecisionVote(
                    decision_id=_uuid.UUID(decision_id),
                    user_id=_uuid.UUID(user_id),
                    option_id=_uuid.UUID(option_id),
                )
            )
            await db.commit()

    async def _listed() -> dict:
        response = await client.get("/api/v1/decisions", headers=ctx["chair_headers"])
        assert response.status_code == 200, response.text
        return next(d for d in response.json() if d["decision_id"] == decision_id)

    await _insert_vote(ctx["chair_id"])
    assert (await _listed())["voting_closed_at"] is None  # العضو لم يصوّت بعد

    await _insert_vote(ctx["member_ids"][0])
    closed = await _listed()
    assert closed["voting_closed_at"] is not None and closed["status"] == "voting"


async def test_listing_without_open_voting_skips_members_query(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    ctx = await _create_approved_committee(
        client, auth_headers, roles_by_name, suffix="nomembers", member_count=2
    )
    await _add_voted_decisions(client, ctx, 2)
    open_count, _ = await _count(client, "/api/v1/decisions", ctx["member_headers_list"][0])

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Decision)
            .where(Decision.committee_id == ctx["committee_id"])
            .values(voting_closed_at=datetime.now(UTC))
        )
        await db.commit()
    closed_count, body = await _count(client, "/api/v1/decisions", ctx["member_headers_list"][0])
    assert len(body) == 2 and body[0]["assignees"]
    assert closed_count == open_count - 1, f"{open_count} -> {closed_count}"
