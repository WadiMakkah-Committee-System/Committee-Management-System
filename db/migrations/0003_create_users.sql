-- =====================================================================
-- 0003_create_users.sql
-- الهدف: جدول المستخدمين + الأدوار العامة + المصادقة
--        FR-UM-001 → FR-UM-006, FR-UM-011 → FR-UM-022
-- =====================================================================

-- الأدوار العامة (Global Roles) على مستوى النظام.
-- أدوار اللجان (رئيس لجنة / عضو لجنة / مطلع CC / عضو بديل) ليست هنا —
-- تلك أدوار Scoped لكل لجنة على حدة وتُصمَّم مع جدول اللجان بمرحلة لاحقة.
CREATE TYPE user_role AS ENUM (
    'super_admin',
    'admin',
    'executive_president',
    'executive_office_manager',
    'executive_office_secretary'
);

-- حالة الحساب — FR-UM-004 (إيقاف مؤقت يمنع تسجيل الدخول فقط)
CREATE TYPE user_status AS ENUM ('active', 'suspended');

CREATE TABLE users (
    user_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    first_name             VARCHAR(100) NOT NULL,
    middle_name            VARCHAR(100) NOT NULL,
    last_name              VARCHAR(100) NOT NULL,

    username                VARCHAR(50)  NOT NULL,     -- تفرد فعلي عبر index جزئي أدناه
    email                    VARCHAR(255) NOT NULL,     -- تفرد فعلي عبر index جزئي أدناه
    password_hash            VARCHAR(255) NOT NULL,     -- bcrypt hash — لا يُخزَّن أي نص صريح

    role                     user_role NOT NULL,
    dep_id                   UUID REFERENCES departments(dep_id),   -- NULLABLE لأدوار مثل super_admin

    status                   user_status NOT NULL DEFAULT 'active',
    must_change_password     BOOLEAN NOT NULL DEFAULT true,          -- FR-UM-016

    failed_login_attempts    SMALLINT NOT NULL DEFAULT 0,             -- FR-UM-019
    locked_until             TIMESTAMPTZ,                             -- قفل 15 دقيقة بعد 5 محاولات فاشلة
    last_login_at            TIMESTAMPTZ,

    deleted_at               TIMESTAMPTZ,                             -- Soft Delete — FR-UM-005

    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- تفرد username وemail، باستثناء الحسابات المحذوفة (Soft Delete) — يسمح
-- بإعادة استخدام نفس البريد/الاسم لحساب جديد بعد حذف القديم.
CREATE UNIQUE INDEX uq_users_username_active ON users (username) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_users_email_active    ON users (email)    WHERE deleted_at IS NULL;

-- Indexes لتسريع الاستعلامات المتكررة (تصفية حسب الإدارة أو الحالة)
CREATE INDEX idx_users_dep_id ON users (dep_id);
CREATE INDEX idx_users_status ON users (status);

CREATE TRIGGER trg_users_set_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();
