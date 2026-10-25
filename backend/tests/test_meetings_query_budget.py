"""
اختبار انتفاخ الاستعلامات لوحدة الاجتماعات (إعادة هيكلة 2026-10-24).

الهدف ليس رقمًا ثابتًا لكل endpoint، بل أن عدد استعلامات SQL **لا يكبر مع
عدد العناصر** (N+1)، وأن القائمة لا تحمّل تفاصيل لم تُطلب. قِيس على
الإنتاج: كل استعلام إضافي ≈ 355ms، فكانت قائمة الاجتماعات (~34 استعلامًا)
تأخذ 13–15 ثانية.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import event, select

from app.core import background
from app.db.session import AsyncSessionLocal, engine
from app.models.meeting import Meeting, MeetingAgendaItem, MeetingMode
from app.models.user import User
from tests.test_meetings import _create_approved_committee


class _QueryCounter:
    def __init__(self) -> None:
        self.count = 0

    def __enter__(self) -> "_QueryCounter":
        event.listen(engine.sync_engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *exc) -> None:
        event.remove(engine.sync_engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, *args, **kwargs) -> None:
        self.count += 1


async def _add_meetings(committee_id: str, chair_id: str, how_many: int) -> list[uuid.UUID]:
    ids = []
    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User))).scalars().all()
        start = datetime.now(UTC) + timedelta(days=1)
        for i in range(how_many):
            meeting = Meeting(
                committee_id=committee_id,
                title=f"اجتماع {i}",
                mode=MeetingMode.remote,
                scheduled_at=start + timedelta(hours=i),
                scheduled_end_at=start + timedelta(hours=i, minutes=30),
                created_by=chair_id,
            )
            meeting.participants = list(users)
            meeting.agenda_items = [MeetingAgendaItem(title=f"بند {j}", sort_order=j) for j in range(3)]
            db.add(meeting)
            await db.flush()
            ids.append(meeting.meeting_id)
        await db.commit()
    return ids


async def _drain_background_tasks() -> None:
    """مهام الإشعارات المنفصلة (run_detached) من طلبات سابقة تنفّذ SQL على
    نفس الـengine — ننتظر انتهاءها قبل العدّ حتى لا تُحسب على الطلب المقاس."""
    while background._pending_tasks:
        await asyncio.gather(*list(background._pending_tasks), return_exceptions=True)


async def _count(client: AsyncClient, path: str, headers: dict[str, str]) -> tuple[int, object]:
    await _drain_background_tasks()
    with _QueryCounter() as counter:
        response = await client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    return counter.count, response.json()


async def test_meetings_list_query_count_does_not_grow_with_meetings(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    headers = ctx["chair_headers"]

    await _add_meetings(ctx["committee_id"], ctx["chair_id"], 2)
    few, few_body = await _count(client, "/api/v1/meetings", headers)

    await _add_meetings(ctx["committee_id"], ctx["chair_id"], 10)
    many, many_body = await _count(client, "/api/v1/meetings", headers)

    assert len(few_body) == 2 and len(many_body) == 12
    assert many == few, f"list query count grew with item count: {few} -> {many}"
    assert many <= 4, f"meetings list uses {many} SQL statements"

    item = many_body[0]
    # القائمة لا تحمّل تفاصيل الاجتماع (المشاركين/البنود/المنشئ) — عددهم فقط.
    assert "participants" not in item and "agenda_items" not in item and "creator" not in item
    assert item["participant_count"] > 0


async def test_meeting_detail_query_count_is_constant(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    ctx = await _create_approved_committee(client, auth_headers, roles_by_name)
    headers = ctx["chair_headers"]
    meeting_id = (await _add_meetings(ctx["committee_id"], ctx["chair_id"], 1))[0]

    statements, body = await _count(client, f"/api/v1/meetings/{meeting_id}", headers)

    # التفاصيل الكاملة ما زالت كما هي (نفس MeetingOut).
    assert body["participants"] and len(body["agenda_items"]) == 3 and body["creator"]["user_id"]
    assert statements <= 6, f"meeting detail uses {statements} SQL statements"


async def test_minutes_summary_query_count_does_not_grow_with_committees(
    client: AsyncClient, auth_headers, roles_by_name, super_admin_user
) -> None:
    """2026-10-25: صلاحية minutes.view كانت تُفحص باستعلام مستقل لكل لجنة
    بالقائمة. الآن استعلام واحد لكل عضويات المستخدم مهما كان عدد اللجان."""
    from app.models.committee import committee_members
    from app.models.role import Role
    from tests.test_decisions import _create_approved_committee as _committee
    from tests.test_meetings import _grant_committee_role_permissions

    first = await _committee(client, auth_headers, roles_by_name, suffix="ms1")
    second = await _committee(client, auth_headers, roles_by_name, suffix="ms2")
    await _grant_committee_role_permissions(["minutes.view"], slug="chair")
    await _grant_committee_role_permissions(["minutes.view"], slug="member")
    async with AsyncSessionLocal() as db:
        member_role_id = (
            await db.execute(select(Role.role_id).where(Role.committee_role_slug == "member"))
        ).scalar_one()
        await db.execute(
            committee_members.insert().values(
                committee_id=second["committee_id"],
                user_id=first["chair_id"],
                committee_role_id=member_role_id,
            )
        )
        await db.commit()

    first_ids = await _add_meetings(first["committee_id"], first["chair_id"], 2)
    second_ids = await _add_meetings(second["committee_id"], second["chair_id"], 2)
    headers = first["chair_headers"]

    one, one_body = await _count(
        client, "/api/v1/meetings/minutes/summary?meeting_ids=" + ",".join(map(str, first_ids)), headers
    )
    both, both_body = await _count(
        client,
        "/api/v1/meetings/minutes/summary?meeting_ids=" + ",".join(map(str, first_ids + second_ids)),
        headers,
    )
    assert len(one_body) == 2 and len(both_body) == 4
    assert not any(item["forbidden"] for item in both_body)
    assert both == one, f"minutes summary query count grew with committees: {one} -> {both}"
