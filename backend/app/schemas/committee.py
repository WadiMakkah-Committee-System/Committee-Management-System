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


class CommitteeRoleSummaryOut(BaseModel):
    """اسم/معرّف دور اللجنة (رئيس/عضو) فقط — بدون كامل RoleDetailOut."""

    model_config = ConfigDict(from_attributes=True)

    role_id: uuid.UUID
    name: str
    committee_role_slug: str | None


class ProposedMemberOut(CommitteeMemberUserOut):
    """
    نفس CommitteeMemberUserOut + المسمى الوظيفي والإدارة الحاليان لهذا
    المستخدم — تُستخدم حصرًا بحقل proposed_members بطلب تشكيل اللجنة
    (قرار موثّق مع المستخدمة 2026-09-13: يحتاج الأدمن/المكتب التنفيذي/
    الرئيس التنفيذي يشوفون هذي المعلومات بجنب كل عضو مقترح قبل اتخاذ
    القرار — بما أن رئيس اللجنة المقترح هو أحد proposed_members نفسه
    (قيد مفروض بـcreate_request)، لا حاجة لتوسيع chair/requester بنفس
    الحقلين).

    عمدًا فرع منفصل عن CommitteeMemberUserOut الأصلية (لا تُعدَّل هي
    نفسها) — تلك تُستخدم بأماكن أخرى (اللجنة المعتمدة نفسها بـCommitteeOut،
    DepartmentMemberElsewhereOut) لا تضمن استعلاماتها eager-load لعلاقة
    User.department (بعكس job_title الذي يحمل lazy="selectin" على مستوى
    الموديل أصلاً) — توسيعها هناك كان سيحتاج تدقيق ومراجعة كل استعلام
    يستخدمها لتفادي MissingGreenlet (Lazy Load بجلسة async).
    """

    job_title: str | None = None
    department: str | None = None

    @field_validator("job_title", mode="before")
    @classmethod
    def _flatten_job_title(cls, value: object) -> str | None:
        # يصل هنا ككائن JobTitle ORM (عبر from_attributes) عادة، أو
        # كسلسلة نصية جاهزة لو بُنيت القيمة يدويًا مستقبلًا.
        if value is None or isinstance(value, str):
            return value
        return getattr(value, "name", None)

    @field_validator("department", mode="before")
    @classmethod
    def _flatten_department(cls, value: object) -> str | None:
        if value is None or isinstance(value, str):
            return value
        return getattr(value, "name", None)


class CommitteeMemberRoleOut(BaseModel):
    """
    عضو اللجنة مع دوره داخلها تحديدًا (رئيس اللجنة/عضو اللجنة) — مراجعة
    لاما 2026-08-31 ("أدوار اللجان"). راجعي app/models/committee.py::
    CommitteeMember؛ من from_attributes تُقرأ user وcommittee_role من نفس
    الصف مباشرة.
    """

    model_config = ConfigDict(from_attributes=True)

    user: CommitteeMemberUserOut
    committee_role: CommitteeRoleSummaryOut


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
    proposed_members: list[ProposedMemberOut]
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
    # مراجعة لاما 2026-08-31: نفس الأعضاء أعلاه، لكن مع دور كل واحد منهم
    # داخل هذه اللجنة تحديدًا (رئيس/عضو) — إضافي، لا يستبدل members.
    member_roles: list[CommitteeMemberRoleOut]
    chair_user_id: uuid.UUID | None
    chair: CommitteeMemberUserOut | None
    created_at: datetime


class DepartmentMemberElsewhereOut(BaseModel):
    """
    مراجعة لاما 2026-08-30 (الجولة الثالثة): سطر تعريفي خفيف — موظف من
    إدارة actor عضو بلجنة تابعة لإدارة ثانية (أو بدون إدارة معروفة).
    عمدًا بدون بقية تفاصيل اللجنة (لا أعضاء آخرين، لا تواريخ...) — هذا
    سطح "معرفة بس"، وليس وصول عرض كامل (ذاك محجوز لنطاق department على
    committees.view حين تكون إدارة actor هي القائدة الفعلية للجنة).
    """

    model_config = ConfigDict(from_attributes=True)

    member: CommitteeMemberUserOut
    committee_id: uuid.UUID
    committee_name: str
    department_name: str | None
