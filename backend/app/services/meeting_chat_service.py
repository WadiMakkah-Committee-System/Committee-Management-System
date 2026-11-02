"""
الهدف:
فحوص الوصول لقناة الاجتماع اللحظية (Socket.IO — راجعي
app/core/socketio_server.py): من يقدر يتصل بغرفة الاجتماع (التواجد، رفع
اليد، بند المناقشة الحالي)، ومن يقدر يدير بند المناقشة. التفويض: نفس
صلاحية الانضمام للاجتماع (meetings.join) — نفس نمط التحقق الهجين (System
Role scope أو Committee Role) المكرَّر بكل وحدة بهذا المشروع.

تحديث 2026-11-02 (قرار لاما): أُزيلت "محادثة الاجتماع" النصية الخاصة
بالمنصة (list_messages/send_message، REST /chat/messages، حدث chat.send)
— الأعضاء يستخدمون شات Microsoft Teams داخل الاجتماع نفسه. جدول
meeting_chat_messages يبقى بقاعدة البيانات (رسائل قديمة) بلا استخدام.
اسم الملف بقي كما هو لتفادي تغيير مسارات الاستيراد القائمة.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.committee import Committee
from app.models.meeting import Meeting
from app.models.user import User
from app.services import committee_service


class MeetingChatNotFoundError(Exception):
    """الاجتماع غير موجود — تُترجَم إلى 404."""


class MeetingChatForbiddenError(Exception):
    """لا صلاحية للوصول لمحادثة هذا الاجتماع — تُترجَم إلى 403."""


def _system_scope_allows(actor: User, committee: Committee, code: str) -> bool:
    scope = actor.scope_for(code)
    if scope == "all":
        return True
    if scope == "department":
        committee_dep_id = committee.chair.dep_id if committee.chair else None
        return actor.dep_id is not None and actor.dep_id == committee_dep_id
    return False


async def _has_access(db: AsyncSession, actor: User, committee: Committee, code: str) -> bool:
    if _system_scope_allows(actor, committee, code):
        return True
    committee_role_codes = await committee_service.get_committee_role_permission_codes(
        db, user_id=actor.user_id, committee_id=committee.committee_id
    )
    return code in committee_role_codes


async def _load_meeting_and_committee(
    db: AsyncSession, meeting_id: uuid.UUID
) -> tuple[Meeting, Committee]:
    result = await db.execute(select(Meeting).where(Meeting.meeting_id == meeting_id))
    meeting = result.scalar_one_or_none()
    if meeting is None or meeting.is_deleted:
        raise MeetingChatNotFoundError("الاجتماع غير موجود")

    # committee.lazy="selectin" على Meeting.committee يعني الصف محمَّل فعليًا
    # ضمن نفس استعلام meeting أعلاه — استعلام committee منفصل هنا كان round
    # trip إضافي بلا داعٍ (نفس النمط المُصلَح بـmeeting_minutes_service.py).
    committee = meeting.committee
    if committee is None or committee.is_deleted:
        raise MeetingChatNotFoundError("اللجنة المرتبطة غير موجودة")
    return meeting, committee


async def require_realtime_access(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> Meeting:
    """يستخدمها أيضًا راوت WebSocket (meeting_live_socket) قبل قبول الاتصال —
    نفس التحقق بالضبط المستخدَم لإرسال رسالة أو رفع اليد."""
    meeting, committee = await _load_meeting_and_committee(db, meeting_id)
    if not await _has_access(db, actor, committee, "meetings.join"):
        raise MeetingChatForbiddenError("ليست لديك صلاحية الوصول لهذا الاجتماع")
    return meeting


# إصلاح 2026-09-14 (بلاغ لاما — أي مشارك (عضو عادي، مو بس رئيس اللجنة)
# يقدر يضغط أي بند بجدول الأجندة ويغيّر "قيد المناقشة الآن" لكل الحاضرين؛
# هذا يفسّر ظاهريًا شكوى الرئيسة "ما يضغط عدل" — أي عضو ثاني يضغط بند
# غير قصدًا (أو فضول) يبدّل الحالة لحظيًا فوق ما ضغطته الرئيسة، فتبدو
# الواجهة "ما تستجيب صح" من منظورها رغم إن كل ضغطة تشتغل فعليًا كما
# يُفترض — فقط آخر ضغطة (من أي شخص) هي اللي تفوز). الصلاحية المستخدَمة:
# "meetings.agenda.item.update" — نفس الكود الممنوح فعليًا لرئيس اللجنة
# فقط بجدول role_permissions (تحقّقتُ مباشرة)، الأنسب دلاليًا من بين
# صلاحيات meetings.agenda.* الموجودة لتحديد/تغيير حالة بند حي.
async def require_agenda_manage_access(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID
) -> Meeting:
    meeting, committee = await _load_meeting_and_committee(db, meeting_id)
    if not await _has_access(db, actor, committee, "meetings.agenda.item.update"):
        raise MeetingChatForbiddenError("ليست لديك صلاحية إدارة بنود هذا الاجتماع")
    return meeting
