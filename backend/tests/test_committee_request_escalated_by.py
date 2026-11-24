"""
الهدف:
اختبارات "مَن رفع طلب تشكيل اللجنة للرئيس التنفيذي" (طلب لاما 2026-11-01):
- كل أعضاء المكتب التنفيذي (أكثر من شخص بنفس الدور) يشوفون نفس الطلبات.
- بعد الرفع يظهر اسم من رفعه ووقت الرفع للمكتب وللرئيس التنفيذي.
- لو أُرجع الطلب ثم رُفع ثانية بواسطة شخص آخر، يظهر آخر من رفعه.
"""

from httpx import AsyncClient
from tests.test_committees import _create_user_with_role, _valid_payload

BASE = "/api/v1/committee-requests"


# _president_can_view_requests: fixture مشترك بـtests/conftest.py.


async def test_escalator_is_shown_and_office_members_share_requests(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], _president_can_view_requests
) -> None:
    admin_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="esc_admin", role_name="admin"
    )
    _, member_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="esc_member", role_name="admin"
    )
    office1_headers, office1_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="esc_office1", role_name="executive_office_manager"
    )
    office2_headers, office2_id = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="esc_office2", role_name="executive_office_manager"
    )
    ceo_headers, _ = await _create_user_with_role(
        client, auth_headers, roles_by_name, username="esc_ceo", role_name="executive_president"
    )

    create = await client.post(BASE, json=_valid_payload(member_id), headers=admin_headers)
    request_id = create.json()["request_id"]
    await client.post(f"{BASE}/{request_id}/submit", headers=admin_headers)

    # الاثنين من المكتب يشوفون نفس الطلب، ولم يُرفع بعد
    for headers in (office1_headers, office2_headers):
        listed = await client.get(BASE, headers=headers)
        assert request_id in {r["request_id"] for r in listed.json()}
        detail = await client.get(f"{BASE}/{request_id}", headers=headers)
        assert detail.json()["escalator"] is None and detail.json()["escalated_at"] is None

    escalate = await client.post(f"{BASE}/{request_id}/escalate", headers=office2_headers)
    assert escalate.status_code == 200, escalate.text
    assert escalate.json()["escalator"]["user_id"] == office2_id
    assert escalate.json()["escalated_at"] is not None

    # يظهر للزميل بالمكتب وللرئيس التنفيذي
    for headers in (office1_headers, ceo_headers):
        detail = await client.get(f"{BASE}/{request_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["escalator"]["user_id"] == office2_id
    listed = await client.get(BASE, headers=ceo_headers)
    row = next(r for r in listed.json() if r["request_id"] == request_id)
    assert row["escalator"]["user_id"] == office2_id

    # الرئيس يرجعه للمكتب، والزميل الأول يرفعه ← يظهر آخر من رفعه
    await client.post(
        f"{BASE}/{request_id}/return-to-office", json={"return_reason": "تفاصيل أكثر"}, headers=ceo_headers
    )
    again = await client.post(f"{BASE}/{request_id}/escalate", headers=office1_headers)
    assert again.status_code == 200, again.text
    assert again.json()["escalator"]["user_id"] == office1_id
