-- =====================================================================
-- 0040_decision_abstain_option.sql
-- الهدف: خيار "ممتنع" ثابت يُضاف تلقائيًا (بالكود، وليس بإدخال رئيسة
-- اللجنة) لكل تصويت يُفتح — طلب صاحبة المشروع 2026-11-01. إذا اختار
-- العضو "ممتنع" يصبح ذكر السبب إلزاميًا (decision_votes.reason)،
-- ويُقيَّد عرض هذا السبب برئيسة اللجنة فقط (أو صاحبب الصوت نفسه لصوته
-- هو) — أشد تقييٴٯ من تحرير نتيجة التصويت العام (decisions.vote.
-- view_result، راجعي decision_service.access._redact_votes_if_unauthorized)
-- حتى لمن يملك تلك الصلاحية لسبب آخر. راجعي رأس 0025 لتفصيل كيف تبقى
-- الأغلبية التلقائية تعمل مع خيارات حرة؛ التعديل هنا: أصوات "ممتنع" لا
-- تُحتسب أصلًا بمقام نسبة الأغلبية (معيار حوكمة شائع: الامتناع ≠ رفض) —
-- راجعي decision_service.voting._maybe_close_voting.
--
-- is_abstain منفصل عن is_approving (دائمًا false لخيار الامتناع) — يميّز
-- خيار الامتناع تحديدًا عن أي خيار "غير موافق" حر تكتبه رئيسة اللجنة.
-- =====================================================================

ALTER TABLE decision_vote_options
    ADD COLUMN is_abstain BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE decision_votes
    ADD COLUMN reason TEXT NULL;

-- ملاحظة: لا قيد CHECK على إلزامية reason عند is_abstain=true — يتطلب
-- فحصًا عبر جدولين (decision_votes.option_id → decision_vote_options.
-- is_abstain)، يُفرض بدلًا عن ذلك بطبقة الخدمة (decision_service.voting.
-- cast_vote) بنفس أسلوب بقية التحققات التجارية بالمشروع (مثال:
-- app/core/committee_period.py).
