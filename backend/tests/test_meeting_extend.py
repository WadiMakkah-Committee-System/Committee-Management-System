"""
الهدف:
اختبارات تمديد الاجتماع قبله أو أثناءه (طلب لاما 2026-11-01) —
POST /meetings/{id}/extend.

ملاحظة: _create_approved_committee بـtest_meetings.py تنشئ لجنة بفترة ثابتة
(حتى 2026-12-01)؛ هنا نمدّ نهاية فترة اللجنة لسنة من الآن، ونحرّك أوقات
الاجتماع نسبةً للحظة الحالية (بدل تواريخ ثابتة تنتهي صلاحيتها مع الوقت).
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.db.session import AsyncSessionLocal
from app.models.committee import Committee
from app.models.meeting import Meeting
from app.models.user import User
from app.services import notification_service
from tests.test_meetings import _create_approved_committee


@pytest.fixture
def notified(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """يلتقط استدعاءات إشعار تعديل الاجتماع بدل الإرسال الفعلي."""
    calls: list[dict] = []

    async def fake_notify(meeting, changes, *, actor_user_id=None):
        calls.append(changes)

    monkeypatch.setattr(notification_service, "notify_meeting_updated", fake_notify)
    return calls


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def _meeting(client: AsyncClient, ctx: dict, *, start: datetime, end: datetime) -> str:
    """ينشئ اجتماعًا مستقبليًا ثم يضبط أوقاته مباشرة (لتمثيل اجتماع منعقد/منتهٍ)."""
    future = datetime.now(UTC) + timedelta(days=2)
    create = await client.post(
        "/api/v1/meetings",
        json={
            "committee_id": ctx["committee_id"],
            "title": "اجتماع التمديد",
            "mode": "remote",
            "scheduled_at": _iso(future),
            "scheduled_end_at": _iso(future + timedelta(hours=1)),
        },
        headers=ctx["chair_headers"],
    )
    assert create.status_code == 201, create.text
    meeting_id = create.json()["meeting_id"]
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Meeting).where(Meeting.meeting_id == meeting_id).values(scheduled_at=start, scheduled_end_at=end)
        )
        await db.commit()
    return meeting_id


@pytest.fixture
async def ctx(client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User) -> dict:
    context = await _create_approved_committee(client, auth_headers, roles_by_name)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Committee)
            .where(Committee.committee_id == context["committee_id"])
            .values(start_date=date.today() - timedelta(days=30), end_date=date.today() + timedelta(days=365))
        )
        await db.commit()
    return context


async def test_extend_ongoing_meeting(client: AsyncClient, ctx: dict, notified) -> None:
    now = datetime.now(UTC)
    meeting_id = await _meeting(client, ctx, start=now - timedelta(minutes=30), end=now + timedelta(minutes=10))
    new_end = now + timedelta(minutes=40)

    response = await client.post(
        f"/api/v1/meetings/{meeting_id}/extend", json={"new_end_at": _iso(new_end)}, headers=ctx["chair_headers"]
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ongoing"
    assert datetime.fromisoformat(body["scheduled_end_at"].replace("Z", "+00:00")) == new_end.replace(microsecond=new_end.microsecond)
    assert len(notified) == 1 and "scheduled_end_at" in notified[0]


async def test_extend_upcoming_meeting(client: AsyncClient, ctx: dict, notified) -> None:
    now = datetime.now(UTC)
    meeting_id = await _meeting(client, ctx, start=now + timedelta(hours=2), end=now + timedelta(hours=3))
    response = await client.post(
        f"/api/v1/meetings/{meeting_id}/extend",
        json={"new_end_at": _iso(now + timedelta(hours=3, minutes=30))},
        headers=ctx["chair_headers"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "upcoming"


async def test_extend_rejects_shorter_past_and_out_of_period(client: AsyncClient, ctx: dict, notified) -> None:
    now = datetime.now(UTC)
    meeting_id = await _meeting(client, ctx, start=now - timedelta(minutes=30), end=now + timedelta(minutes=30))
    url = f"/api/v1/meetings/{meeting_id}/extend"

    shorter = await client.post(url, json={"new_end_at": _iso(now + timedelta(minutes=15))}, headers=ctx["chair_headers"])
    assert shorter.status_code == 400 and "بعد وقت النهاية الحالي" in shorter.json()["detail"]

    beyond = await client.post(url, json={"new_end_at": _iso(now + timedelta(days=400))}, headers=ctx["chair_headers"])
    assert beyond.status_code == 400

    assert notified == []


async def test_cannot_extend_finished_meeting(client: AsyncClient, ctx: dict, notified) -> None:
    now = datetime.now(UTC)
    meeting_id = await _meeting(client, ctx, start=now - timedelta(hours=2), end=now - timedelta(hours=1))
    response = await client.post(
        f"/api/v1/meetings/{meeting_id}/extend",
        json={"new_end_at": _iso(now + timedelta(minutes=30))},
        headers=ctx["chair_headers"],
    )
    assert response.status_code == 409
    assert notified == []


async def test_member_without_update_permission_cannot_extend(client: AsyncClient, ctx: dict, notified) -> None:
    now = datetime.now(UTC)
    meeting_id = await _meeting(client, ctx, start=now - timedelta(minutes=30), end=now + timedelta(minutes=30))
    for headers in (ctx["member_headers"], ctx["outsider_headers"]):
        response = await client.post(
            f"/api/v1/meetings/{meeting_id}/extend",
            json={"new_end_at": _iso(now + timedelta(hours=1))},
            headers=headers,
        )
        assert response.status_code in (403, 404)
