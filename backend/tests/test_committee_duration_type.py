"""
اختبارات "نوع مدة اللجنة" (دائمة/مؤقتة) — db/migrations/0037_committee_duration_type.sql،
طلب صاحبة المشروع 2026-10-29.

تغطي:
- إنشاء طلب دائم بلا تواريخ، وتمرير النوع للجنة عند الاعتماد (جارية دائمًا).
- رفض الدائمة مع تواريخ، ورفض المؤقتة بلا تواريخ.
- تغيير النوع أثناء التعديل قبل الاعتماد (مسح التواريخ عند التحويل لدائمة،
  واشتراطها عند التحويل لمؤقتة).
- النوع ثابت بعد الاعتماد: لا تعديل لفترة لجنة دائمة.
- فحوص فترة اللجنة (app/core/committee_period.py) تقبل أي تاريخ للدائمة.
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
    """حمولة طلب لجنة دائمة صالحة — بلا أي تاريخ."""
    return {
        "committee_name": name,
        "statement": "بيان اللجنة",
        "duration_type": "permanent",
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


async def test_permanent_request_has_no_dates_and_committee_is_always_ongoing(
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
    assert body["start_date"] is None
    assert body["end_date"] is None

    committee_id = await _approve(client, actors, body["request_id"])

    detail = await client.get(f"/api/v1/committees/{committee_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    committee = detail.json()
    assert committee["duration_type"] == "permanent"
    assert committee["start_date"] is None
    assert committee["end_date"] is None
    assert committee["lifecycle_state"] == "ongoing"


async def test_permanent_request_with_dates_is_rejected(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    payload = _permanent_payload(actors["member_id"])
    payload["start_date"] = "2026-09-01"
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
    payload["end_date"] = "2026-12-01"  # بلا start_date
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


async def test_switching_type_on_draft_clears_or_requires_dates(
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

    # مؤقتة → دائمة: التواريخ المحفوظة تُمسح.
    to_permanent = await client.patch(
        f"/api/v1/committee-requests/{request_id}",
        json={"duration_type": "permanent"},
        headers=actors["admin_headers"],
    )
    assert to_permanent.status_code == 200, to_permanent.text
    assert to_permanent.json()["duration_type"] == "permanent"
    assert to_permanent.json()["start_date"] is None
    assert to_permanent.json()["end_date"] is None

    # دائمة → مؤقتة بلا تواريخ: مرفوض (لا تواريخ محفوظة نرجع لها).
    missing_dates = await client.patch(
        f"/api/v1/committee-requests/{request_id}",
        json={"duration_type": "temporary"},
        headers=actors["admin_headers"],
    )
    assert missing_dates.status_code == 400, missing_dates.text

    # دائمة → مؤقتة مع تواريخ: مقبول.
    to_temporary = await client.patch(
        f"/api/v1/committee-requests/{request_id}",
        json={"duration_type": "temporary", "start_date": "2026-10-01", "end_date": "2027-01-01"},
        headers=actors["admin_headers"],
    )
    assert to_temporary.status_code == 200, to_temporary.text
    assert to_temporary.json()["duration_type"] == "temporary"
    assert to_temporary.json()["start_date"] == "2026-10-01"


async def test_permanent_committee_period_cannot_be_edited_after_approval(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    """النوع ثابت بعد الاعتماد — شاشة "تعديل فترة اللجنة" ترفض اللجنة الدائمة."""
    actors = await _setup_actors(client, auth_headers, roles_by_name)
    create = await client.post(
        "/api/v1/committee-requests",
        json=_permanent_payload(actors["member_id"]),
        headers=actors["admin_headers"],
    )
    committee_id = await _approve(client, actors, create.json()["request_id"])

    response = await client.patch(
        f"/api/v1/committees/{committee_id}",
        json={"start_date": "2026-09-01", "end_date": "2026-12-01"},
        headers=auth_headers,
    )
    assert response.status_code == 400, response.text

    detail = await client.get(f"/api/v1/committees/{committee_id}", headers=auth_headers)
    assert detail.json()["duration_type"] == "permanent"
    assert detail.json()["end_date"] is None


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
