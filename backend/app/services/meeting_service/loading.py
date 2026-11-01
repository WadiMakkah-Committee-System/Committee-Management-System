"""
تحميل الاجتماعات واللجان من قاعدة البيانات — المكان **الوحيد** بوحدة
الاجتماعات الذي يحدد ماذا يُحمَّل مع كل اجتماع.

لماذا هذا الملف (تحقيق أداء 2026-10-24، مقاس على الإنتاج): الموديلات
تعرّف أغلب العلاقات lazy="selectin"، فـselect(Meeting) بلا خيارات كان يجرّ
تلقائيًا شجرة كاملة (اللجنة → رئيسها/أعضاؤها/أدوارهم → صلاحيات كل دور،
والمنشئ والمشاركين → أدوارهم → صلاحياتهم، والبنود) = حوالي 29 إلى 34
استعلامًا لطلب واحد، وكل استعلام يكلّف ~355ms على الإنتاج (Render Oregon ↔
Supabase Ireland). هنا كل نوع تحميل صريح ومحدد بحاجة المستدعي فعليًا:

- access_options(): للعمليات التي تحتاج فحص صلاحية فقط (اللجنة + رئيسها).
- detail_options(): لشكل MeetingOut الكامل (+ ما يحتاجه الإشعار البريدي).
- أي علاقة غير مذكورة صراحة عليها raiseload(sql_only=True): لو حاول كود
  مستقبلي قراءة علاقة لم تُحمَّل، يفشل فورًا بخطأ واضح بدل أن يطلق
  استعلامًا مخفيًا (أو يفشل بـMissingGreenlet غامض في async).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, raiseload, selectinload

from app.models.committee import Committee
from app.models.meeting import Meeting, MeetingStatus, meeting_participants
from app.models.user import User
from app.services.meeting_service.errors import MeetingNotFoundError


def _committee_with_chair(path):
    """اللجنة + رئيسها فقط (يكفيان _system_scope_allows) — أي علاقة أخرى
    للجنة أو لرئيسها ممنوعة صراحةً."""
    chair = path.joinedload(Committee.chair)
    return (path, chair, chair.raiseload("*", sql_only=True), path.raiseload("*", sql_only=True))


def access_options() -> tuple:
    """فحص صلاحية على اجتماع واحد + قراءة حقوله المباشرة. استعلام واحد."""
    return (
        *_committee_with_chair(joinedload(Meeting.committee)),
        raiseload("*", sql_only=True),
    )


def detail_options() -> tuple:
    """شكل MeetingOut الكامل (creator/participants/agenda_items) + اللجنة
    ورئيسها لفحص الصلاحية + اسم اللجنة والمشاركين للإشعار البريدي بعد
    الإنشاء/التعديل/الإلغاء (notification_service). 3 استعلامات ثابتة مهما
    كان عدد المشاركين."""
    creator = joinedload(Meeting.creator)
    participants = selectinload(Meeting.participants)
    return (
        *_committee_with_chair(joinedload(Meeting.committee)),
        creator,
        creator.raiseload("*", sql_only=True),
        participants,
        participants.raiseload("*", sql_only=True),
        selectinload(Meeting.agenda_items),
        raiseload("*", sql_only=True),
    )


async def load_meeting(
    db: AsyncSession, meeting_id: uuid.UUID, *, detail: bool = False, reload: bool = False
) -> Meeting:
    """
    reload=True فقط لإعادة التحميل بعد commit/flush بنفس الدالة (populate_existing).

    لماذا ليس دائمًا: الجلسة الواحدة تشارك نفس كائن الاجتماع بين الخدمات
    (مثلًا meeting_minutes_service يحمّله كاملًا ثم يستدعي
    list_extracted_items). populate_existing مع raiseload كان يعيد تعبئة
    الكائن المشترك فيُعلّم علاقاته التي حمّلتها الخدمة الأخرى (المشاركين
    والبنود) كممنوعة → خطأ عند قراءتها بعد ذلك. بدونه، كائن موجود أصلًا
    بالجلسة يبقى كما هو (بعلاقاته المحمّلة)، وخيارات التحميل تطبَّق فقط
    على كائن جديد.
    """
    options = detail_options() if detail else access_options()
    result = await db.execute(
        select(Meeting)
        .where(Meeting.meeting_id == meeting_id)
        .options(*options)
        .execution_options(populate_existing=reload)
    )
    meeting = result.unique().scalar_one_or_none()
    if meeting is None or meeting.is_deleted:
        raise MeetingNotFoundError("الاجتماع غير موجود")
    sync_meeting_status(meeting)
    return meeting


async def load_committee(
    db: AsyncSession, committee_id: uuid.UUID, *, with_members: bool = False
) -> Committee:
    """اللجنة + رئيسها (+ أعضاؤها عند الطلب: مصدر المشاركين التلقائي عند
    إنشاء اجتماع، وأسماء المشاركين لتوليد المسودة). بدون member_roles/
    أدوار/صلاحيات الأعضاء — غير مستخدمة بهذه المسارات."""
    chair = joinedload(Committee.chair)
    options: list = [chair, chair.raiseload("*", sql_only=True)]
    if with_members:
        members = selectinload(Committee.members)
        options += [members, members.raiseload("*", sql_only=True)]
    options.append(raiseload("*", sql_only=True))
    result = await db.execute(
        select(Committee)
        .where(Committee.committee_id == committee_id)
        .options(*options)
        .execution_options(populate_existing=True)
    )
    committee = result.unique().scalar_one_or_none()
    if committee is None or committee.is_deleted:
        raise MeetingNotFoundError("اللجنة المرتبطة غير موجودة")
    return committee


def participant_count_column():
    """عدد المشاركين كعمود مرتبط (correlated subquery) — يُحسب داخل نفس
    استعلام قائمة الاجتماعات بدل تحميل قوائم المستخدمين كاملة."""
    return (
        select(func.count())
        .select_from(meeting_participants)
        .where(meeting_participants.c.meeting_id == Meeting.meeting_id)
        .correlate(Meeting)
        .scalar_subquery()
        .label("participant_count")
    )


def sync_meeting_status(meeting: Meeting) -> None:
    """
    تحويل كسول (Lazy) لحالة الاجتماع من الوقت الفعلي مقابل
    (scheduled_at, scheduled_end_at) — بدل Scheduler/Cron منفصل (لا حاجة
    له بحجم هذا المشروع). يُستدعى من كل نقطة تحميل اجتماع (load_meeting
    وlist_meetings أدناه)، فتُعاد الحالة الصحيحة فعليًا مع كل قراءة، بصرف
    النظر هل حُفظت القيمة الجديدة بقاعدة البيانات بهذا الطلب تحديدًا أو لا
    (القراءات وحدها — GET — لا تُنفّذ commit عمدًا؛ الحساب نفسه مشتق دائمًا
    من scheduled_at/scheduled_end_at الثابتين + الوقت الحالي، فهو صحيح على
    أي حال بكل قراءة قادمة، وتُحفَظ القيمة تلقائيًا بأول طلب كتابة يمر بنفس
    الاجتماع لاحقًا: تعديل/حذف/انضمام/مغادرة).

    قرار موثّق مع لاما 2026-09-05: يعمل فقط على الاجتماعات التي لها
    scheduled_end_at (اجتماعات جديدة بعد migration 0023) — الاجتماعات
    القديمة بلا هذا الحقل تبقى بسلوكها التاريخي (بلا تحويل تلقائي، القرار
    المؤجَّل الأصلي لمرحلة تكامل Teams ما زال ساريًا عليها فقط، راجعي رأس
    db/migrations/0018). لا يمس started_at/ended_at (حضور Agora فعلي، مفهوم
    منفصل تمامًا) ولا يمس status == recorded أبدًا (محجوزة لمرحلة تسجيل
    Teams مستقبلية).

    إصلاح 2026-09-09 (بلاغ لاما — فتحت اجتماعًا انتهى وقته المجدول من قسم
    المحاضر وظل يظهر "الاجتماع لم ينتهِ بعد"): كانت الدالة private
    (باسم _maybe_transition_status) ومستدعاة فقط داخل هذا الملف، بينما
    meeting_minutes_service._load_meeting (نسخة محلية منفصلة لجلب
    الاجتماع، بنفس نمط meeting_chat_service._load_meeting_and_committee)
    كانت تقرأ العمود status الخام من القاعدة مباشرة بلا أي تحويل — فتبقى
    عالقة على upcoming/ongoing حتى يمر طلب كتابة آخر على نفس الاجتماع
    (تعديل/انضمام...) يُشغّل هذه الدالة صدفة. حُوِّلت الآن لدالة عامة
    (بلا _) عمدًا لتصبح قابلة للاستيراد والاستدعاء من أي ملف خدمة آخر
    يحمّل Meeting ويعتمد على status الزمني — بدأ فعليًا بـ
    meeting_minutes_service._load_meeting (راجعيها). أي ملف مستقبلي
    يحمّل Meeting ويحتاج status صحيحًا زمنيًا (وليس فقط القيمة الخام
    بالقاعدة) يجب أن يستدعيها أيضًا بدل تكرار المنطق أو تجاهله — هذا
    بالضبط الفخ اللي وقعنا فيه هنا.
    """
    if meeting.scheduled_end_at is None:
        return
    if meeting.status not in (MeetingStatus.upcoming, MeetingStatus.ongoing):
        return

    now = datetime.now(UTC)
    if now >= meeting.scheduled_end_at:
        meeting.status = MeetingStatus.finished
    elif now >= meeting.scheduled_at:
        meeting.status = MeetingStatus.ongoing
    else:
        meeting.status = MeetingStatus.upcoming


def _all_committee_members(committee: Committee) -> list[User]:
    """
    كل أعضاء اللجنة (بمن فيهم رئيسها) — مصدر المشاركين التلقائي الوحيد
    عند إنشاء الاجتماع (راجعي docstring أعلى الملف). لا تكرار: الرئيس قد
    يكون أيضًا ضمن committee.members حسب لحظة الاستعلام، فنستبعد تكراره
    صراحة.
    """
    members = list(committee.members)
    if committee.chair is not None and committee.chair_user_id not in {m.user_id for m in members}:
        members.append(committee.chair)
    return members
