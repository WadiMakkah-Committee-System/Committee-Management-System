"""
الهدف:
راوتات REST لوحدة "إدارة الاجتماعات" (Phase 2 + مرفقات الاجتماع). بدون
أي تكامل فعلي مع Microsoft Teams/Graph API — راجعي رأس
app/services/meeting_service.py لتفصيل القرار الموثّق.

ملاحظة مهمة (لماذا لا تستخدم راوتات الإنشاء/التعديل/الحذف require_permission
على مستوى الراوت، بخلاف committees.py): التفويض هنا يعتمد على اللجنة
المحدَّدة بالطلب تحديدًا (Committee Role الخاص بعضوية actor في *تلك*
اللجنة بالذات) وليس فقط على دوره العام — فلا يمكن فحصه بمعزل عن تحميل
السجل نفسه أولًا. يُفرض بالكامل داخل meeting_service.

ملاحظة تقنية: دوال meeting_service (create/update/delete_meeting،
add/update/delete_agenda_item، add/delete_attachment) تُنفّذ commit/rollback
داخليًا بنفسها الآن (بخلاف نمط committees.py الذي يترك الـcommit للراوت) —
ضروري لأن add_attachment يستدعي document_service.create_document الذي
يُنهي معاملته (transaction) الخاصة به بالكامل قبل أن يعود، فلا يمكن تأجيل
الـcommit لهذا الجزء إلى الراوت. طُبِّق نفس النمط على بقية دوال الوحدة
هنا للاتساق، بدل خلط الأسلوبين داخل نفس الملف. الاستثناء الوحيد:
join_meeting/leave_meeting (تكامل Agora) — تُبقي الـcommit/rollback على
مستوى الراوت عمدًا (راجعي تعليق القسم أدناه).

بنية الحزمة (إعادة هيكلة 2026-10-24 — كانت ملفًا واحدًا بـ1123 سطرًا):
- _errors.py      ترجمة استثناءات الخدمة إلى HTTP (مشتركة).
- core.py         CRUD + الانضمام/المغادرة + جدول الأعمال.
- attachments.py  المرفقات.
- ai.py           التسجيل الصوتي + المسودة + البنود المستخرجة.
- minutes.py      المحاضر.
- chat.py         رسائل القناة اللحظية.

المسارات وترتيب تسجيلها مطابقان تمامًا للملف السابق (نفس البادئة /meetings).
"""

from fastapi import APIRouter

from app.api.v1.meetings import ai, attachments, chat, core, minutes

# كل راوتر فرعي يحمل البادئة /meetings بنفسه (FastAPI لا يسمح بمسار
# فارغ "" تحت راوتر بلا بادئة)، وهذا الراوتر يجمعها بنفس الترتيب الأصلي.
router = APIRouter()
for _sub in (core, attachments, ai, minutes, chat):
    router.include_router(_sub.router)
