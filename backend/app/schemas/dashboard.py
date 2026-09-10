"""
الهدف:
Pydantic Schemas لوحدة "لوحة التحكم" — تجميع إحصائيات وقوائم مختصرة من
الوحدات الموجودة فعليًا (اللجان، الاجتماعات، القرارات، المهام، الوثائق)،
كلها مفلترة حسب صلاحيات المستخدم الفعلية بالضبط (نفس منطق كل وحدة على
حدة، بلا تكرار أو إعادة تنفيذ لمنطق النطاق own/department/all).

راجعي رأس app/services/dashboard_service.py للتفصيل الكامل ولماذا لا
يوجد Schema لقسم "التقارير" (مؤجَّل — قرار صريح من صاحبة المشروع
2026-09-08، راجعي محضر ذلك القرار بسجل GitHub لهذا التاريخ).
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.meeting import MeetingMode
from app.models.task import TaskStatus


class DashboardCommitteeItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    committee_id: uuid.UUID
    name: str


class DashboardMeetingItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    meeting_id: uuid.UUID
    title: str
    scheduled_at: datetime
    mode: MeetingMode
    committee_name: str


class DashboardDecisionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    decision_id: uuid.UUID
    title: str
    committee_name: str
    voting_deadline: datetime | None


class DashboardTaskItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: uuid.UUID
    title: str
    status: TaskStatus
    end_date: date
    committee_name: str


class DashboardDocumentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    title: str
    created_at: datetime


class DashboardSummary(BaseModel):
    """
    استجابة GET /dashboard/summary — راجعي docstring
    dashboard_service.get_dashboard_summary لتفصيل حساب كل حقل. كل عدّاد
    (`*_count`) يعكس الإجمالي الفعلي المتاح لهذا المستخدم تحديدًا، وليس
    طول قائمة المعاينة (`*_preview`) التي تُقتَصر على عناصر قليلة للعرض
    السريع فقط (راجعي _PREVIEW_LIMIT بالخدمة).
    """

    committees_count: int
    committees_preview: list[DashboardCommitteeItem]

    upcoming_meetings_count: int
    upcoming_meetings_preview: list[DashboardMeetingItem]

    pending_votes_count: int
    pending_votes_preview: list[DashboardDecisionItem]

    open_tasks_count: int
    open_tasks_preview: list[DashboardTaskItem]

    documents_count: int
    recent_documents_preview: list[DashboardDocumentItem]
