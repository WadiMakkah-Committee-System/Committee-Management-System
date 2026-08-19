-- =====================================================================
-- 0004_create_audit_logs.sql
-- الهدف: سجل تدقيق (Audit Log) لعمليات إنشاء/تعديل/حذف/إيقاف الحسابات
--        FR-UM-029
-- =====================================================================

CREATE TYPE audit_action AS ENUM ('create', 'update', 'delete', 'suspend', 'reactivate');

-- جدول Append-only (بدون UPDATE أو DELETE) — لا يحتوي updated_at عمدًا.
-- target_type + target_id بشكل عام (مو FK مباشر) عشان يصلح لتسجيل أي كيان
-- مستقبلي (لجان، اجتماعات، قرارات...) بدون تعديل بنية الجدول لاحقًا.
CREATE TABLE audit_logs (
    log_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id UUID REFERENCES users(user_id),   -- NULLABLE - من نفذ العملية
    action_type   audit_action NOT NULL,
    target_type   VARCHAR(50) NOT NULL,             -- مثال: 'user', 'department'
    target_id     UUID NOT NULL,
    metadata      JSONB,                            -- تفاصيل إضافية (القيم قبل/بعد)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_logs_actor_user_id ON audit_logs (actor_user_id);
CREATE INDEX idx_audit_logs_target        ON audit_logs (target_type, target_id);
CREATE INDEX idx_audit_logs_created_at    ON audit_logs (created_at);
