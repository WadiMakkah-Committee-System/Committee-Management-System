-- =====================================================================
-- 0017_meetings_enforcement.sql
-- الهدف: منح صلاحيات القراءة فقط لدور "ادمن" على وحدة الاجتماعات، حسب
--        permissions.xlsx حرفيًا (عمود "ادمن" مطابق تمامًا لعمود "عضو
--        لجنه" بقسم الاجتماعات: عرض الاجتماع، عرض تفاصيله، عرض جدول
--        الأعمال، عرض المرفقات فقط — بدون أي صلاحية إنشاء/تعديل/حذف).
--
-- ملاحظة تصميم مهمة (لماذا لا يوجد هنا أي منح لـ"رئيس لجنة"/"عضو لجنة"):
-- كلاهما ليسا أدوارًا بجدول roles أصلًا (حُذفا نهائيًا من كتالوج الأدوار
-- العامة — قرار موثّق 2026-08-27، راجعي 0013_committee_chair.sql).
-- "رئاسة اللجنة" و"العضوية فيها" حالتان مرتبطتان بلجنة محددة (عبر
-- committees.chair_user_id وcommittee_members)، وليستا صلاحية عامة
-- تُمنح لدور — فيُفرض الوصول الكامل لرئيس اللجنة والوصول للقراءة فقط
-- لأعضائها في طبقة الخدمة (meeting_service.py، Phase 2) بالتحقق المباشر
-- من عضوية/رئاسة اللجنة المرتبطة بالاجتماع، تمامًا بنفس أسلوب
-- committee_service.get_committee (فحص chair_user_id/members هناك،
-- وليس عبر role_permissions). صلاحيات meetings.* الكاملة (schedule/
-- update/delete/agenda.*/attachments.*/record_audio) موجودة أصلًا
-- بكتالوج الصلاحيات (0006) لكن **لا تُمنح هنا لأي دور حقيقي عمدًا** —
-- سوبر ادمن فقط يملكها فعليًا، عبر المنح الشامل التلقائي في 0006 نفسه
-- ("super_admin يحصل على كل الصلاحيات في الكتالوج تلقائيًا")، دون أي
-- إضافة جديدة هنا.
--
-- صلاحيتا "تحويل المسودة إلى ملخص" و"عرض المسودة/الملخص" (أعمدة الذكاء
-- الاصطناعي بالمصفوفة) غير مُدرجتين هنا عمدًا — مرتبطتان بمخرجات لا
-- توجد بعد (لا تسجيل صوتي ولا مسودة اجتماع في هذا الـPhase، راجعي
-- ملاحظة (1) بـ0016) — تُمنح عند بناء تلك المرحلة، وليس قبلها.
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
