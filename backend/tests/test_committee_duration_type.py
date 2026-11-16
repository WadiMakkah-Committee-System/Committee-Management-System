"""
اختبارات "نوع مدة اللجنة" (دائمة/مؤقتة) — db/migrations/0037_committee_duration_type.sql،
طلب صاحبة المشروع 2026-10-29.

تحديث migration 0050 (قرار لاما 2026-11-16): الدائمة صار لها تاريخ بداية
ونهاية إلزاميان مثل المؤقتة (وتُمدَّد من داخل اللجنة) — الدائمة القديمة بلا
تواريخ تبقى صالحة.

تغطي:
- إنشاء طلب دائم بتواريخ، وتمرير النوع والتواريخ للجنة عند الاعتماد.
- رفض الدائمة بلا تواريخ، ورفض المؤقتة بلا تواريخ.
- تغيير النوع أثناء التعديل قبل الاعتماد يحتفظ بالتواريخ.
- فترة اللجنة الدائمة قابلة للتعديل بعد الاعتماد.
- فحوص فترة اللجنة (app/core/committee_period.py) تقبل أي تاريخ للدائمة القديمة بلا فترة.
- السلوك القديم (بلا duration_type) يبقى مؤقتًا كما كان.
"""

from datetime import date

import pytest
from httpx import AsyncClient

from app.core.committee_period import (
    assert_committee_not_expired,
    assert_within_committee_period,
)
from app.models.committee import Committee
from app.models.committee_request import CommitteeDurationType
from app.models.user import User
from tests.test_committees import _setup_actors


def _permanent_payload(member_id: str, *, name: str = "لجنة دائمة") -> dict:
    """حمولة طلب لجنة دائمة صالحة — بتاريخ بداية ونهاية (migration 0050)."""
    return {
        "committee_name": name,
        "statement": "بيان اللجنة",
        "duration_type": "permanent",
        "start_date": "2026-09-01",
        "end_date": "2027-09-01",
        "proposed_member_ids": [member_id],
        "chair_user_id": member_id,
    }


async def _approve(client: AsyncClient, actors: dict, request_id: str) -> str:
    """ينقل الطلب من draft إلى approved ويرجع committee_id الناتج."""
    await client.post(f"/api/v1/committee-requests/{request_id}/submit", headers=actors["admin_headers"])
    await client.post(f"/api/v1/committee-requests/{request_id}/escalate", headers=actors["office_headers"])
    approve = await client.post(
        f"/api/v1/committee-requests/{request_id}/approve", headers=actors["ceo_headers"]
    )
    assert approve.status_code == 200, approve.text
    return approve.json()["committee_id"]


async def test_permanent_request_keeps_dates_and_committee_follows_them(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)

    create = await client.post(
        "/api/v1/committee-requests",
        json=_permanent_payload(actors["member_id"]),
        headers=actors["admin_headers"],
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["duration_type"] == "permanent"
    assert body["start_date"] == "2026-09-01"
    assert body["end_date"] == "2027-09-01"

    committee_id = await _approve(client, actors, body["request_id"])

    detail = await client.get(f"/api/v1/committees/{committee_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    committee = detail.json()
    assert committee["duration_type"] == "permanent"
    assert committee["start_date"] == "2026-09-01"
    assert committee["end_date"] == "2027-09-01"


async def test_permanent_request_without_dates_is_rejected(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    payload = _permanent_payload(actors["member_id"])
    del payload["start_date"]
    del payload["end_date"]
    response = await client.post(
        "/api/v1/committee-requests", json=payload, headers=actors["admin_headers"]
    )
    assert response.status_code == 422


async def test_temporary_request_without_dates_is_rejected(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    payload = _permanent_payload(actors["member_id"])
    payload["duration_type"] = "temporary"
    del payload["start_date"]  # بلا start_date
    response = await client.post(
        "/api/v1/committee-requests", json=payload, headers=actors["admin_headers"]
    )
    assert response.status_code == 422


async def test_request_without_duration_type_defaults_to_temporary(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """توافق رجعي: العميل القديم (بلا duration_type) يبقى يُنشئ لجنة مؤقتة."""
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    payload = {
        "committee_name": "لجنة قديمة",
        "start_date": "2026-09-01",
        "end_date": "2026-12-01",
        "proposed_member_ids": [actors["member_id"]],
        "chair_user_id": actors["member_id"],
    }
    response = await client.post(
        "/api/v1/committee-requests", json=payload, headers=actors["admin_headers"]
    )
    assert response.status_code == 201, response.text
    assert response.json()["duration_type"] == "temporary"
    assert response.json()["end_date"] == "2026-12-01"


async def test_switching_type_on_draft_keeps_dates(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    create = await client.post(
        "/api/v1/committee-requests",
        json={
            "committee_name": "لجنة مؤقتة",
            "duration_type": "temporary",
            "start_date": "2026-09-01",
            "end_date": "2026-12-01",
            "proposed_member_ids": [actors["member_id"]],
            "chair_user_id": actors["member_id"],
        },
        headers=actors["admin_headers"],
    )
    assert create.status_code == 201, create.text
    request_id = create.json()["request_id"]

    # مؤقتة → دائمة: التواريخ المحفوظة تبقى (migration 0050).
    to_permanent = await client.patch(
        f"/api/v1/committee-requests/{request_id}",
        json={"duration_type": "permanent"},
        headers=actors["admin_headers"],
    )
    assert to_permanent.status_code == 200, to_permanent.text
    assert to_permanent.json()["duration_type"] == "permanent"
    assert to_permanent.json()["start_date"] == "2026-09-01"
    assert to_permanent.json()["end_date"] == "2026-12-01"

    # دائمة → مؤقتة مع تواريخ: مقبول.
    to_temporary = await client.patch(
        f"/api/v1/committee-requests/{request_id}",
        json={"duration_type": "temporary", "start_date": "2026-10-01", "end_date": "2027-01-01"},
        headers=actors["admin_headers"],
    )
    assert to_temporary.status_code == 200, to_temporary.text
    assert to_temporary.json()["duration_type"] == "temporary"
    assert to_temporary.json()["start_date"] == "2026-10-01"


async def test_permanent_committee_period_can_be_edited_after_approval(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    """migration 0050: فترة الدائمة قابلة للتعديل بعد الاعتماد (والنوع يبقى دائمًا)."""
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    create = await client.post(
        "/api/v1/committee-requests",
        json=_permanent_payload(actors["member_id"]),
        headers=actors["admin_headers"],
    )
    committee_id = await _approve(client, actors, create.json()["request_id"])

    response = await client.patch(
        f"/api/v1/committees/{committee_id}",
        json={"end_date": "2028-01-01"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["duration_type"] == "permanent"
    assert response.json()["end_date"] == "2028-01-01"


@pytest.mark.parametrize("value", [date(2000, 1, 1), date(2099, 12, 31)])
def test_period_checks_accept_any_date_for_permanent_committee(value: date) -> None:
    """الاجتماعات/المهام/القرارات بلجنة دائمة لا تُقيَّد بفترة، واللجنة لا تنتهي."""
    committee = Committee(
        name="لجنة دائمة",
        duration_type=CommitteeDurationType.permanent,
        start_date=None,
        end_date=None,
    )
    assert committee.lifecycle_state(today=value) == "ongoing"
    assert_within_committee_period(committee, field_label="التاريخ", value=value)
    assert_committee_not_expired(committee, action_label="الإجراء")
