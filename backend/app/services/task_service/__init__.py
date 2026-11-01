"""
الهدف:
منطق العمل لوحدة "إدارة المهام" — الإنشاء المباشر من واجهة المهام فقط
(§4 SRS + §6 BRS). بدون المهام المستخرجة من اجتماع بالذكاء الاصطناعي
(تُبنى لاحقًا)، وبدون ربط بالوثائق أو تذكيرات بهذه المرحلة. راجعي رأس
db/migrations/0024_tasks_schema.sql لكل الاجتهادات الموثّقة المتفَق عليها
مع صاحبة المشروع (2026-09-06).

التفويض: نفس النمط الهجين المطبَّق حرفيًا بوحدة القرارات (System Role
scope عبر actor.scope_for، أو Committee Role permission عبر
committee_service.get_committee_role_permission_codes) — بنفس أكواد
النظام تمامًا لكلا المستويين (tasks.create/view/view_details/update/
delete/status.update)، تُمنح لدوري "رئيس اللجنة"/"عضو اللجنة" مباشرة عبر
شاشة الأدوار والصلاحيات (نفس آلية decisions.*، راجعي test_decisions.py
لمثال المنح). ملاحظة: أكواد committee.tasks.manage/view_assigned/
update_assigned المزروعة بـmigration 0016 هي فقط لتصنيف واجهة "أدوار
اللجان" — غير مستخدَمة هنا، بنفس الحال الفعلي لأكواد committee.decisions.*
بوحدة القرارات.

تمييز إضافي غير موجود بالقرارات: "عرض" و"تحديث الحالة" يحتاجان تقييدًا
إضافيًا على مستوى الكائن نفسه (وليس مجرّد امتلاك الكود) — رئيس اللجنة
يشوف/يحدّث أي مهمة بلجنته، بينما العضو العادي (نفس الكود الممنوح له)
يقتصر على المهام المسندة له هو تحديدًا. هذا التمييز يُحسَم بمقارنة
committee.chair_user_id == actor.user_id مباشرة، وليس من قائمة الأكواد.

القفل الحرج (FR-TASK-016/018): التعديل/الحذف/إعادة الإسناد/تحديث الحالة
كلها ممنوعة فعليًا إذا status الحالية = 'completed'.

تحديثات الحالة تُسجَّل بجدول audit_logs العام (نفس نمط تحديثات حالة
القرارات بالضبط) — منفصل تمامًا عن task_assignment_history (مسار
المهمة)، المخصّص فقط لتتبع إعادة تعيين المسؤول.

بنية الحزمة (إعادة هيكلة 2026-10-24 — كانت ملفًا واحدًا ~565 سطرًا):
- errors.py / codes.py  الأخطاء وأكواد الصلاحيات وتسميات العرض.
- loading.py            المكان الوحيد الذي يحدد ماذا يُحمَّل مع المهمة.
- access.py             قواعد صلاحيات المهام فوق app/services/committee_access.py.
- crud.py               الإنشاء/العرض/القائمة/التعديل/الحذف.
- status.py             تحديث الحالة وإعادة الإسناد.
- activity.py           مسار المهمة الموحَّد.
الاستيراد القديم (task_service.X) يعمل كما هو.
"""

from app.services.task_service.activity import get_task_activity
from app.services.task_service.crud import (
    create_task,
    delete_task,
    get_task,
    list_tasks,
    update_task,
)
from app.services.task_service.errors import (
    TaskForbiddenError,
    TaskInvalidStateError,
    TaskNotFoundError,
    TaskValidationError,
)
from app.services.task_service.status import reassign_task, update_status

__all__ = [
    "TaskForbiddenError",
    "TaskInvalidStateError",
    "TaskNotFoundError",
    "TaskValidationError",
    "create_task",
    "delete_task",
    "get_task",
    "get_task_activity",
    "list_tasks",
    "reassign_task",
    "update_status",
    "update_task",
]
