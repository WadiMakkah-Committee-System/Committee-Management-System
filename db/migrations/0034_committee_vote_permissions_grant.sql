-- منح صلاحيتي التصويت المفقودتين لأدوار اللجان (رئيس/عضو).
--
-- خلفية القرار (بلاغ لاما 2026-09-14: "رئيس اللجنة أنشئ قرار وسوى نشر،
-- لكن أنا كعضو لجنة ما أقدر أصوّت"): decisions.vote.cast وdecisions.
-- vote.view_result عُرّفا فقط بكتالوج الصلاحيات (migration 0006) ولم
-- يُمنحا أبدًا لأي دور — لا نظامي (role_permissions عبر users.role_id)
-- ولا لجني (migration 0016 غطّت committee.decisions.view/manage لكن
-- نسيت صلاحيتي التصويت تحديدًا). النتيجة: cast_vote يرفض الجميع فعليًا
-- عبر _has_access (راجعي decision_service.py) إلا من يملك دورًا نظاميًا
-- استثنائيًا مُنح يدويًا من شاشة "الأدوار والصلاحيات" — وهذا ما فسّر
-- نجاح اختبارات لاما السابقة (حساب مدير/رئيسة) وفشل اختبار عضو عادي.
--
-- الإصلاح الجذري: decisions.vote.cast من حق كل من هو عضو باللجنة —
-- رئيسها وأعضاؤها على حدٍّ سواء (نفس نص _committee_voter_ids التوثيقي
-- بالضبط: "كل من يحق له التصويت... رئيسها وأعضاؤها")، فمنحها هنا لكلا
-- دوري اللجنة. أما decisions.vote.view_result (تفصيل مَن صوّت وبأي خيار
-- لكل الأعضاء) فتبقى عمدًا مقصورة على رئيس اللجنة فقط — هذا بالضبط ما
-- أصلحه بلاغ 2026-09-07 الموثّق برأس _redact_votes_if_unauthorized:
-- "عضو اللجنة ليه يمديه يشوف نتيجة التصويت؟!" — منحها لعضو اللجنة هنا
-- سيُعيد نفس الخطأ الذي أُصلح صراحة حينها.

INSERT INTO role_permissions (role_id, permission_id, scope)
SELECT r.role_id, p.permission_id, 'all'
FROM roles r
JOIN permissions p ON p.code = 'decisions.vote.cast'
WHERE r.committee_role_slug IN ('chair', 'member')
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id, scope)
SELECT r.role_id, p.permission_id, 'all'
FROM roles r
JOIN permissions p ON p.code = 'decisions.vote.view_result'
WHERE r.committee_role_slug = 'chair'
ON CONFLICT (role_id, permission_id) DO NOTHING;
