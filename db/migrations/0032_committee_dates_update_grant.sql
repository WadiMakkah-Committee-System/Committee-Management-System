-- منح صلاحية تعديل تاريخي بداية/نهاية اللجنة (فقط) لأدوار المكتب التنفيذي.
--
-- خلفية القرار (طلب صاحبة المشروع 2026-09-13، ضمن "قاعدة فترة اللجنة"):
-- كانت الهجرة 0009_committee_formation_enforcement.sql قد قفلت بيانات
-- اللجنة بالكامل بعد الاعتماد لكل الأدوار بلا استثناء (قرار موثّق ومتعمَّد
-- حينها، اجتهاد عن الـSRS الأصلي بالاتفاق مع صاحبة المشروع). هذه الهجرة
-- تعكس ذلك القرار جزئيًا وبنطاق ضيق جدًا: الاسم/البيان/الرئيس/الأعضاء
-- تبقى مقفلة تمامًا كما قرَّرت 0009 دون أي استثناء — فقط start_date/
-- end_date تصبحان قابلتين للتعديل، عبر endpoint جديد مخصص
-- (PATCH /committees/{id})، لأن سيناريوهات فعلية (تمديد/تقصير فترة لجنة
-- قائمة) تحتاج ذلك ولا يوجد أي تحايل معماري آخر يحققه.
--
-- اختيار الأدوار: executive_office_manager وexecutive_office_secretary
-- فقط (وليس executive_president أو رؤساء اللجان) — لأن المكتب التنفيذي
-- هو المالك الإداري القائم فعلاً لبيانات طلبات تكوين اللجان قبل
-- الاعتماد، فهذا امتداد طبيعي لنفس الملكية بعد الاعتماد، بنطاق التاريخ
-- فقط. راجعي app/services/committee_service.py (update_committee) و
-- app/api/v1/committees.py لمنطق الفحص المرتبط (رفض التعديل إذا وُجد
-- اجتماع/مهمة/قرار مرتبط يقع خارج الفترة الجديدة).

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id
FROM roles r
CROSS JOIN permissions p
WHERE r.name IN ('executive_office_manager', 'executive_office_secretary')
  AND p.code = 'committees.update'
ON CONFLICT (role_id, permission_id) DO NOTHING;
