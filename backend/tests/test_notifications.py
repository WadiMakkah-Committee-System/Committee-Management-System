"""
الإشعارات داخل النظام (إعادة هيكلة 2026-10-24): القائمة/تعليم كمقروء/تعليم
الكل — نفس النتائج، وعدد استعلامات ثابت (المستلم لم يعد يُحمَّل مع كل إشعار
بدوره وصلاحياته، وتعليم الكل UPDATE واحد).
"""

from httpx import AsyncClient
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.notification import Notification
from app.models.user import User
from tests.test_meetings_query_budget import _count


async def _add_notifications(user: User, how_many: int) -> None:
    async with AsyncSessionLocal() as db:
        for i in range(how_many):
            db.add(
                Notification(
                    recipient_user_id=user.user_id, event_type="test.event", title=f"إشعار {i}"
                )
            )
        await db.commit()


async def _unread_in_db(user: User) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.recipient_user_id == user.user_id, Notification.is_read.is_(False))
            )
        ).scalar_one()


async def test_notifications_list_mark_read_and_mark_all(
    client: AsyncClient, auth_headers, super_admin_user: User
) -> None:
    await _add_notifications(super_admin_user, 3)
    few, page = await _count(client, "/api/v1/notifications", auth_headers)
    await _add_notifications(super_admin_user, 9)
    many, page = await _count(client, "/api/v1/notifications", auth_headers)
    assert page["total"] == 12 and len(page["items"]) == 12
    assert many == few, f"notifications list grew: {few} -> {many}"
    assert many <= 6, f"notifications list uses {many} SQL statements"

    first_id = page["items"][0]["notification_id"]
    read = await client.patch(f"/api/v1/notifications/{first_id}/read", headers=auth_headers)
    assert read.status_code == 200, read.text
    assert read.json()["is_read"] is True and read.json()["read_at"]
    assert await _unread_in_db(super_admin_user) == 11

    read_all = await client.post("/api/v1/notifications/read-all", headers=auth_headers)
    assert read_all.status_code == 200, read_all.text
    assert read_all.json()["unread_count"] == 0
    assert await _unread_in_db(super_admin_user) == 0

    # مرة ثانية بلا شيء غير مقروء: لا خطأ، العدد صفر.
    again = await client.post("/api/v1/notifications/read-all", headers=auth_headers)
    assert again.status_code == 200 and again.json()["unread_count"] == 0
