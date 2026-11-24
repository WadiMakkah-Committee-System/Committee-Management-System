"""
اختبارات "المراجعة الاختيارية" للمحضر (قرار لاما 2026-11-17) مقابل PostgreSQL حقيقي:

- اختيار القالب لا يضيف أي مراجعين تلقائيًا (لا أحد "بانتظار المراجعة").
- عضو بلا صلاحية minutes.review: can_review=False ومحاولة المراجعة 403.
- عضو مُنحت له minutes.review من شاشة الأدوار: can_review=True، ومراجعته
  تُنشئ صف المراجع لحظتها وتظهر بالمحضر وبالملخص.
- غير العضو (outsider) ممنوع حتى لو كان الطلب صحيحًا.
- اعتماد رئيس اللجنة لا ينتظر أي مراجعة.
"""

from httpx import AsyncClient

from app.models.user import User
from tests.test_decisions import _revoke_committee_role_permissions
from tests.test_meetings import _grant_committee_role_permissions
from tests.test_minutes_general_api import _detail, _select_general, _setup


async def _detail_full(client: AsyncClient, ctx: dict, headers) -> dict:
    response = await client.get(f"/api/v1/meetings/{ctx['meeting_id']}/minutes/detail", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_template_selection_adds_no_reviewers(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User
) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    minutes = await _select_general(client, ctx)
    assert minutes["reviewers"] == []
    assert (await _detail(client, ctx))["reviewers"] == []


async def test_member_without_review_permission_cannot_review(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User
) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    await _select_general(client, ctx)
    # الاختبار التالي يمنح العضو minutes.review، والمنح يبقى بالقاعدة بين
    # الاختبارات والتشغيلات (role_permissions لا تُفرَّغ) — نسحبها هنا صراحة.
    await _revoke_committee_role_permissions(["minutes.review"], slug="member")

    detail = await _detail_full(client, ctx, ctx["member_headers"])
    assert detail["can_review"] is False

    response = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/minutes/review/approve",
        json={"comment": "تمام"},
        headers=ctx["member_headers"],
    )
    assert response.status_code == 403, response.text


async def test_member_with_review_permission_reviews_on_demand(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User
) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    await _select_general(client, ctx)
    # الأدمن يفعّل شيك بوكس "مراجعة المحضر وإبداء الرأي" لدور عضو اللجنة.
    await _grant_committee_role_permissions(
        ["minutes.view", "minutes.update", "minutes.sign", "minutes.review"], slug="member"
    )

    detail = await _detail_full(client, ctx, ctx["member_headers"])
    assert detail["can_review"] is True

    response = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/minutes/review/return",
        json={"comment": "صياغة القرار الثاني غير دقيقة"},
        headers=ctx["member_headers"],
    )
    assert response.status_code == 200, response.text
    reviewers = response.json()["reviewers"]
    assert len(reviewers) == 1
    assert reviewers[0]["user"]["user_id"] == ctx["member_id"]
    assert reviewers[0]["status"] == "returned"
    assert reviewers[0]["comment"] == "صياغة القرار الثاني غير دقيقة"

    # المراجعة رأي فقط: المحضر يبقى بمرحلة الإعداد، ورئيس اللجنة يعتمد متى ما بغى.
    assert response.json()["stage"] == "preparing"
    approve = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/minutes/approve", headers=ctx["chair_headers"]
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["stage"] == "signature"


async def test_outsider_cannot_review_even_with_permission_request(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User
) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    await _select_general(client, ctx)
    response = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/minutes/review/approve",
        json={},
        headers=ctx["outsider_headers"],
    )
    assert response.status_code == 403, response.text


async def test_chair_can_approve_without_any_review(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user: User
) -> None:
    ctx = await _setup(client, auth_headers, roles_by_name)
    await _select_general(client, ctx)
    detail = await _detail_full(client, ctx, ctx["chair_headers"])
    assert detail["can_review"] is True  # الرئيس عنده الصلاحية لكنه غير مُلزم
    approve = await client.post(
        f"/api/v1/meetings/{ctx['meeting_id']}/minutes/approve", headers=ctx["chair_headers"]
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["stage"] == "signature"
