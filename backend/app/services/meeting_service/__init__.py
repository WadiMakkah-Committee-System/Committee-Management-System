"""
الهدف:
منطق العمل (Business Logic) لوحدة "إدارة الاجتماعات" — FR-MEET-001 →
FR-MEET-005 (SRS §3.1.1/3.1.2) + إدارة جدول الأعمال (§3.1.3) + مرفقات
الاجتماع (عرض تقديمي + مرفقات عامة، عبر document_links الموجود أصلًا).
بدون أي تكامل فعلي مع Microsoft Teams/Graph API — mode='remote' يمهّد
لتلك المرحلة فقط (راجعي app/models/meeting.py). الانضمام الفعلي
للاجتماعات عن بعد يتم عبر Agora (راجعي قسم join_meeting/leave_meeting
أدناه) — منفصل تمامًا عن تكامل Teams المؤجَّل.

التفويض (بعد "أدوار اللجان" — راجعي committee_service.py::
get_committee_role_permission_codes): الوصول = صلاحية على مستوى System
Role (own/department/all، من دور المستخدم العام) **أو** صلاحية على
مستوى Committee Role (رئيس اللجنة/عضو اللجنة — من دور عضويته بهذه اللجنة
تحديدًا، تُقرأ حيًا من role_permissions). لا شيء مكتوب بثبات بالكود —
يُضبط من شاشة "الأدوار والصلاحيات".

تحديثات 2026-09-01 (قرارات صاحبة المشروع):
- meeting_type (نص حر) → mode (عن بعد/حضوري) + location (إلزامي حضوري).
- المشاركون: لا يوجد اختيار يدوي بعد الآن — كل أعضاء اللجنة (بمن فيهم
  رئيسها) يُضافون تلقائيًا عند الإنشاء (create_meeting)، ولا اختيار يدوي
  عند التعديل أيضًا (participant_ids حُذف بالكامل من MeetingUpdate —
  راجعي schemas/meeting.py).
- حذف الاجتماع (delete_meeting) ممنوع بعد وقت انعقاده الفعلي (لا معنى
  لحذف اجتماع انتهى وقته) — قيد جديد لم يكن موجودًا سابقًا.
- مرفقات الاجتماع: قسمان مستقلان (kind: 'presentation' | 'attachment')،
  يُخزَّنان عبر document_service.create_document (نفس بنية تخزين وحدة
  الوثائق) ثم يُربطان بالاجتماع عبر document_links (linked_entity_type=
  'meeting_presentation'/'meeting_attachment'، linked_entity_id=meeting_id)
  — الجدول كان "جاهزًا بالقاعدة، غير مستخدَم بعد" (راجعي 0012)، وهذا أول
  استخدام فعلي له.

تحديث 2026-09-05/06 (قرارات موثّقة مع لاما — تكامل الفيديو + الإشعارات):
- scheduled_end_at إلزامي عند الإنشاء، ويقود التحويل التلقائي لحالة
  الاجتماع (upcoming/ongoing/finished) — راجعي sync_meeting_status.
- update_meeting/delete_meeting يُعيدان الاجتماع (بعد commit) لتستخدمه
  طبقة الـAPI بإرسال إشعار بريدي لأعضاء اللجنة (راجعي notification_service.py
  وapp/api/v1/meetings.py) — عند التعديل فقط لو تغيّر أحد "الحقول
  المهمة" (موعد البداية/النهاية/النوع/المكان).

بنية الوحدة (إعادة هيكلة 2026-10-24 — كانت ملفًا واحدًا بـ1390 سطرًا):
- errors.py           الاستثناءات (تُترجَم لرموز HTTP بطبقة الـAPI).
- access.py           فحص الصلاحيات (System Role أو Committee Role).
- loading.py          تحميل الاجتماع/اللجنة بخيارات صريحة + sync_meeting_status.
- crud.py             إنشاء/عرض/قائمة/تعديل/حذف.
- attendance.py       الانضمام/المغادرة (Agora).
- agenda.py           جدول الأعمال.
- attachments.py      المرفقات.
- recordings.py       التسجيل الصوتي + مسودة الذكاء الاصطناعي.
- extracted_items.py  البنود المستخرجة → مهام/قرارات.

مسار الاستيراد لم يتغيّر: app.services.meeting_service.<الدالة> يعمل كما
كان لكل الدوال والاستثناءات العامة (هذا الملف يعيد تصديرها).
"""

from app.services.meeting_service.agenda import add_agenda_item, delete_agenda_item, update_agenda_item
from app.services.meeting_service.attachments import (
    add_agenda_item_attachments,
    add_attachment,
    delete_attachment,
    get_attachment_download,
    list_attachments,
)
from app.services.meeting_service.attendance import MeetingJoinToken, join_meeting, leave_meeting
from app.services.meeting_service.crud import (
    create_meeting,
    delete_meeting,
    extend_meeting,
    get_meeting,
    list_meetings,
    update_meeting,
)
from app.services.meeting_service.errors import (
    AgendaItemNotFoundError,
    AttachmentNotFoundError,
    DraftNotFoundError,
    ExtractedItemNotFoundError,
    MeetingForbiddenError,
    MeetingInvalidStateError,
    MeetingNotFoundError,
    MeetingValidationError,
    RecordingNotFoundError,
)
from app.services.meeting_service.extracted_items import (
    add_manual_extracted_item,
    assign_extracted_item_as_decision,
    assign_extracted_item_as_task,
    delete_extracted_item,
    extract_meeting_items,
    list_extracted_items,
)
from app.services.meeting_service.loading import sync_meeting_status
from app.services.meeting_service.recordings import (
    download_recording,
    generate_draft,
    get_draft,
    get_latest_recording,
    upload_recording,
)

__all__ = [
    "AgendaItemNotFoundError",
    "AttachmentNotFoundError",
    "DraftNotFoundError",
    "ExtractedItemNotFoundError",
    "MeetingForbiddenError",
    "MeetingInvalidStateError",
    "MeetingJoinToken",
    "MeetingNotFoundError",
    "MeetingValidationError",
    "RecordingNotFoundError",
    "add_agenda_item",
    "add_agenda_item_attachments",
    "add_attachment",
    "add_manual_extracted_item",
    "assign_extracted_item_as_decision",
    "assign_extracted_item_as_task",
    "create_meeting",
    "delete_agenda_item",
    "delete_attachment",
    "delete_extracted_item",
    "delete_meeting",
    "download_recording",
    "extract_meeting_items",
    "generate_draft",
    "get_attachment_download",
    "get_draft",
    "extend_meeting",
    "get_latest_recording",
    "get_meeting",
    "join_meeting",
    "leave_meeting",
    "list_attachments",
    "list_extracted_items",
    "list_meetings",
    "sync_meeting_status",
    "update_agenda_item",
    "update_meeting",
    "upload_recording",
]
