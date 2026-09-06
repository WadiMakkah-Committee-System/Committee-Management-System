"""
الهدف:
Pydantic Schemas الخاصة بوحدة "إدارة الاجتماعات" (Phase 2 — Backend APIs).
تحدّد شكل بيانات الاجتماعات وجدول الأعمال والمرفقات والردود لواجهات
FR-MEET-001 → FR-MEET-005 (SRS §3.1.1/3.1.2) + إدارة جدول الأعمال
(§3.1.3)، وتفصل شكل الـAPI عن نموذج قاعدة البيانات (ORM) في
app/models/meeting.py.

بدون تكامل Teams/AI فعلي في هذا الـPhase — لا حقول teams_join_url/summary
هنا، رغم أن mode='remote' يمهّد لتلك المرحلة (راجعي app/models/meeting.py).

تحديث 2026-09-01 (قرارات صاحبة المشروع):
- meeting_type (نص حر) → mode (عن بعد/حضوري، عبر MeetingMode) + location
  (إلزامي فقط للاجتماع الحضوري — راجعي رأس db/migrations/0020 للتفصيل
  الكامل، ومنطق التحقق التلازمي الفعلي بـapp/services/meeting_service.py).
- participant_ids حُذف من MeetingCreate/MeetingUpdate بالكامل — المشاركون
  الآن كل أعضاء اللجنة تلقائيًا (يُشتقّون بطبقة الخدمة، راجعي
  meeting_service.create_meeting)، بدون أي اختيار يدوي.
- مرفقات الاجتماع (MeetingAttachmentOut) — عبر document_links الموجود
  أصلًا (راجعي رأس db/migrations/0021)، تُرفع كـmultipart/form-data منفصلة
  بعد إنشاء الاجتماع (راجعي app/api/v1/meetings.py::upload_meeting_attachment).

تحديث 2026-09-05 (قرار موثّق مع لاما): scheduled_end_at إلزامي عند
الإنشاء (لا اجتماع بلا وقت نهاية معروف مسبقًا) — يقود التحويل التلقائي
لحالة الاجتماع (upcoming/ongoing/finished)، راجعي
meeting_service._maybe_transition_status.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.meeting import MeetingMode, MeetingStatus
from app.schemas.committee import CommitteeMemberUserOut

# نوعا مرفقات الاجتماع — يقابلان بالضبط قيمتَي linked_entity_type
# المستخدمتين بجدول document_links (راجعي meeting_service.py):
# 'meeting_presentation' و'meeting_attachment'.
MeetingAttachmentKind = Literal["presentation", "attachment"]


class MeetingAgendaItemCreate(BaseModel):
    """بند جدول أعمال — يُرسَل ضمن قائمة عند إنشاء/تعديل الاجتماع، أو منفردًا لاحقًا."""

    title: str = Field(min_length=2, max_length=255)
    description: str | None = None
    sort_order: int = 0


class MeetingAgendaItemUpdate(BaseModel):
    """تعديل جزئي لبند موجود — كل الحقول اختيارية."""

    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = None
    sort_order: int | None = None


class MeetingAgendaItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agenda_item_id: uuid.UUID
    meeting_id: uuid.UUID
    title: str
    description: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


class MeetingCreate(BaseModel):
    """
    بيانات إنشاء اجتماع جديد (FR-MEET-001) — حصريًا لرئيس اللجنة المرتبط
    بـcommittee_id (يُتحقَّق منه بطبقة الخدمة عبر committee.chair_user_id،
    وليس هنا). بنود الأجندة اختيارية عند الإنشاء — يمكن إضافتها لاحقًا
    عبر /agenda-items (FR-MEET §3.1.3).

    mode إلزامي دائمًا (قرار 2026-09-01)؛ location إلزامي فقط لو
    in_person، ويُفرَغ تلقائيًا لو remote (يُتحقَّق أدناه) — الاجتماع عن
    بُعد يُربط لاحقًا بـTeams (teams_join_url، محجوز غير مستخدَم بعد).

    scheduled_end_at إلزامي أيضًا (قرار موثّق مع لاما 2026-09-05) — لا
    يُسمح بإنشاء اجتماع بلا وقت نهاية معروف مسبقًا؛ يجب أن يكون بعد
    scheduled_at.

    لا يوجد participant_ids هنا (قرار موثّق مع لاما 2026-09-05): كل أعضاء
    اللجنة (بمن فيهم رئيسها) يُضافون تلقائيًا كمشاركين عند الإنشاء — بلا
    اختيار يدوي. راجعي meeting_service.create_meeting للتنفيذ الفعلي.
    """

    committee_id: uuid.UUID
    title: str = Field(min_length=2, max_length=255)
    description: str | None = None
    mode: MeetingMode
    location: str | None = Field(default=None, max_length=255)
    scheduled_at: datetime
    # إلزامي (قرار موثّق مع لاما 2026-09-05) — لا يُسمح بإنشاء اجتماع بلا
    # وقت نهاية معروف مسبقًا. راجعي db/migrations/0023 لسبب كون العمود
    # نفسه Nullable بقاعدة البيانات رغم الإلزام هنا (اجتماعات قديمة فقط).
    scheduled_end_at: datetime
    agenda_items: list[MeetingAgendaItemCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_location_matches_type(self) -> "MeetingCreate":
        self.location = _blank_to_none(self.location)
        if self.mode == MeetingMode.in_person and self.location is None:
            raise ValueError("مكان الاجتماع إلزامي للاجتماع الحضوري")
        if self.mode == MeetingMode.remote and self.location is not None:
            raise ValueError("لا يمكن تحديد مكان لاجتماع عن بُعد")
        return self

    @model_validator(mode="after")
    def _validate_end_after_start(self) -> "MeetingCreate":
        if self.scheduled_end_at <= self.scheduled_at:
            raise ValueError("وقت نهاية الاجتماع يجب أن يكون بعد وقت البداية")
        return self


class MeetingUpdate(BaseModel):
    """
    تعديل بيانات اجتماع قائم (FR-MEET-003) — قبل انعقاده فقط (يُفرض بطبقة
    الخدمة عبر status == upcoming، وليس هنا). كل الحقول اختيارية.

    mode/location: لا يوجد تحقق تلازمي هنا (نفس نمط chair_user_id
    بـCommitteeFormationRequestUpdate) — لو أُرسل أحدهما بدون الآخر، يُفرض
    التلازم بطبقة الخدمة مقابل الحالة الحالية المحفوظة بقاعدة البيانات
    (غير متاحة بمستوى Schema فقط). لهذا السبب أيضًا تستخدم طبقة الـAPI
    model_fields_set لتمييز "لم يُرسَل" عن "أُرسل بقيمة فارغة صراحة" لكلا
    الحقلين (نفس نمط category_explicitly_set بـdocument_service).
    """

    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = None
    mode: MeetingMode | None = None
    location: str | None = Field(default=None, max_length=255)
    scheduled_at: datetime | None = None
    scheduled_end_at: datetime | None = None

    @model_validator(mode="after")
    def _normalize_location(self) -> "MeetingUpdate":
        self.location = _blank_to_none(self.location)
        return self


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    meeting_id: uuid.UUID
    committee_id: uuid.UUID
    title: str
    description: str | None
    mode: MeetingMode
    location: str | None
    scheduled_at: datetime
    scheduled_end_at: datetime | None
    status: MeetingStatus
    creator: CommitteeMemberUserOut
    participants: list[CommitteeMemberUserOut]
    agenda_items: list[MeetingAgendaItemOut]
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MeetingAttachmentOut(BaseModel):
    """
    ملف مرتبط باجتماع (عرض تقديمي أو مرفق عام) — تجميعة من Document +
    document_links (راجعي meeting_service.list_attachments). document_id
    هو نفسه معرّف الوثيقة بوحدة "إدارة الوثائق" (documents.py) — يمكن
    استخدامه مباشرة مع GET /documents/{document_id}/download.
    """

    document_id: uuid.UUID
    kind: MeetingAttachmentKind
    title: str
    file_name: str
    mime_type: str
    file_size_bytes: int
    uploaded_by: CommitteeMemberUserOut
    linked_at: datetime


class MeetingJoinOut(BaseModel):
    """
    استجابة POST /meetings/{id}/join — معلومات الانضمام الجاهزة لتمريرها
    مباشرة لـAgora Web SDK (client.join(app_id, channel, token, uid)). تُبنى يدويًا
    بطبقة الـAPI من meeting_service.MeetingJoinToken (ليس من attributes نموذج ORM،
    فلا from_attributes هنا).
    """

    app_id: str
    channel: str
    token: str
    uid: int
    expires_at: int
