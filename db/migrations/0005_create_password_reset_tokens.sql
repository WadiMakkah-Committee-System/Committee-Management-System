-- =====================================================================
-- 0005_create_password_reset_tokens.sql
-- الهدف: آلية "نسيت كلمة المرور" عبر OTP بالبريد الإلكتروني — FR-UM-018
-- =====================================================================

-- جدول Append-only بشكل أساسي (السجل يُحدَّث مرة وحدة فقط عند الاستخدام
-- عبر used_at) — لا يحتوي updated_at عمدًا.
CREATE TABLE password_reset_tokens (
    token_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(user_id),
    otp_code_hash VARCHAR(255) NOT NULL,   -- لا يُخزَّن رمز OTP كنص صريح
    expires_at    TIMESTAMPTZ NOT NULL,
    used_at       TIMESTAMPTZ,             -- NULLABLE - يُملأ عند استخدام الرمز
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_password_reset_tokens_user_id ON password_reset_tokens (user_id);
