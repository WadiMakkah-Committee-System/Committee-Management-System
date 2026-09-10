"""
الهدف:
منطق العمل لوحدة "لوحة التحكم" — تجميع إحصائيات وقوائم مختصرة من الوحدات
الموجودة فعليًا، مطابقة لمتطلبات SRS/BRS العامة حول لوحة التحكم:

- BRS (بند أهداف عام): "توفير لوحة تحكم تعرض إحصائيات وتقارير عن اللجان
  والاجتماعات".
- SRS (4 حالات استخدام): (1) توجيه المستخدم للوحة التحكم بعد تسجيل
  الدخول، (2) عرض الخيارات المسموح بها حسب الصلاحيات، (3) عرض اللجان
  المصرح بها للمستخدم، (4) عرض التقارير التي يملك صلاحية الوصول إليها.

قرار نطاق صريح من صاحبة المشروع (2026-09-08): "التقارير" (حالة الاستخدام
الرابعة) مؤجَّلة بالكامل لمرحلة منفصلة — هذه الوحدة تغطي فقط (2) و(3)
أعلاه (الإحصائيات + قوائم مختصرة)، بالإضافة إلى اجتماعات قادمة وقرارات
بانتظار تصويت المستخدم ومهام مفتوحة (امتداد طبيعي لروح البند العام
بالـBRS "إحصائيات عن اللجان والاجتماعات"، مُوسَّع ليشمل بقية الوحدات
الفعلية بالنظام اليوم — القرارات والمهام والوثائق لم تكن موجودة أصلًا
وقت كتابة SRS/BRS).

مبدأ التصميم الجوهري: **لا تكرار لمنطق الصلاحيات/النطاق هنا إطلاقًا** —
كل قسم يستدعي دالة list_* الحقيقية من خدمته الأصلية (committee_service،
meeting_service، decision_service، task_service، document_service) بنفس
الطريقة التي تستدعيها بها راوتات تلك الوحدات تمامًا، ثم يُلخِّص/يُصفّي
فوق النتيجة المُرجَعة فقط (فرز بالتاريخ، اقتصاص لعدد صغير للمعاينة).
هذا يضمن تطابق ما يظهر بلوحة التحكم مع ما يظهر فعليًا بكل صفحة على حدة
حرفيًا (لا احتمال لثغرة تسريب صلاحيات جديدة هنا — أي إصلاح صلاحيات
مستقبلي بأي وحدة أصلية ينعكس هنا تلقائيًا بلا أي تعديل إضافي).
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision import Decision, DecisionClassification, DecisionStatus
from app.models.meeting import Meeting, MeetingStatus
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.dashboard import (
    DashboardCommitteeItem,
    DashboardDecisionItem,
    DashboardDocumentItem,
    DashboardMeetingItem,
    DashboardSummary,
    DashboardTaskItem,
)
from app.services import committee_service, decision_service, document_service, meeting_service, task_service

_PREVIEW_LIMIT = 5


def _upcoming_meetings(meetings: list[Meeting]) -> list[Meeting]:
    now = datetime.now(UTC)
    upcoming = [
        m for m in meetings if m.status == MeetingStatus.upcoming and m.scheduled_at >= now
    ]
    upcoming.sort(key=lambda m: m.scheduled_at)
    return upcoming


def _decisions_pending_my_vote(decisions: list[Decision], actor: User) -> list[Decision]:
    """
    قرارات خاضعة للتصويت، مفتوحة حاليًا، ولم يصوّت عليها actor بعد.

    ملاحظة تصميم مهمة: decision.votes هنا قد تكون مُحرَّرة أصلًا (راجعي
    decision_service._redact_votes_if_unauthorized) لتحتوي فقط صوت actor
    الشخصي إن وُجد (لمن لا يملك decisions.vote.view_result) — هذا لا يكسر
    الفحص هنا إطلاقًا: نبحث فقط عن وجود صوت لـactor.user_id تحديدًا، وهو
    مضمون الظهور بالقائمة المُحرَّرة لو صوّت فعلًا (التحرير يُبقي صوته
    دائمًا، يحذف فقط أصوات البقية — راجعي رأس تلك الدالة).
    """
    pending: list[Decision] = []
    for d in decisions:
        if d.classification != DecisionClassification.voting or d.status != DecisionStatus.voting:
            continue
        if any(v.user_id == actor.user_id for v in d.votes):
            continue
        pending.append(d)
    pending.sort(key=lambda d: d.voting_deadline or datetime.max.replace(tzinfo=UTC))
    return pending


def _open_tasks(tasks: list[Task]) -> list[Task]:
    open_tasks = [t for t in tasks if t.status != TaskStatus.completed]
    open_tasks.sort(key=lambda t: t.end_date)
    return open_tasks


async def get_dashboard_summary(db: AsyncSession, *, actor: User) -> DashboardSummary:
    committee_scope = actor.scope_for("committees.view") or "own"
    committees = await committee_service.list_committees(db, actor=actor, scope=committee_scope)
    meetings = await meeting_service.list_meetings(db, actor=actor)
    decisions = await decision_service.list_decisions(db, actor=actor)
    tasks = await task_service.list_tasks(db, actor=actor)
    documents = await document_service.list_documents(db, current_user=actor)

    upcoming_meetings = _upcoming_meetings(meetings)
    pending_votes = _decisions_pending_my_vote(decisions, actor)
    open_tasks = _open_tasks(tasks)

    return DashboardSummary(
        committees_count=len(committees),
        committees_preview=[
            DashboardCommitteeItem.model_validate(c) for c in committees[:_PREVIEW_LIMIT]
        ],
        upcoming_meetings_count=len(upcoming_meetings),
        upcoming_meetings_preview=[
            DashboardMeetingItem(
                meeting_id=m.meeting_id,
                title=m.title,
                scheduled_at=m.scheduled_at,
                mode=m.mode,
                committee_name=m.committee.name,
            )
            for m in upcoming_meetings[:_PREVIEW_LIMIT]
        ],
        pending_votes_count=len(pending_votes),
        pending_votes_preview=[
            DashboardDecisionItem(
                decision_id=d.decision_id,
                title=d.title,
                committee_name=d.committee.name,
                voting_deadline=d.voting_deadline,
            )
            for d in pending_votes[:_PREVIEW_LIMIT]
        ],
        open_tasks_count=len(open_tasks),
        open_tasks_preview=[
            DashboardTaskItem(
                task_id=t.task_id,
                title=t.title,
                status=t.status,
                end_date=t.end_date,
                committee_name=t.committee.name,
            )
            for t in open_tasks[:_PREVIEW_LIMIT]
        ],
        documents_count=len(documents),
        recent_documents_preview=[
            DashboardDocumentItem.model_validate(doc) for doc in documents[:_PREVIEW_LIMIT]
        ],
    )
