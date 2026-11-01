-- =====================================================================
-- 0039_committee_request_escalated_by.sql
-- الهدف: حفظ "مَن رفع طلب تشكيل اللجنة للرئيس التنفيذي ومتى" (طلب لاما
-- 2026-11-01): المكتب التنفيذي فيه أكثر من شخص يشوفون نفس الطلبات، والمطلوب
-- يظهر بصفحة الطلب اسم الشخص اللي رفعه (escalate_request → pending_approval).
--
-- - escalated_by / escalated_at: آخر رفع للطلب. لو رجع الطلب لمقدّمه ثم
--   رُفع مرة ثانية، تُحدَّث القيمتان بآخر من رفعه.
-- - NULL = الطلب لم يُرفع للرئيس التنفيذي بعد. القيم تبقى محفوظة حتى لو
--   أُرجع الطلب لاحقًا (سجل تاريخي)؛ الواجهة تعرضها فقط بحالات ما بعد الرفع
--   (pending_approval/approved/rejected).
-- - تعبئة الطلبات المرفوعة سابقًا من audit_logs (action_type='escalate')
--   — آخر رفع لكل طلب — حتى تظهر المعلومة للطلبات القديمة أيضًا.
-- =====================================================================

ALTER TABLE committee_formation_requests
    ADD COLUMN escalated_by UUID REFERENCES users(user_id),
    ADD COLUMN escalated_at TIMESTAMPTZ;

UPDATE committee_formation_requests r
SET escalated_by = a.actor_user_id,
    escalated_at = a.created_at
FROM (
    SELECT DISTINCT ON (target_id) target_id, actor_user_id, created_at
    FROM audit_logs
    WHERE action_type = 'escalate'
      AND target_type = 'committee_formation_request'
    ORDER BY target_id, created_at DESC
) a
WHERE r.request_id = a.target_id;
