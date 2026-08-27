"""
الهدف:
Pydantic Schemas الخاصة بوحدة "طلبات تشكيل اللجان" (Committee Formation
Requests) — Phase 2 (Backend APIs). تحدّد شكل بيانات الطلبات والردود
لواجهات RF-COM-100 → RF-COM-700 (SRS)، وتفصل شكل الـ API عن نموذج قاعدة
البيانات (ORM) في app/models/committee_request.py و app/models/committee.py.

المسؤولية:
التحقق من صحة المدخلات (تواريخ، أعضاء مقترحون) وتحديد الحقول المُرجعة
للعميل حسب الحالة (مثال: rejection_reason لا معنى له إلا بعد الرفض).
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.committee_request import CommitteeRequestStatus


class CommitteeMemberUserOut(BaseModel):
    """شكل مختصر لبيانات مستخدم — عضو مقترح بطلب تشكيل، أو عضو معتمد بلجنة."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    first_name: str
    middle_name: str
    last_name: str
    email: str


class CommitteeFormationRequestCreate(BaseModel):
    """
    بيانات إنشاء طلب تشكيل لجنة جديد (RF-COM-100/200) — يُنشأ دائمًا بحالة
    draft. عضو مقترح واحد على الأقل إلزامي (قرار تحقق منطقي بسيط: لا معنى
    للجنة بلا أعضاء)، وغير موثّق صراحة بـ SRS/BRS.
    """

    committee_name: str = Field(min_length=2, max_length=200)
    statement: str | None = None
    start_date: date
    end_date: date
    proposed_member_ids: list[uuid.UUID] = Field(min_length=1)
    # رئيس اللجنة — إلزامي دائمًا (حتى بحالة draft)، بنفس منطق proposed_member_ids
    # أعلاه (قرار موثّق 2026-08-27). التحقق من كونه فعلًا أحد proposed_member_ids
    # يتم أدناه (نفس الطلب) وبطبقة الخدمة أيضًا عند التعديل (قائمة الأعضاء
    # قد تتغيّر لاحقًا بينما الرئيس لا).
    chair_user_id: uuid.UUID

    @field_validator("proposed_member_ids")
    @classmethod
    def _no_duplicate_members(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(v)) != len(v):
            raise ValueError("لا يمكن تكرار نفس العضو أكثر من مرة بقائمة الأعضاء المقترحين")
        return v

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v: date, info) -> date:
        start = info.data.get("start_date")
        if start is not None and v <= start:
            raise ValueError("تاريخ نهاية عمل اللجنة يجب أن يكون بعد تاريخ البداية")
        return v

    @field_validator("chair_user_id")
    @classmethod
    def _chair_must_be_a_proposed_member(cls, v: uuid.UUID, info) -> uuid.UUID:
        members = info.data.get("proposed_member_ids")
        if members is not None and v not in members:
            raise ValueError("رئيس اللجنة يجب أن يكون أحد الأعضاء المقترحين بالطلب")
        return v


class CommitteeFormationRequestUpdate(BaseModel):
    """
    بيانات تعديل طلب تشكيل لجنة قائم — نفس حقول الإنشاء، كلها اختيارية
    (تعديل جزئي). من يقدر يستدعيها ومتى محكوم بحالة الطلب (Business Rule
    في committee_service، وليس هنا).
    """

    committee_name: str | None = Field(default=None, min_length=2, max_length=200)
    statement: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    proposed_member_ids: list[uuid.UUID] | None = Field(default=None, min_length=1)
    # اختياري بالتعديل الجزئي (نفس نمط بقية الحقول هنا) — لو أُرسل، يُتحقَّق
    # من كونه أحد الأعضاء المقترحين (سواء القائمة الجديدة إن أُرسلت، أو
    # القائمة الحالية المحفوظة، تُفرض بطبقة الخدمة لأنها تحتاج قراءة الطلب
    # الحالي من قاعدة البيانات، وهذا غير متاح هنا بمستوى Schema فقط).
    chair_user_id: uuid.UUID | None = None

    @field_validator("proposed_member_ids")
    @classmethod
    def _no_duplicate_members(cls, v: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        if v is not None and len(set(v)) != len(v):
            raise ValueError("لا يمكن تكرار نفس العضو أكثر من مرة بقائمة الأعضاء المقترحين")
        return v


class CommitteeRejectRequest(BaseModel):
    """سبب الرفض — إلزامي عند رفض الرئيس التنفيذي لطلب التشكيل (RF-COM-600، نهائي)."""

    rejection_reason: str = Field(min_length=3, max_length=1000)


class CommitteeReturnRequest(BaseModel):
    """
    سبب الإرجاع — إلزامي، تُستخدم لمسارين غير نهائيين (قرار موثّق
    2026-08-24): المكتب التنفيذي يرجع الطلب لمقدّمه، أو الرئيس التنفيذي
    يرجعه للمكتب التنفيذي.
    """

    return_reason: str = Field(min_length=3, max_length=1000)


class CommitteeFormationRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: uuid.UUID
    committee_name: str
    statement: str | None
    start_date: date
    end_date: date
    status: CommitteeRequestStatus
    requester: CommitteeMemberUserOut
    proposed_members: list[CommitteeMemberUserOut]
    chair_user_id: uuid.UUID | None
    chair: CommitteeMemberUserOut | None
    # اللجنة الناتجة عن اعتماد هذا الطلب — None قبل الاعتماد (Task #15،
    # للتنقّل المباشر من قائمة الطلبات لصفحة اللجنة نفسها عند approved).
    committee_id: uuid.UUID | None
    rejection_reason: str | None
    return_reason: str | None
    created_at: datetime
    updated_at: datetime


class CommitteeOut(BaseModel):
    """اللجنة المعتمدة رسميًا — تُنشأ تلقائيًا عند موافقة الرئيس التنفيذي."""

    model_config = ConfigDict(from_attributes=True)

    committee_id: uuid.UUID
    name: str
    statement: str | None
    start_date: date
    end_date: date
    source_request_id: uuid.UUID
    members: list[CommitteeMemberUserOut]
    chair_user_id: uuid.UUID | None
    chair: CommitteeMemberUserOut | None
    created_at: datetime
