-- =====================================================================
-- 0019_meetings_enforcement.sql
-- الهدف: منح صلاحيات القراءة فقط لدور "ادمن" (System Role) على وحدة
--        الاجتماعات، حسب permissions.xlsx حرفيًا (عمود "ادمن" مطابق
--        تمامًا لعمود "عضو لجنه" بقسم الاجتماعات: عرض الاجتماع، عرض
--        تفاصيله، عرض جدول الأعمال، عرض المرفقات فقط — بدون أي صلاحية
--        إنشاء/تعديل/حذف).
--
-- ملاحظة مهمة (نسخة مصحَّحة 2026-09-01 — النسخة الأصلية أصبحت غير
-- دقيقة بعد "أدوار اللجان"، راجعي db/migrations/0016_committee_roles.sql
-- و0017_remove_committee_roles_category.sql): هذا الملف يمنح فقط دور
-- "ادمن" العام (System Role)، ولا علاقة له بـ"رئيس اللجنة"/"عضو اللجنة"
-- — هذان أصبحا الآن دورين حقيقيين بجدول roles (kind='committee')، تُمنح
-- صلاحياتهما (بما فيها meetings.*) من نفس شاشة "الأدوار والصلاحيات"،
-- وليس من ملف migration ثابت. حتى صدور منح صريح لهما هناك، لا يملكان أي
-- كود meetings.* (فقط committees.view، بحسب 0017 أعلاه) — فلا أحد غير
-- سوبر أدمن أو دور "ادمن" (المنح أدناه) يقدر يتعامل مع الاجتماعات فعليًا.
-- التحقق الفعلي بطبقة الخدمة (meeting_service.py) يجمع بين مسار النظام
-- هذا ومسار دور اللجنة معًا (OR)، بنفس نمط committee_service.get_committee.
--
-- صلاحيتا "تحويل المسودة إلى ملخص" و"عرض المسودة/الملخص" (أعمدة الذكاء
-- الاصطناعي بالمصفوفة) غير مُدرجتين هنا عمدًا — مرتبطتان بمخرجات لا
-- توجد بعد (لا تسجيل صوتي ولا مسودة اجتماع في هذا الـPhase) — تُمنح عند
-- بناء تلك المرحلة، وليس قبلها.
-- =====================================================================

-- لا تعتمد على اسم الدور المعروض ('admin' محليًا مقابل 'ادمن' بالإنتاج)
-- — بنفس تحذير مراجعة لاما 2026-08-30 المطبَّق فعليًا بـ0015. الدور
-- المقصود (ادمن) يُحدَّد هنا عبر صلاحية مميّزة يملكها فعليًا وحده حاليًا
-- (committees.request.create — مانحها الوحيد بالكتالوج بحسب 0009).
INSERT INTO role_permissions (role_id, permission_id, scope)
SELECT DISTINCT rp.role_id, meet_perm.permission_id, 'department'
FROM role_permissions rp
JOIN permissions anchor_perm
    ON anchor_perm.permission_id = rp.permission_id
    AND anchor_perm.code = 'committees.request.create'
JOIN permissions meet_perm
    ON meet_perm.code IN (
        'meetings.view',
        'meetings.view_details',
        'meetings.agenda.view',
        'meetings.attachments.view'
    )
ON CONFLICT (role_id, permission_id) DO UPDATE SET scope = 'department';
