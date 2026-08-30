-- =====================================================================
-- 0015_committees_request_update_backfill.sql
-- الهدف: تصحيح/تعميم منح مرحلة الـBackend من مراجعة لاما 2026-08-30
-- (توحيد صلاحية تعديل طلب اللجنة تحت committees.request.update واحدة —
-- راجعي app/services/committee_service.py::update_request/submit_request).
--
-- migration 0014 (البند 5) منحت هذا فقط لدور محدد بالاسم النصي 'ادمن'
-- (الدور الفعلي بقاعدة البيانات الإنتاجية اليوم). هذا الملف يصحّح ذلك
-- ليكون عامًا وغير معتمد على اسم دور معيّن إطلاقًا (اتساقًا مع "لا تعتمدي
-- على اسم الدور المعروض لتحديد الصلاحيات" — مراجعة لاما 2026-08-30):
-- أي دور يملك committees.request.create اليوم كان يعتمد عليها ضمنيًا
-- لتعديل/إرسال مسودته الخاصة (draft/returned) قبل التوحيد — يحتاج الآن
-- committees.request.update بنطاق 'own' ليحافظ على نفس القدرة بالضبط
-- بعد أن أصبح submit_request/update_request (لحالتي draft/returned)
-- يتحققان من committees.request.update فقط، بغض النظر عن اسم الدور أو
-- تسميته المعروضة — وهذا ما يجعل هذا الملف يعمل صح محليًا بيئة التطوير
-- (حيث الأدوار مسمّاة بالإنجليزية: admin) وبالإنتاج (حيث أُعيدت تسميتها
-- عربيًا: ادمن) بنفس المنطق دون أي فرق.
--
-- ON CONFLICT DO NOTHING عمدًا (وليس DO UPDATE): أي دور يملك بالفعل
-- committees.request.update (مثال: المكتب التنفيذي بنطاق 'all') لا يُمَس
-- إطلاقًا — هذا الملف يُضيف فقط للأدوار التي لا تملك الصلاحية بعد، ولا
-- يُضيّق نطاق أي منح أوسع موجود مسبقًا.
INSERT INTO role_permissions (role_id, permission_id, scope)
SELECT rp.role_id, update_perm.permission_id, 'own'
FROM role_permissions rp
JOIN permissions create_perm
    ON create_perm.permission_id = rp.permission_id
    AND create_perm.code = 'committees.request.create'
JOIN permissions update_perm
    ON update_perm.code = 'committees.request.update'
ON CONFLICT (role_id, permission_id) DO NOTHING;
