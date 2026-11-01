"""
الهدف:
تصنيف "مرفقات اللجنة" بصفحة الوثائق (طلب لاما 2026-11-01): تصفّح هرمي
لجنة ← (مرفقات الاجتماعات | مرفقات المهام) ← اجتماع ← مرفقاته + محضره.

المسؤولية — تحميل كسول صارم (شرط لاما الصريح: "لا تجيب بيانات أنا لسه ما
طلبتها"): كل مستوى دالة مستقلة بنقطة API مستقلة، تُستدعى فقط لما المستخدم
يفتح ذاك المستوى، وكل دالة تجلب أعمدة شاشتها فقط:
- list_committees_brief: المعرّف، الاسم، تاريخ النهاية + حالة منتهية/جارية.
  (لا أعضاء، لا اجتماعات، لا أعداد.)
- list_committee_meetings_brief: المعرّف، العنوان، الموعد فقط — أعمدة SQL
  مباشرة بلا تحميل كائنات Meeting ولا أي علاقة.
- get_meeting_bundle: مرفقات اجتماع واحد (العرض/المرفقات العامة/مرفقات
  البنود مع عنوان البند) + توفر المحضر ومرحلته. محتوى المحضر نفسه لا يُجلب
  هنا — يُولَّد PDF فقط لما يضغط تحميل (GET /meetings/{id}/minutes/pdf).
- مرفقات المهام: لا نقطة لها حاليًا (قرار لاما: القسم يظهر فاضي الآن).

الصلاحيات (RBAC بالباك-إند):
- اللجان: نطاق committees.view النظامي (own/department/all)، ومن لا يملكه
  يرى لجانه (رئيس/عضو) فقط — نفس قاعدة GET /committees.
- اجتماعات لجنة: meetings.view على تلك اللجنة (System Role أو دور اللجنة).
- مرفقات اجتماع: meetings.attachments.view، والمحضر: minutes.view. من يملك
  واحدة منهما فقط يحصل على جزئها والآخر فاضي (لا 403 للصفحة كاملة)؛ من لا
  يملك أيًا منهما يُرفض.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.meeting import Meeting, MeetingAgendaItem
from app.models.meeting_minutes import MeetingMinutes
from app.models.user import User
from app.services import committee_service, meeting_service
from app.services.committee_access import CommitteeAccess
from app.services.meeting_service.errors import MeetingForbiddenError
from app.services.meeting_service.loading import load_committee, load_meeting

# السعودية بلا توقيت صيفي — "اليوم" لتحديد اللجنة المنتهية بتوقيت الرياض.
_RIYADH = timezone(timedelta(hours=3))


@dataclass
class CommitteeBrief:
    committee_id: uuid.UUID
    name: str
    end_date: date | None
    is_ended: bool


@dataclass
class MeetingBrief:
    meeting_id: uuid.UUID
    title: str
    scheduled_at: datetime


@dataclass
class BundleAttachment:
    document: Document
    kind: str
    linked_at: datetime
    agenda_item_id: uuid.UUID | None
    agenda_item_title: str | None


@dataclass
class MeetingBundle:
    meeting_id: uuid.UUID
    title: str
    can_view_attachments: bool
    attachments: list[BundleAttachment]
    can_view_minutes: bool
    minutes_available: bool
    minutes_stage: str | None


async def list_committees_brief(db: AsyncSession, *, actor: User) -> list[CommitteeBrief]:
    """
    الهدف: قائمة لجان المستخدم (المنتهية والجارية) — المستوى الأول بالتصنيف.
    المدخلات: actor. المخرجات: CommitteeBrief لكل لجنة، الجارية أولًا.
    الاستعلامات: 1 (list_committees بوضع summary — أعمدة اللجنة فقط).
    """
    scope = actor.scope_for("committees.view") or "own"
    committees = await committee_service.list_committees(db, actor=actor, scope=scope, summary=True)
    today = datetime.now(_RIYADH).date()
    briefs = [
        CommitteeBrief(
            committee_id=c.committee_id,
            name=c.name,
            end_date=c.end_date,
            is_ended=c.end_date is not None and c.end_date < today,
        )
        for c in committees
        if c.deleted_at is None
    ]
    # الجارية أولًا (ترتيب list_committees الأصلي — الأحدث — محفوظ داخل كل مجموعة).
    briefs.sort(key=lambda b: b.is_ended)
    return briefs


async def list_committee_meetings_brief(
    db: AsyncSession, *, actor: User, committee_id: uuid.UUID
) -> list[MeetingBrief]:
    """
    الهدف: أسماء اجتماعات لجنة واحدة فقط (المستوى الثالث — بعد اختيار
    "مرفقات الاجتماعات").
    المدخلات: committee_id. يتطلب meetings.view على اللجنة.
    المخرجات: MeetingBrief (معرّف/عنوان/موعد) الأحدث أولًا.
    الأخطاء: MeetingNotFoundError (404) لجنة غير موجودة، MeetingForbiddenError (403).
    الاستعلامات: اللجنة + رئيسها (1) + أكواد دور اللجنة عند الحاجة (0-1) + الاجتماعات (1).
    """
    committee = await load_committee(db, committee_id)
    if not await CommitteeAccess(db, actor).has(committee, "meetings.view"):
        raise MeetingForbiddenError("ليست لديك صلاحية عرض اجتماعات هذه اللجنة")
    result = await db.execute(
        select(Meeting.meeting_id, Meeting.title, Meeting.scheduled_at)
        .where(Meeting.committee_id == committee_id, Meeting.deleted_at.is_(None))
        .order_by(Meeting.scheduled_at.desc())
    )
    return [MeetingBrief(meeting_id=r.meeting_id, title=r.title, scheduled_at=r.scheduled_at) for r in result.all()]


async def get_meeting_bundle(db: AsyncSession, *, actor: User, meeting_id: uuid.UUID) -> MeetingBundle:
    """
    الهدف: مرفقات اجتماع واحد + محضره (المستوى الأخير — بعد اختيار اجتماع).
    المدخلات: meeting_id.
    المخرجات: MeetingBundle — المرفقات (مرفقات البنود مع عنوان بندها) وحالة
    المحضر (موجود؟ مرحلته) بدون محتواه.
    الأخطاء: MeetingNotFoundError (404)، MeetingForbiddenError (403) لو لا
    يملك عرض المرفقات ولا عرض المحضر.
    الاستعلامات: الاجتماع + لجنته + رئيسها (1) + أكواد دور اللجنة (0-1) +
    المرفقات (1) + عناوين البنود عند وجود مرفقات بنود فقط (0-1) + مرحلة المحضر (0-1).
    """
    meeting = await load_meeting(db, meeting_id)
    access = CommitteeAccess(db, actor)
    can_attachments = await access.has(meeting.committee, "meetings.attachments.view")
    can_minutes = await access.has(meeting.committee, "minutes.view")
    if not (can_attachments or can_minutes):
        raise MeetingForbiddenError("ليست لديك صلاحية عرض مرفقات هذا الاجتماع")

    attachments: list[BundleAttachment] = []
    if can_attachments:
        rows = await meeting_service.query_meeting_attachments(db, meeting_id=meeting_id)
        agenda_ids = {aid for _d, _k, _l, aid in rows if aid is not None}
        titles: dict[uuid.UUID, str] = {}
        if agenda_ids:
            result = await db.execute(
                select(MeetingAgendaItem.agenda_item_id, MeetingAgendaItem.title).where(
                    MeetingAgendaItem.agenda_item_id.in_(agenda_ids)
                )
            )
            titles = {r.agenda_item_id: r.title for r in result.all()}
        attachments = [
            BundleAttachment(
                document=doc,
                kind=kind,
                linked_at=linked_at,
                agenda_item_id=aid,
                agenda_item_title=titles.get(aid) if aid else None,
            )
            for doc, kind, linked_at, aid in rows
            # مرفق بند محذوف (لو فات التنظيف) لا يظهر يتيمًا بلا عنوان.
            if aid is None or aid in titles
        ]

    stage: str | None = None
    if can_minutes:
        stage_value = await db.scalar(
            select(MeetingMinutes.stage).where(MeetingMinutes.meeting_id == meeting_id)
        )
        stage = stage_value.value if stage_value is not None else None

    return MeetingBundle(
        meeting_id=meeting.meeting_id,
        title=meeting.title,
        can_view_attachments=can_attachments,
        attachments=attachments,
        can_view_minutes=can_minutes,
        minutes_available=stage is not None and stage != "none",
        minutes_stage=stage,
    )
