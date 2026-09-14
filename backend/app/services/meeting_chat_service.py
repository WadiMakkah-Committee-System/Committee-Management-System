"""
الهدف:
منطق العمل لـ"محادثة الاجتماع" — راجعي رأس
db/migrations/0026_meeting_realtime.sql للتصميم الكامل. التفويض: نفس
صلاحية الانضمام للاجتماع (meetings.join) بالضبط — لا صلاحية منفصلة
للمحادثة (قرار مقصود: من يقدر يدخل الغرفة يقدر يكتب فيها). نفس نمط
التحقق الهجين (System Role scope أو Committee Role) المكرَّر بكل وحدة
بهذا المشروع (meeting_service.py وdecision_service.py) — مكرَّر هنا
عمدًا بدل استيراد دوال خاصة (_underscore) من meeting_service، اتساقًا مع
قرار decision_service.py نفسه بعدم فعل ذلك.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.committee import Committee
from app.models.meeting import Meeting
from app.models.meeting_chat import MeetingChatMessage
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


async def list_messages(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, limit: int = 100
) -> list[MeetingChatMessage]:
    await require_realtime_access(db, actor=actor, meeting_id=meeting_id)
    result = await db.execute(
        select(MeetingChatMessage)
        .where(MeetingChatMessage.meeting_id == meeting_id)
        .order_by(MeetingChatMessage.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def send_message(
    db: AsyncSession, *, actor: User, meeting_id: uuid.UUID, body: str
) -> MeetingChatMessage:
    """يُستدعى من داخل راوت WebSocket (meeting_live_socket) عند type=chat.send —
    وليس عبر REST. يحفظ الرسالة ويُرجعها؛ البث لبقية المشاركين مسؤولية
    الراوت نفسه (عبر app.core.meeting_realtime.connection_manager) بعد
    نجاح هذا الاستدعاء.

    إصلاح 2026-09-13 (بلاغ لاما — لايف: رسالة الدردشة "ما توصل ولا
    تنحفظ"): كانت تُحفَظ فعليًا (commit ينجح)، لكن db.refresh(message)
    لا يُعيد تحميل العلاقات (relationships) — فقط أعمدة الصف نفسه.
    MeetingChatMessage.sender معرَّفة lazy="selectin" (راجعي
    app/models/meeting_chat.py)، وهذا يعمل تلقائيًا فقط ضمن SELECT فعلي
    يحمّل الصف، لا refresh() لكائن مُنشأ محليًا للتو. النتيجة: socketio_server.
    chat_send يحاول MeetingChatMessageOut.model_validate(message) *بعد*
    إغلاق جلسة async with — أي وصول لـmessage.sender عندها يفشل (الكائن
    detached)، فيُرمى استثناء غير مُلتقَط داخل معالج chat.send، والبث
    ("chat.message") لا يصل لأحد أبدًا — لا للمُرسِل نفسه ولا لبقية
    الحاضرين — رغم أن الرسالة محفوظة فعليًا بقاعدة البيانات (تظهر فقط
    عبر REST History عند إعادة فتح الدردشة لاحقًا). الحل: إعادة تحميل
    الصف بـSELECT صريح مع selectinload(sender) بدل refresh() — نفس نمط
    التحميل الصريح المطبَّق بكل الملف تقريبًا (meeting_service/
    committee_service) بدل الاعتماد على تحميل ضمني بعد انتهاء الجلسة."""
    await require_realtime_access(db, actor=actor, meeting_id=meeting_id)

    trimmed = body.strip()
    if not trimmed:
        raise ValueError("نص الرسالة لا يمكن أن يكون فارغًا")

    message = MeetingChatMessage(meeting_id=meeting_id, sender_id=actor.user_id, body=trimmed[:2000])
    db.add(message)
    await db.commit()

    result = await db.execute(
        select(MeetingChatMessage)
        .where(MeetingChatMessage.message_id == message.message_id)
        .options(selectinload(MeetingChatMessage.sender))
    )
    return result.scalar_one()
