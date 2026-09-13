"""
الهدف:
منطق العمل لوحدة "المحاضر" (SRS §7 — المحاضر) — إعداد المحضر من قالب
معتمد، تحرير تعاوني (البث اللحظي نفسه مسؤولية app/api/v1/meetings.py::
meeting_live_socket + app/core/meeting_realtime.py، هذا الملف فقط يحفظ
الحالة بقاعدة البيانات)، مراجعة، اعتماد، وتوقيع إلكتروني بعد اكتماله
تلقائيًا يُقفَل ويُؤرشف. راجعي رأس db/migrations/0029_meeting_minutes.sql
وapp/models/meeting_minutes.py للتصميم الكامل والقرارات الموثّقة.

مرجع التصميم: تصميم Lovable المرفق من لمى (minutes.id.tsx) — آلة الحالة
والتدفق هنا مطابقان له حرفيًا، مع تبسيط واحد موثّق أدناه (submit_review
ينتظر كل المراجعين فعليًا بدل نسخة Lovable المبسّطة اللي تعتمد الكل
بضغطة واحدة).

التفويض: نفس النمط الهجين المستخدَم بـmeeting_service.py (System Role
scope **أو** Committee Role permission، عبر committee_service.
get_committee_role_permission_codes) — أكواد الصلاحيات (minutes.*) كانت
مزروعة أصلًا بكتالوج الصلاحيات منذ 0006_roles_permissions.sql، هذا أول
استخدام فعلي لها.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.committee import Committee
from app.models.meeting import Meeting, MeetingStatus
from app.models.meeting_minutes import (
    MeetingMinutes,
    MeetingMinutesReviewer,
    MeetingMinutesReviewStatus,
    MeetingMinutesSignature,
    MeetingMinutesStage,
)
from app.models.role import Role, RolePermission
from app.models.user import User
from app.services import committee_service, meeting_service

# ============================== القوالب الثابتة (Hardcoded) ==============================
# لا واجهة إدارة قوالب بعد (لمى أجّلت هذا القرار صراحة لمرحلة لاحقة) —
# ثلاثة قوالب فقط، بأسماء لمى الصريحة. الفرق بينها Layout فعلي لا مجرد
# اسم: executive/formal أقسامهما ثابتة (قائمة نصوص أدناه)، بينما detailed
# ليس له أقسام ثابتة إطلاقًا — أقسامه تُبنى ديناميكيًا بند بند من جدول
# أعمال الاجتماع الفعلي (_build_sections_from_template أدناه)، فكل محضر
# "تفصيلي" له عدد أقسام مختلف بحسب عدد بنود اجتماعه.

MINUTES_TEMPLATES: dict[str, dict] = {
    "executive": {
        "id": "executive",
        "name": "القالب التنفيذي",
        "description": "قالب مختصر وتنفيذي يركّز على الملخص التنفيذي وأبرز النقاط دون تفاصيل المداولات.",
        "sections": [
            "الملخص التنفيذي",
            "أبرز النقاط",
            "القرارات",
            "المهام",
            "النقاط المعلقة",
            "المتابعة القادمة",
        ],
    },
    "formal": {
        "id": "formal",
        "name": "القالب الرسمي",
        "description": "قالب رسمي كامل يوثّق كل مجريات الاجتماع من الحضور حتى التوقيعات.",
        "sections": [
            "بيانات الاجتماع",
            "الحضور",
            "جدول الأعمال",
            "مجريات المناقشة",
            "القرارات والتوصيات",
            "المهام والإجراءات",
            "التوصيات",
            "الاجتماع القادم",
            "التوقيعات",
        ],
    },
    "detailed": {
        "id": "detailed",
        "name": "القالب التفصيلي",
        "description": "يربط كل بند من جدول الأعمال بمناقشته وقراره ومهامه — قسم مستقل لكل بند فعلي بالاجتماع.",
        "sections": [],  # ديناميكي — راجعي _build_sections_from_template.
    },
}


class MinutesNotFoundError(Exception):
    """المحضر (أو الاجتماع المرتبط به) غير موجود — تُترجَم إلى 404."""


class MinutesForbiddenError(Exception):
    """محاولة إجراء غير مسموح بها لهذا المستخدم تحديدًا — تُترجَم إلى 403."""


class MinutesInvalidStateError(Exception):
    """محاولة إجراء لا تناسب مرحلة المحضر الحالية — تُترجَم إلى 409."""


class MinutesValidationError(Exception):
    """خطأ تحقق من بيانات العمل — تُترجَم إلى 400."""


# ============================== تحميل وتحقق الصلاحية ==============================


async def _load_committee(db: AsyncSession, committee_id: uuid.UUID) -> Committee:
    result = await db.execute(select(Committee).where(Committee.committee_id == committee_id))
    committee = result.scalar_one_or_none()
    if committee is None:
        raise MinutesNotFoundError("اللجنة غير موجودة")
    return committee


async def _load_meeting(db: AsyncSession, meeting_id: uuid.UUID) -> Meeting:
    # تحقيق أداء لاما 2026-09-13 — إصلاح N+1 الثاني (بعد _load_minutes_row
    # بتاريخ 2026-09-12): committee وchair/members الفرعيين كانوا يُحمَّلون
    # عبر lazy="selectin" الافتراضي بدون تنسيق استعلام واحد وقت الجلب —
    # التعليق القديم على _load_meeting_and_committee أدناه كان يفترض خطأً
    # أن lazy="selectin" يعني تحميل committee ضمن نفس استعلام meeting
    # (batched تلقائيًا) — هذا غير صحيح: lazy="selectin" كإستراتيجية
    # افتراضية (بدون .options(selectinload(...)) وقت الاستعلام) يُطلق
    # round trip منفصل خاص به عند أول وصول لـmeeting.committee، ثم كل
    # علاقة فرعية تُلمَس بعده (chair، members) تُطلق round trip خاص بها
    # أيضًا — بالضبط نفس آلية N+1 المؤكَّدة سابقًا على owner/reviewers/
    # signatures، لكن هنا على مسار التحقق من الصلاحية الذي يمر منه كل
    # استدعاء لهذه الدالة (9 مواقع استخدام). الحل: .options(selectinload)
    # صريح هنا يجمّع committee+chair+members في استعلامين ثابتين بدل
    # تحميل كل علاقة لحالها عند أول استخدام لها لاحقًا بالكود.
    result = await db.execute(
        select(Meeting)
        .where(Meeting.meeting_id == meeting_id)
        .options(
            selectinload(Meeting.committee).selectinload(Committee.chair),
            selectinload(Meeting.committee).selectinload(Committee.members),
        )
    )
    meeting = result.scalar_one_or_none()
    if meeting is None or meeting.is_deleted:
        raise MinutesNotFoundError("الاجتماع غير موجود")
    # إصلاح 2026-09-09 (بلاغ لاما — اجتماع منتهي وقته المجدول يظل يظهر
    # "الاجتماع لم ينتهِ بعد" بقسم المحاضر): بدون هذا السطر كان status
    # يُقرأ خامًا من القاعدة كما هو، وقد يبقى عالقًا على upcoming/ongoing
    # لو ما مرّ على نفس الاجتماع أي طلب كتابة (تعديل/انضمام) يُحدّثه —
    # meeting_service.sync_meeting_status هي نفس دالة التحويل الكسول
    # المستخدَمة بمسار "الاجتماعات" العادي (راجعي docstring هناك)،
    # أصبحت عامة تحديدًا عشان تُستدعى هنا وتُبقي الحالتين متطابقتين.
    meeting_service.sync_meeting_status(meeting)
    return meeting


def _all_committee_members(committee: Committee) -> list[User]:
    """كل أعضاء اللجنة بمن فيهم رئيسها — نفس مصدر التوقيع/المراجعة
    المتوقَّع (مطابق تمامًا لـmeeting_service._all_committee_members،
    نسخة محلية لأن دوال meeting_service بـ_ خاصة بملفها فقط)."""
    members = list(committee.members)
    if committee.chair is not None and committee.chair_user_id not in {m.user_id for m in members}:
        members.append(committee.chair)
    return members


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


async def _require_access(
    db: AsyncSession, actor: User, committee: Committee, code: str, message: str
) -> None:
    if not await _has_access(db, actor, committee, code):
        raise MinutesForbiddenError(message)


async def _load_meeting_and_committee(db: AsyncSession, meeting_id: uuid.UUID) -> tuple[Meeting, Committee]:
    # تصحيح 2026-09-13: التعليق القديم هنا كان يفترض أن committee تُحمَّل
    # ضمن نفس استعلام meeting تلقائيًا بمجرد lazy="selectin" — تبيّن بالقياس
    # الفعلي إن هذا غير صحيح (نفس مفهوم N+1 المكتشف بـ_load_minutes_row).
    # الإصلاح الحقيقي الآن داخل _load_meeting نفسها عبر selectinload صريح.
    meeting = await _load_meeting(db, meeting_id)
    committee = meeting.committee
    return meeting, committee


def _require_meeting_finished(meeting: Meeting) -> None:
    """FR-MIN-001: إعداد المحضر لا يبدأ إلا بعد انتهاء الاجتماع."""
    if meeting.status not in (MeetingStatus.finished, MeetingStatus.recorded):
        raise MinutesInvalidStateError("لا يمكن إعداد محضر الاجتماع إلا بعد انتهائه")


# تحقيق أداء لاما 2026-09-12 — إصلاح N+1 (مؤكَّد بقياس فعلي: 47 استعلام
# متسلسل، 17.5 ثانية إجمالًا على /minutes حقيقي). owner/reviewers/
# signatures وما يتفرّع منها (user → role → role_permission_links →
# permission، وuser → job_title) كلها lazy="selectin" بالموديلات — هذا
# يمنع N+1 فقط لو الوالد تحمّل ضمن استعلام واحد مجمّع (selectinload
# صريح). بدونه (كالحالة السابقة هنا) كل reviewer/signature يتحمّل لحاله
# ثم user لحاله ثم role لحاله... سلسلة متداخلة. الحل: تحميل كل شيء عبر
# .options() بنفس الاستعلام الأصلي فيتحوّل لعدد صغير وثابت من الدفعات
# (batch واحد لكل مستوى علاقة) بدل واحد لكل عضو/مراجع/موقّع.
def _user_eager_options(user_relationship):
    return (
        user_relationship.selectinload(User.role).selectinload(Role.role_permission_links).selectinload(RolePermission.permission),
        user_relationship.selectinload(User.job_title),
    )


async def _load_minutes_row(db: AsyncSession, meeting_id: uuid.UUID) -> MeetingMinutes | None:
    # علامة تحقّق مؤقتة (تحقيق أداء لاما 2026-09-12): تثبت إن هذا الإصدار
    # فعليًا هو اللي يشتغل بالإنتاج، لا نفترض بس من "Live" باللوحة —
    # نفس درس الكاش القديم اللي صار بالتحقيق السابق.
    from app.core import perf_probe as _perf_probe

    _perf_probe.mark("minutes.eager_load_v2_active")

    stmt = (
        select(MeetingMinutes)
        .where(MeetingMinutes.meeting_id == meeting_id)
        .options(
            *_user_eager_options(selectinload(MeetingMinutes.owner)),
            *_user_eager_options(
                selectinload(MeetingMinutes.reviewers).selectinload(MeetingMinutesReviewer.user)
            ),
            *_user_eager_options(
                selectinload(MeetingMinutes.signatures).selectinload(MeetingMinutesSignature.user)
            ),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _load_minutes_or_404(db: AsyncSession, meeting_id: uuid.UUID) -> MeetingMinutes:
    minutes = await _load_minutes_row(db, meeting_id)
    if minutes is None:
        raise MinutesNotFoundError("لم يبدأ إعداد محضر لهذا الاجتماع بعد")
    return minutes


async def load_meeting(db: AsyncSession, meeting_id: uuid.UUID) -> Meeting:
    """تحميل عام (بدون _) للاجتماع — تستخدمه طبقة الـAPI فقط لبناء نص
    الإشعارات بعد نجاح send_for_signature/sign_minutes (عنوان الاجتماع)،
    بلا تكرار فحص صلاحية meetings.view (الفعل نفسه محمي أصلًا بصلاحية
    minutes.* المناسبة قبل الوصول لهذه النقطة)."""
    return await _load_meeting(db, meeting_id)


# ============================== القوالب ==============================


def list_templates() -> list[dict]:
    return list(MINUTES_TEMPLATES.values())


async def list_templates_for_meeting(
    db: AsyncSession, *, meeting_id: uuid.UUID, actor: User
) -> list[dict]:
    """FR-MIN-003 — عرض قوالب المحاضر المعتمدة فقط (بدون إنشاء صف محضر
    كأثر جانبي، بخلاف get_or_create_minutes أدناه — الاختيار الفعلي هو
    ما ينشئ الصف)."""
    meeting, committee = await _load_meeting_and_committee(db, meeting_id)
    _require_meeting_finished(meeting)
    await _require_access(db, actor, committee, "minutes.templates.view", "ليست لديك صلاحية عرض قوالب المحاضر")
    return list_templates()


def _build_sections_from_template(template_id: str, meeting: Meeting) -> list[dict]:
    template = MINUTES_TEMPLATES[template_id]
    if template_id == "detailed":
        agenda_items = sorted(meeting.agenda_items, key=lambda a: a.sort_order)
        if not agenda_items:
            # لا بنود أجندة مسجّلة — نتجنّب محضرًا بلا أي قسم إطلاقًا.
            return [
                {"id": str(uuid.uuid4()), "title": "ملاحظات عامة", "body": "", "order": 0}
            ]
        return [
            {
                "id": str(uuid.uuid4()),
                "title": item.title,
                "body": "المناقشة:\n\nالقرار:\n\nالمهام المرتبطة:\n",
                "order": index,
            }
            for index, item in enumerate(agenda_items)
        ]
    return [
        {"id": str(uuid.uuid4()), "title": title, "body": "", "order": index}
        for index, title in enumerate(template["sections"])
    ]


async def select_template(
    db: AsyncSession, *, meeting_id: uuid.UUID, actor: User, template_id: str
) -> MeetingMinutes:
    if template_id not in MINUTES_TEMPLATES:
        raise MinutesValidationError("قالب غير معروف")

    meeting, committee = await _load_meeting_and_committee(db, meeting_id)
    _require_meeting_finished(meeting)
    await _require_access(
        db, actor, committee, "minutes.templates.select", "ليست لديك صلاحية اختيار قالب المحضر"
    )

    minutes = await _load_minutes_row(db, meeting_id)
    if minutes is None:
        minutes = MeetingMinutes(meeting_id=meeting_id, owner_user_id=actor.user_id)
        db.add(minutes)
    elif minutes.stage not in (MeetingMinutesStage.none, MeetingMinutesStage.preparing):
        raise MinutesInvalidStateError("لا يمكن تغيير القالب بعد إرسال المحضر للمراجعة")

    minutes.template_id = template_id
    minutes.sections = _build_sections_from_template(template_id, meeting)
    minutes.stage = MeetingMinutesStage.preparing
    if minutes.owner_user_id is None:
        minutes.owner_user_id = actor.user_id

    # تحديث 2026-09-10 (قرار لاما — إلغاء اختيار المراجعين يدويًا،
    # المراجعة تصير "مفتوحة" لكل أعضاء اللجنة تلقائيًا بمجرد اختيار
    # القالب، بمن فيهم رئيسها): تُعبَّأ مرة واحدة فقط (لو فارغة) — إعادة
    # اختيار القالب لاحقًا لا تصفّر مراجعات موجودة أصلًا.
    if not minutes.reviewers:
        minutes.reviewers = [
            MeetingMinutesReviewer(minutes_id=minutes.minutes_id, user_id=member.user_id)
            for member in _all_committee_members(committee)
        ]

    await db.commit()
    return await _load_minutes_or_404(db, meeting_id)


# ============================== عرض / تعديل المحتوى ==============================


async def get_or_create_minutes(db: AsyncSession, *, meeting_id: uuid.UUID, actor: User) -> MeetingMinutes:
    meeting, committee = await _load_meeting_and_committee(db, meeting_id)
    await _require_access(db, actor, committee, "minutes.view", "ليست لديك صلاحية لعرض محضر هذا الاجتماع")

    minutes = await _load_minutes_row(db, meeting_id)
    if minutes is not None:
        return minutes

    _require_meeting_finished(meeting)
    minutes = MeetingMinutes(meeting_id=meeting_id)
    db.add(minutes)
    await db.commit()
    return await _load_minutes_or_404(db, meeting_id)


async def update_sections(
    db: AsyncSession, *, meeting_id: uuid.UUID, actor: User, sections: list[dict]
) -> MeetingMinutes:
    meeting, committee = await _load_meeting_and_committee(db, meeting_id)
    await _require_access(db, actor, committee, "minutes.update", "ليست لديك صلاحية تعديل محتوى المحضر")

    minutes = await _load_minutes_or_404(db, meeting_id)
    if minutes.stage != MeetingMinutesStage.preparing:
        raise MinutesInvalidStateError("لا يمكن تعديل المحضر في مرحلته الحالية")

    minutes.sections = sections
    await db.commit()
    return await _load_minutes_or_404(db, meeting_id)


# ============================== المراجعة ==============================


async def submit_review(
    db: AsyncSession,
    *,
    meeting_id: uuid.UUID,
    actor: User,
    approve: bool,
    comment: str | None,
) -> MeetingMinutes:
    meeting, committee = await _load_meeting_and_committee(db, meeting_id)
    await _require_access(db, actor, committee, "minutes.approve", "ليست لديك صلاحية اعتماد المراجعة")

    minutes = await _load_minutes_or_404(db, meeting_id)
    if minutes.stage != MeetingMinutesStage.preparing:
        raise MinutesInvalidStateError("المحضر ليس بمرحلة تسمح بالمراجعة")

    reviewer_row = next((r for r in minutes.reviewers if r.user_id == actor.user_id), None)
    if reviewer_row is None:
        raise MinutesForbiddenError("لست ضمن مراجعي هذا المحضر")

    # تحديث 2026-09-10 (قرار لاما — المراجعة "مفتوحة" لكل الأعضاء تلقائيًا،
    # ولا تُستخدم كبوابة أصلًا): تسجيل رأي/ملاحظة المراجع فقط، بلا أي أثر
    # على مرحلة المحضر — لا إعادة تلقائية للتعديل عند الرفض، ولا نقل
    # تلقائي عند اكتمال الموافقات. رئيس اللجنة يقدر يعتمد من "التحضير"
    # مباشرة في أي وقت يبيه، بغض النظر عن حالة المراجعين (راجعي
    # approve_minutes أدناه).
    reviewer_row.status = (
        MeetingMinutesReviewStatus.approved if approve else MeetingMinutesReviewStatus.returned
    )
    reviewer_row.comment = comment
    reviewer_row.reviewed_at = datetime.now(UTC)

    await db.commit()
    return await _load_minutes_or_404(db, meeting_id)


# ============================== الاعتماد ==============================


async def approve_minutes(db: AsyncSession, *, meeting_id: uuid.UUID, actor: User) -> MeetingMinutes:
    meeting, committee = await _load_meeting_and_committee(db, meeting_id)
    await _require_access(db, actor, committee, "minutes.approve", "ليست لديك صلاحية اعتماد المحضر")

    minutes = await _load_minutes_or_404(db, meeting_id)
    # تحديث 2026-09-10 (قرار لاما): الاعتماد صار متاحًا مباشرة من مرحلة
    # "التحضير" في أي وقت يقرره رئيس اللجنة — بدون انتظار اكتمال مراجعة
    # الأعضاء وبدون المرور بمرحلتي "المراجعة"/"الاعتماد" القديمتين كبوابة.
    # أبقينا review وapproval هنا فقط توافقًا رجعيًا مع أي محاضر كانت فعلًا
    # بهذه المرحلة من قبل هذا التحديث.
    if minutes.stage not in (
        MeetingMinutesStage.preparing,
        MeetingMinutesStage.review,
        MeetingMinutesStage.approval,
    ):
        raise MinutesInvalidStateError("المحضر ليس بمرحلة تسمح بالاعتماد")

    minutes.stage = MeetingMinutesStage.signature
    minutes.approved_at = datetime.now(UTC)

    await db.commit()
    return await _load_minutes_or_404(db, meeting_id)


async def return_for_edit(
    db: AsyncSession, *, meeting_id: uuid.UUID, actor: User, comment: str | None
) -> MeetingMinutes:
    """إعادة المحضر للتعديل — تُستخدم الآن كطريقة "التراجع" الوحيدة بعد
    الاعتماد (approve_minutes صار يقفز مباشرة من "التحضير" إلى "التوقيع"،
    فما فيه مرحلة "اعتماد" وسيطة يُنتظر فيها الرد — الإعادة هنا تلغي
    اعتمادًا سابقًا وترجّع المحضر قابلًا للتعديل من جديد)."""
    meeting, committee = await _load_meeting_and_committee(db, meeting_id)
    await _require_access(db, actor, committee, "minutes.approve", "ليست لديك صلاحية إعادة المحضر للتعديل")

    minutes = await _load_minutes_or_404(db, meeting_id)
    if minutes.stage not in (MeetingMinutesStage.approval, MeetingMinutesStage.signature):
        raise MinutesInvalidStateError("المحضر ليس بمرحلة تسمح بالإعادة للتعديل")

    minutes.stage = MeetingMinutesStage.preparing
    minutes.sent_to_review_at = None
    for r in minutes.reviewers:
        r.status = MeetingMinutesReviewStatus.pending
        r.comment = comment if r.comment is None else r.comment
        r.reviewed_at = None

    await db.commit()
    return await _load_minutes_or_404(db, meeting_id)


# ============================== التوقيع الإلكتروني ==============================


async def send_for_signature(db: AsyncSession, *, meeting_id: uuid.UUID, actor: User) -> MeetingMinutes:
    meeting, committee = await _load_meeting_and_committee(db, meeting_id)
    await _require_access(db, actor, committee, "minutes.approve", "ليست لديك صلاحية إرسال المحضر للتوقيع")

    minutes = await _load_minutes_or_404(db, meeting_id)
    if minutes.stage != MeetingMinutesStage.signature:
        raise MinutesInvalidStateError("المحضر ليس بمرحلة التوقيع")

    if not minutes.signatures:
        minutes.signatures = [
            MeetingMinutesSignature(minutes_id=minutes.minutes_id, user_id=member.user_id)
            for member in _all_committee_members(committee)
        ]
    minutes.sent_for_signature_at = datetime.now(UTC)

    await db.commit()
    return await _load_minutes_or_404(db, meeting_id)


async def sign_minutes(
    db: AsyncSession, *, meeting_id: uuid.UUID, actor: User, signature_image: str
) -> MeetingMinutes:
    meeting, committee = await _load_meeting_and_committee(db, meeting_id)
    await _require_access(db, actor, committee, "minutes.sign", "ليست لديك صلاحية التوقيع على هذا المحضر")

    minutes = await _load_minutes_or_404(db, meeting_id)
    if minutes.stage != MeetingMinutesStage.signature:
        raise MinutesInvalidStateError("المحضر ليس بمرحلة التوقيع")

    signature_row = next((s for s in minutes.signatures if s.user_id == actor.user_id), None)
    if signature_row is None:
        raise MinutesForbiddenError("لست ضمن الموقّعين المتوقَّعين لهذا المحضر")

    signature_row.signature_image = signature_image
    signature_row.signed_at = datetime.now(UTC)

    if all(s.signed_at is not None for s in minutes.signatures):
        minutes.stage = MeetingMinutesStage.completed
        minutes.completed_at = datetime.now(UTC)

    await db.commit()
    return await _load_minutes_or_404(db, meeting_id)
