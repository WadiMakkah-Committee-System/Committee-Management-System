"""
الهدف:
Pydantic Schemas الخاصة بوحدة "إدارة القرارات" (القرارات المستقلة فقط).
راجعي رأس db/migrations/0021_decisions_schema.sql للاجتهادات الموثّقة.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.decision import DecisionClassification, DecisionStatus, DecisionVoteChoice
from app.schemas.committee import CommitteeMemberUserOut


class DecisionCreate(BaseModel):
    """
    إنشاء قرار مستقل جديد (FR-001 مسار "الإصدار المباشر" فقط — بدون مصدر
    اجتماع، يُبنى لاحقًا). لا يوجد حقل منفذين هنا — كل أعضاء اللجنة
    (بمن فيهم رئيسها) يُضافون تلقائيًا كمنفذين، بنفس مبدأ مشاركي الاجتماع
    (قرار صاحبة المشروع 2026-09-02، مُعدَّل من اختيار يدوي إلى تلقائي
    بالكامل — راجعي decision_service.create_decision).
    """

    committee_id: uuid.UUID
    title: str = Field(min_length=2, max_length=255)
    classification: DecisionClassification
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _end_after_start(self) -> "DecisionCreate":
        if self.end_date < self.start_date:
            raise ValueError("تاريخ نهاية التنفيذ يجب أن يكون بعد تاريخ البداية أو يساويه")
        return self


class DecisionUpdate(BaseModel):
    """
    تعديل بيانات قرار — متاح فقط بحالة pending (قبل فتح التصويت أو
    الاعتماد المباشر). لا يوجد حقل منفذين — يُعاد اشتقاقهم تلقائيًا من
    عضوية اللجنة عند أي تعديل، بنفس منطق الإنشاء.
    """

    title: str | None = Field(default=None, min_length=2, max_length=255)
    classification: DecisionClassification | None = None
    start_date: date | None = None
    end_date: date | None = None


class DecisionVoteCast(BaseModel):
    choice: DecisionVoteChoice


class DecisionOpenVoting(BaseModel):
    """فتح التصويت — voting_deadline اختياري (راجعي ملاحظة التصميم (2) بالـmigration)."""

    voting_deadline: datetime | None = None


class DecisionVoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    voter: CommitteeMemberUserOut
    choice: DecisionVoteChoice
    voted_at: datetime


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    decision_id: uuid.UUID
    committee_id: uuid.UUID
    title: str
    classification: DecisionClassification
    status: DecisionStatus
    start_date: date
    end_date: date
    voting_opened_at: datetime | None
    voting_deadline: datetime | None
    voting_closed_at: datetime | None
    rejection_reason: str | None
    creator: CommitteeMemberUserOut
    assignees: list[CommitteeMemberUserOut]
    votes: list[DecisionVoteOut]
    created_at: datetime
    updated_at: datetime
