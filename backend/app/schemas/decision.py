"""
الهدف:
Pydantic Schemas الخاصة بوحدة "إدارة القرارات" (القرارات المستقلة فقط).
راجعي رأس db/migrations/0021_decisions_schema.sql للاجتهادات الموثّقة.

تحديث 2026-09-07 (قرار صريح من صاحبة المشروع: "الي يحدد بيانات التصويت
رئيس اللجنة بس والأعضاء يقررون"): خيارات التصويت (DecisionVoteOptionCreate)
تُكتب من رئيسة اللجنة عند فتح التصويت (DecisionOpenVoting)، بدل أن تكون
موافق/غير موافق ثابتة بالكود — راجعي رأس db/migrations/0025_decision_vote_options.sql.

تحديث 2026-11-03 (قرار صاحب المشروع بعد مقارنة منصات الحوكمة): رجعت خيارات
التصويت ثابتة: موافق / غير موافق / ممتنع. DecisionOpenVoting ما يستقبل
options بعد الآن (أي options يرسلها عميل قديم تُتجاهَل بصمت — extra="ignore"
الافتراضي بـPydantic)، والخيارات تُنشأ بالكامل في decision_service/voting.py.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.decision import DecisionClassification, DecisionStatus
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
    # لو أُرسل من داخل غرفة الاجتماع (لوحة "القرارات" الجديدة) — يُربط
    # القرار بالاجتماع المصدر تلقائيًا. اختياري: القرارات المستقلة من
    # شاشة "إدارة القرارات" العامة تُرسله فارغًا (None). لا يُتحقَّق هنا
    # أن meeting_id ينتمي فعليًا لنفس committee_id — تحقق ذلك بطبقة
    # الخدمة (راجعي decision_service.create_decision).
    meeting_id: uuid.UUID | None = None
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


class DecisionOpenVoting(BaseModel):
    """
    فتح التصويت — الخيارات ثابتة (موافق / غير موافق / ممتنع، تحديث
    2026-11-03) ولا تُرسل من العميل. voting_deadline اختياري (راجعي ملاحظة
    التصميم (2) بـ0021).
    """

    voting_deadline: datetime | None = None


class DecisionVoteCast(BaseModel):
    """التصويت لخيار محدَّد من خيارات هذا القرار تحديدًا (يُتحقَّق منه بطبقة الخدمة)."""

    option_id: uuid.UUID
    # إلزامي فقط عند اختيار خيار "ممتنع" الثابت (is_abstain) — يُتحقَّق
    # منه بطبقة الخدمة (decision_service.voting.cast_vote)، ويُتجاهل
    # (يُخزَّن None) لأي خيار آخر.
    reason: str | None = Field(default=None, max_length=2000)


class DecisionVoteOptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    option_id: uuid.UUID
    label: str
    is_approving: bool
    is_abstain: bool
    sort_order: int


class DecisionVoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    voter: CommitteeMemberUserOut
    option: DecisionVoteOptionOut
    # مقيَّد برئيسة اللجنة أو صاحب الصوت نفسه فقط — راجعي
    # decision_service.access._redact_votes_if_unauthorized.
    reason: str | None
    voted_at: datetime


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    decision_id: uuid.UUID
    committee_id: uuid.UUID
    meeting_id: uuid.UUID | None
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
    vote_options: list[DecisionVoteOptionOut]
    votes: list[DecisionVoteOut]
    # من لم يصوّت بعد من أعضاء اللجنة (ورئيسها) — لرئيسة اللجنة فقط، وإلا
    # [] دائمًا (راجعي access._redact_votes_if_unauthorized).
    non_voters: list[CommitteeMemberUserOut] = []
    created_at: datetime
    updated_at: datetime


class DecisionAttachmentOut(BaseModel):
    """
    ملف مرفق اختياري بقرار (تجميعة من Document + document_links، بنفس
    نمط MeetingAttachmentOut بوحدة الاجتماعات بالضبط) — رئيسة اللجنة فقط
    ترفقه، عادةً عند الإنشاء (راجعي decision_service.attachments).
    """

    document_id: uuid.UUID
    title: str
    file_name: str
    mime_type: str
    file_size_bytes: int
    uploaded_by: CommitteeMemberUserOut
    linked_at: datetime
