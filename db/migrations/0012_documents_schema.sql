-- 0012_documents_schema.sql
-- الهدف: قاعدة بيانات وحدة "إدارة الوثائق" (Document Management) — كيان مستقل
-- قابل للربط لاحقًا باللجان/الاجتماعات/المهام/القرارات عبر document_links
-- بدون تعديل هذا الـSchema عند بناء تلك الوحدات مستقبلًا.
--
-- يشمل:
--  - documents / document_categories (عامة Super Admin أو خاصة بإدارة).
--  - نطاق رؤية متعدد ومركّب: عام / إدارات / لجان / مستخدمون محددون.
--  - عمود content_tsv (Full-Text Search مجاني عبر PostgreSQL).
--  - عمود embedding (pgvector) جاهز للبحث الدلالي المستقبلي عبر Gemini.
--
-- ملاحظة: هذا الملف طُبّق مسبقًا على قاعدة بيانات Supabase الحية بواسطة
-- Claude بتاريخ 2026-08-26. كتالوج صلاحيات الوثائق (documents.* و
-- document_categories.*) ومنح الأدوار الأساسية لها أُدرجا يدويًا حينها
-- مباشرة على القاعدة الحية بدل ملف Migration — وثّقناها لاحقًا في
-- 0013_documents_permissions.sql حتى لا يبقى انحراف (Drift) بين db/migrations/
-- والقاعدة الفعلية.
--
-- ملاحظة تصحيح (بعد المراجعة): هذا الملف كان يحتوي محتواه مكرَّرًا مرتين
-- بالخطأ (نفس الأوامر من CREATE EXTENSION إلى نهاية الملف، مرتين) — نتيجة
-- تشغيله على قاعدة فيها الجداول مسبقًا (كالحال هنا) يُنتج سلسلة أخطاء
-- "already exists" غير ضارة لكنها مربكة لأي عضو فريق يشغّل الملف من
-- الصفر لأول مرة. صُحِّح هنا لنسخة واحدة نظيفة؛ لا تأثير على القاعدة
-- الحية لأنها مطبَّقة أصلًا ولم تتغيّر.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TYPE document_status AS ENUM ('active', 'archived');
CREATE TYPE document_category_scope AS ENUM ('global', 'department');

CREATE TABLE public.document_categories (
            category_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            VARCHAR(150) NOT NULL,
            scope           document_category_scope NOT NULL,
            department_id   UUID NULL REFERENCES public.departments(dep_id),
            created_by      UUID NOT NULL REFERENCES public.users(user_id),
            deleted_at      TIMESTAMPTZ NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT document_categories_scope_department_chk CHECK (
                (scope = 'global' AND department_id IS NULL) OR
                (scope = 'department' AND department_id IS NOT NULL)
            )
        );

CREATE UNIQUE INDEX document_categories_global_name_uq
    ON public.document_categories (lower(name))
    WHERE scope = 'global' AND deleted_at IS NULL;

CREATE UNIQUE INDEX document_categories_department_name_uq
    ON public.document_categories (department_id, lower(name))
    WHERE scope = 'department' AND deleted_at IS NULL;

CREATE TABLE public.documents (
            document_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            title           VARCHAR(255) NOT NULL,
            description     TEXT NULL,
            file_name       VARCHAR(255) NOT NULL,
            storage_path    VARCHAR(500) NOT NULL,
            mime_type       VARCHAR(150) NOT NULL,
            file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes > 0),
            category_id     UUID NULL REFERENCES public.document_categories(category_id),
            status          document_status NOT NULL DEFAULT 'active',
            is_public       BOOLEAN NOT NULL DEFAULT false,
            content_text    TEXT NULL,
            content_tsv     TSVECTOR GENERATED ALWAYS AS (
                                to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(description,'') || ' ' || coalesce(content_text,''))
                            ) STORED,
            embedding       VECTOR(768) NULL,
            uploaded_by     UUID NOT NULL REFERENCES public.users(user_id),
            deleted_at      TIMESTAMPTZ NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );

CREATE INDEX documents_content_tsv_idx ON public.documents USING GIN (content_tsv);
CREATE INDEX documents_category_id_idx ON public.documents (category_id);
CREATE INDEX documents_uploaded_by_idx ON public.documents (uploaded_by);

CREATE TABLE public.document_visibility_departments (
            document_id     UUID NOT NULL REFERENCES public.documents(document_id) ON DELETE CASCADE,
            department_id   UUID NOT NULL REFERENCES public.departments(dep_id) ON DELETE CASCADE,
            PRIMARY KEY (document_id, department_id)
        );

CREATE TABLE public.document_visibility_committees (
            document_id     UUID NOT NULL REFERENCES public.documents(document_id) ON DELETE CASCADE,
            committee_id    UUID NOT NULL REFERENCES public.committees(committee_id) ON DELETE CASCADE,
            PRIMARY KEY (document_id, committee_id)
        );

CREATE TABLE public.document_visibility_users (
            document_id     UUID NOT NULL REFERENCES public.documents(document_id) ON DELETE CASCADE,
            user_id         UUID NOT NULL REFERENCES public.users(user_id) ON DELETE CASCADE,
            PRIMARY KEY (document_id, user_id)
        );

CREATE TABLE public.document_links (
            document_id         UUID NOT NULL REFERENCES public.documents(document_id) ON DELETE CASCADE,
            linked_entity_type  VARCHAR(50) NOT NULL,
            linked_entity_id    UUID NOT NULL,
            linked_by           UUID NOT NULL REFERENCES public.users(user_id),
            linked_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (document_id, linked_entity_type, linked_entity_id)
        );

ALTER TABLE public.document_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_visibility_departments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_visibility_committees ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_visibility_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_links ENABLE ROW LEVEL SECURITY;

CREATE TRIGGER trg_document_categories_set_updated_at
    BEFORE UPDATE ON public.document_categories
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_documents_set_updated_at
    BEFORE UPDATE ON public.documents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- توسعة سجل التدقيق ليدعم أحداث الوثائق (خارج نفس معاملة الجداول أعلاه
-- بحسب قيود PostgreSQL على ALTER TYPE ... ADD VALUE).
ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'upload';
ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'download';
