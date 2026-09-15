"""
الهدف:
Pydantic Schemas لوحدة "المحاضر" (SRS §7) — راجعي رأس
app/models/meeting_minutes.py وdb/migrations/0029 للتصميم الكامل
(آلة الحالة، القوالب الثابتة، لماذا reviewers/signatures جدولان حقيقيان).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.committee import CommitteeMemberUserOut

MeetingMinutesStageOut = Literal["none", "preparing", "review", "approval", "signature", "completed"]
MeetingMinutesReviewStatusOut = Literal["pending", "approved", "returned"]
MinutesTemplateId = Literal["executive", "formal", "detailed"]


class MinutesSection(BaseModel):
    """قسم واحد بمحتوى المحضر — تُنسخ نسخة أولية من القالب لحظة اختياره
    (راجعي MINUTES_TEMPLATES بـmeeting_minutes_service.py)، وبعدها حرة
    الإضافة/التعديل/الحذف بدون أي أثر على تعريف القالب نفسه."""

    id: str
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    order: int = 0


class MinutesTemplateOut(BaseModel):
    """تعريف قالب ثابت (Hardcoded بالباك-إند — لا واجهة إدارة قوالب بعد،
    لمى أجّلت هذا القرار صراحة). تُعرض فقط للمعاينة قبل الاختيار؛ القالب
    التفصيلي (detailed) لا تُعرَف أقسامه مسبقًا هنا (تُبنى ديناميكيًا من
    بنود الاجتماع الفعلية — sections هنا تكون قائمة فارغة له، والفرونت
    يعرض له وصفًا مختلفًا بدل معاينة أقسام ثابتة)."""

    id: MinutesTemplateId
    name: str
    description: str
    sections: list[str]


class ReviewerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reviewer_id: uuid.UUID
    user: CommitteeMemberUserOut
    status: MeetingMinutesReviewStatusOut
    comment: str | None
    reviewed_at: datetime | None


class SignatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    signature_id: uuid.UUID
    user: CommitteeMemberUserOut
    signed: bool
    signed_at: datetime | None


class MeetingMinutesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    minutes_id: uuid.UUID
    meeting_id: uuid.UUID
    template_id: MinutesTemplateId | None
    # اسم القالب المختار جاهزًا من الباك-إند (FR-MIN-003 البند الثالث) —
    # يتيح للأعضاء معرفة اسم القالب المختار بدون الحاجة لاستدعاء
    # GET /{meeting_id}/minutes/templates المحمي برئيس اللجنة فقط
    # (minutes.templates.view). None إذا لم يُختر قالب بعد.
    template_name: str | None
    stage: MeetingMinutesStageOut
    owner: CommitteeMemberUserOut | None
    sections: list[MinutesSection]
    reviewers: list[ReviewerOut]
    signatures: list[SignatureOut]
    sent_to_review_at: datetime | None
    approved_at: datetime | None
    sent_for_signature_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MinutesSummaryOut(BaseModel):
    """ملخص خفيف لمحضر اجتماع واحد ضمن استجابة دفعية (bulk) — إصلاح
    2026-09-14 (بلاغ لاما — انهيار 500 متكرر على عدة مسارات مختلفة
    بنفس اللحظة): صفحة "إدارة المحاضر" (MinutesListPage.tsx) كانت تطلق
    طلب HTTP منفصل بالكامل لكل اجتماع عبر useQueries (5-40+ طلب متزامن
    حسب عدد الاجتماعات غير upcoming بالنظام)، وكل طلب يفتح جلسة/اتصال
    قاعدة بيانات مستقل — هذا بالضبط ما كان يستنزف Connection Pool
    (pool_size=10+max_overflow=10) عند أي انفجار طلبات (خصوصًا بعد Render
    Cold Start)، تمامًا كما وُثِّق سابقًا بتعليقات app/db/session.py
    (9/10/12 سبتمبر — "صفحة المحضر وحدها تفتح 5-6 طلبات متزامنة"، ونفس
    الفخ تكرر هنا بمضاعفة عدد الاجتماعات بدل صفحة واحدة). الحل الجذري:
    نقطة API دفعية واحدة (GET /meetings/minutes/summary) تعيد ملخصًا
    لكل الاجتماعات المطلوبة باستعلامين اثنين فقط (راجعي
    list_minutes_summaries أدناه) بدل استعلام Full MeetingMinutesOut لكل
    اجتماع على حدة. لا يحمل sections/template_id (غير مستخدَمة بالقائمة
    أصلًا) — القائمة تفتح المحضر التفصيلي (GET /{id}/minutes العادي) فقط
    عند الضغط الفعلي على بطاقة واحدة."""

    meeting_id: uuid.UUID
    forbidden: bool
    not_finished_yet: bool
    stage: MeetingMinutesStageOut | None
    owner_name: str | None
    reviewers_total: int
    reviewers_approved: int
    approved_at: datetime | None
    signatures_total: int
    signatures_signed: int


class SelectTemplateIn(BaseModel):
    """اختيار قالب المحضر (FR-MIN-003) — رئيس اللجنة فقط (minutes.templates.select)."""

    template_id: MinutesTemplateId


class UpdateSectionsIn(BaseModel):
    """استبدال كامل لقائمة أقسام المحضر — تُستخدم لكل من التعديل العادي
    والـAutosave وإضافة/حذف قسم (الفرونت يرسل القائمة كاملة بعد التعديل
    المحلي، ونفس الحدث يُبث لحظيًا لبقية الحاضرين عبر minutes.updated)."""

    sections: list[MinutesSection]


class ReviewDecisionIn(BaseModel):
    """اعتماد مراجعة أو إعادتها للتعديل — comment إلزامي عمليًا عند
    الإعادة فقط (يُتحقَّق منه بطبقة الخدمة لا هنا)."""

    comment: str | None = Field(default=None, max_length=1000)


class SignMinutesIn(BaseModel):
    """توقيع إلكتروني — صورة Base64 (PNG) من react-signature-canvas
    بالفرونت-إند (توقيع فعلي مرسوم، وليس مجرد علم "تم")."""

    signature_image: str = Field(min_length=10)
