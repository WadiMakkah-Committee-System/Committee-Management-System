-- =====================================================================
-- 0051_tickets.sql
-- الهدف: وحدة "التذاكر" (الدعم الفني) — طلب صاحب المشروع 2026-11-17.
-- المرجع الكامل للمتطلبات: مواصفات نظام التذاكر (tickets_spec.md بمشروع
-- "ادارة اللجان"). هذا الملف طبقة قاعدة البيانات فقط — لا يوجد Backend بعد.
--
-- الجداول:
--   1) ticket_number_counters — عدّاد سنوي لرقم التذكرة (TKT-2026-0001).
--   2) tickets                — التذكرة: نوعها ووحدتها وأولويتها وحالتها وإسنادها.
--   3) ticket_messages        — المحادثة: رد عام أو ملاحظة داخلية. الوصف = أول رسالة.
--   4) ticket_attachments     — مرفقات الرسائل.
--   + قسم صلاحيات جديد "tickets"، ومنح tickets.create لكل الأدوار النظامية الحالية.
--
-- قرارات التصميم:
-- 1) الوصف هو أول رسالة بالمحادثة (is_description = true) وليس عمودًا بجدول
--    tickets — نفس نمط Zendesk. الفايدة: مرفقات البلاغ الأول تتبع رسالة مثل
--    أي رد، والمحادثة تبدأ بالوصف بدون معالجة خاصة. قيد مؤجَّل (عند COMMIT)
--    يضمن أن كل تذكرة لها وصف واحد بالضبط.
-- 2) سجل التذكرة (TKT-FR-017: من غيّر الحالة/الإسناد/الأولوية ومتى) يُقرأ من
--    audit_logs (target_type = 'ticket') — الفهرس idx_audit_logs_target موجود،
--    وactor_role_id يحفظ الصفة. لا جدول أحداث منفصل حتى لا يتكرر نفس السجل.
-- 3) مرفقات التذاكر بجدول مستقل، وليس documents/document_links: لقطات الشاشة
--    وملفات البلاغات ما لازم تظهر بمكتبة الوثائق أو بالبحث الدلالي.
-- 4) القيم الثابتة (النوع، الوحدة، الأولوية، الحالة): VARCHAR + CHECK بدل
--    ENUM — نفس سبب migration 0014 (إضافة قيمة لاحقًا بأمر ALTER بسيط).
-- 5) سلامة الحالة بقاعدة البيانات نفسها: trigger يرفض أي انتقال غير موجود
--    بجدول الانتقالات (القسم 4 بالمواصفات)، وقيود CHECK تربط كل حالة بتاريخها
--    (resolved_at/closed_at/cancelled_at). الـ triggers هنا **تتحقق فقط** ولا
--    تغيّر الحالة أو التواريخ بنفسها — طبقة الخدمة هي اللي تضبطها، عشان كائن
--    الـ ORM ما يصير قديم بعد الحفظ (expire_on_commit=False بهذا المشروع).
--    الاستثناءان: رقم التذكرة (يُولَّد عند الإدراج) وlast_public_activity_at
--    (عمود عرض فقط، مثل updated_at).
--    "من يحق له" ينفّذ الانتقال (مقدّم الطلب أو الدعم) يبقى بطبقة الخدمة.
-- 6) الرسائل والمرفقات لا تُعدَّل ولا تُحذف بعد الإرسال (trigger) — مطابق
--    للمواصفات (القسم 7).
-- 7) client_message_id: معرّف يولّده المتصفح لكل رسالة — لو أعاد المستخدم
--    المحاولة (العرض المتفائل، TKT-FR-025) والطلب الأول كان نجح فعليًا، القيد
--    الفريد يمنع تكرار الرسالة.
-- 8) السنة برقم التذكرة بتوقيت الرياض (تذكرة الساعة 12:30 فجر 1 يناير تاخذ
--    السنة الجديدة).
-- 9) الحذف: لا يوجد حذف للتذاكر بالمواصفات — المفاتيح الأجنبية بلا CASCADE،
--    فأي محاولة حذف لتذكرة لها رسائل تُرفض.
-- 10) كل دوال الـ triggers هنا مثبّت فيها search_path = public, pg_temp — توصية
--    مدقق أمان Supabase (function_search_path_mutable): ما تتأثر الدالة بأي
--    search_path يضبطه المستخدم المتصل.
-- =====================================================================

BEGIN;

-- ============================ 1) عدّاد أرقام التذاكر ============================
-- صف واحد لكل سنة. التوليد بـ INSERT ... ON CONFLICT DO UPDATE يقفل صف السنة
-- لين نهاية المعاملة، فتذكرتان بنفس اللحظة ما ياخذون نفس الرقم. ولو فشلت
-- المعاملة يرجع العداد معها (ما فيه أرقام ضايعة).
CREATE TABLE ticket_number_counters (
    year     SMALLINT PRIMARY KEY,
    last_seq INT NOT NULL,
    CONSTRAINT ticket_number_counters_year_chk CHECK (year BETWEEN 2020 AND 9999),
    CONSTRAINT ticket_number_counters_seq_chk CHECK (last_seq > 0)
);

COMMENT ON TABLE ticket_number_counters IS
    'آخر تسلسل مستخدم لأرقام التذاكر لكل سنة ميلادية (بتوقيت الرياض) — يُحدَّث فقط من trigger إدراج التذاكر';

-- ============================ 2) التذاكر ============================
CREATE TABLE tickets (
    ticket_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- رقم التذكرة: السنة والتسلسل يولّدهم trigger الإدراج (أي قيمة مرسلة تُستبدل).
    number_year   SMALLINT NOT NULL,
    number_seq    INT NOT NULL,
    -- الصيغة النهائية للعرض والبحث: TKT-2026-0042 (4 أرقام على الأقل، وتكبر بعد 9999).
    ticket_number VARCHAR(20) GENERATED ALWAYS AS (
        'TKT-' || number_year::text || '-'
        || lpad(number_seq::text, GREATEST(4, length(number_seq::text)), '0')
    ) STORED,

    requester_id  UUID NOT NULL REFERENCES users(user_id),
    title         VARCHAR(150) NOT NULL,
    ticket_type   VARCHAR(20) NOT NULL,
    module        VARCHAR(30) NOT NULL,
    priority      VARCHAR(10) NOT NULL DEFAULT 'medium',
    status        VARCHAR(25) NOT NULL DEFAULT 'new',
    -- عضو الدعم المسؤول — واحد أو فارغ. بلا FK CASCADE: المستخدمين يُحذفون حذفًا ناعمًا.
    assignee_id   UUID REFERENCES users(user_id),

    -- "آخر تحديث" اللي يشوفه مقدّم الطلب: آخر رسالة عامة أو تغيير حالة.
    -- الملاحظات الداخلية والإسناد والأولوية ما تحرّكه (ما يكشف نشاط الدعم الداخلي).
    last_public_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    resolved_at   TIMESTAMPTZ,
    closed_at     TIMESTAMPTZ,
    cancelled_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT tickets_number_uq UNIQUE (number_year, number_seq),
    CONSTRAINT tickets_number_seq_chk CHECK (number_seq > 0),
    CONSTRAINT tickets_title_len_chk CHECK (char_length(btrim(title)) BETWEEN 5 AND 150),
    CONSTRAINT tickets_type_chk CHECK (
        ticket_type IN ('change_request', 'bug', 'inquiry', 'account_access')
    ),
    CONSTRAINT tickets_module_chk CHECK (
        module IN ('users_departments', 'committees', 'meetings', 'tasks', 'decisions',
                   'documents', 'minutes', 'dashboard', 'other')
    ),
    CONSTRAINT tickets_priority_chk CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    CONSTRAINT tickets_status_chk CHECK (
        status IN ('new', 'in_progress', 'waiting_on_requester', 'resolved', 'closed', 'cancelled')
    ),
    -- "جديدة" = ما أحد استلمها. الاستلام ينقلها لـ "قيد المعالجة" بنفس الخطوة.
    CONSTRAINT tickets_new_unassigned_chk CHECK (status <> 'new' OR assignee_id IS NULL),
    -- الإلغاء متاح فقط وهي "جديدة"، فالملغاة ما لها مسند إليه.
    CONSTRAINT tickets_cancelled_unassigned_chk CHECK (status <> 'cancelled' OR assignee_id IS NULL),
    -- كل حالة نهائية/محلولة مربوطة بتاريخها، والعكس.
    -- المغلقة تمر دائمًا بـ "تم الحل"، فتحتفظ بـ resolved_at.
    CONSTRAINT tickets_resolved_at_chk CHECK ((status IN ('resolved', 'closed')) = (resolved_at IS NOT NULL)),
    CONSTRAINT tickets_closed_at_chk CHECK ((status = 'closed') = (closed_at IS NOT NULL)),
    CONSTRAINT tickets_cancelled_at_chk CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL))
);

COMMENT ON TABLE tickets IS
    'تذاكر الدعم الفني — الوصف هو أول رسالة في ticket_messages، وسجل التغييرات في audit_logs (target_type = ticket)';
COMMENT ON COLUMN tickets.ticket_type IS
    'change_request: طلب تعديل أو ميزة | bug: بلاغ خلل | inquiry: استفسار | account_access: مشكلة حساب أو صلاحية';
COMMENT ON COLUMN tickets.module IS
    'الوحدة المتأثرة: users_departments | committees | meetings | tasks | decisions | documents | minutes | dashboard | other';
COMMENT ON COLUMN tickets.status IS
    'new: جديدة | in_progress: قيد المعالجة | waiting_on_requester: بانتظار رد المستخدم | resolved: تم الحل | closed: مغلقة | cancelled: ملغاة';

-- البحث بالرقم (TKT-2026-0042).
CREATE UNIQUE INDEX uq_tickets_ticket_number ON tickets (ticket_number);
-- "تذاكري" لمقدّم الطلب، بترتيب آخر تحديث.
CREATE INDEX idx_tickets_requester_activity ON tickets (requester_id, last_public_activity_at DESC);
-- تبويب "المسندة لي" للدعم (المفتوحة فقط).
CREATE INDEX idx_tickets_assignee_open ON tickets (assignee_id)
    WHERE status NOT IN ('closed', 'cancelled');
-- تبويب "غير مسندة".
CREATE INDEX idx_tickets_unassigned_open ON tickets (created_at)
    WHERE assignee_id IS NULL AND status NOT IN ('closed', 'cancelled');
-- تبويب "الكل" مع فلتر الحالة.
CREATE INDEX idx_tickets_status_updated ON tickets (status, updated_at DESC);
-- مهمة الإغلاق التلقائي بالمجدول (تم الحل منذ 4 أيام).
CREATE INDEX idx_tickets_resolved_due ON tickets (resolved_at) WHERE status = 'resolved';

-- ---------- trigger الإدراج: الحالة الابتدائية + مقدّم الطلب + توليد الرقم ----------
CREATE OR REPLACE FUNCTION tickets_before_insert()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_is_guest BOOLEAN;
    v_year     SMALLINT;
    v_seq      INT;
BEGIN
    IF NEW.status <> 'new' THEN
        RAISE EXCEPTION 'tickets: التذكرة تبدأ دائمًا بحالة new (المرسلة: %)', NEW.status
            USING ERRCODE = 'check_violation';
    END IF;

    -- ضيوف الاجتماعات (migration 0047) حسابات مؤقتة — ما يرسلون تذاكر.
    SELECT is_guest INTO v_is_guest FROM users WHERE user_id = NEW.requester_id;
    IF v_is_guest THEN
        RAISE EXCEPTION 'tickets: حساب ضيف الاجتماع لا يرسل تذاكر'
            USING ERRCODE = 'check_violation';
    END IF;

    v_year := EXTRACT(YEAR FROM (NEW.created_at AT TIME ZONE 'Asia/Riyadh'))::SMALLINT;

    INSERT INTO ticket_number_counters AS c (year, last_seq)
    VALUES (v_year, 1)
    ON CONFLICT (year) DO UPDATE SET last_seq = c.last_seq + 1
    RETURNING c.last_seq INTO v_seq;

    NEW.number_year := v_year;
    NEW.number_seq := v_seq;
    NEW.last_public_activity_at := NEW.created_at;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_tickets_before_insert
    BEFORE INSERT ON tickets
    FOR EACH ROW
    EXECUTE FUNCTION tickets_before_insert();

-- ---------- trigger التعديل: الأعمدة الثابتة + قفل النهائية + جدول الانتقالات ----------
CREATE OR REPLACE FUNCTION tickets_before_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    -- المغلقة والملغاة للقراءة فقط.
    IF OLD.status IN ('closed', 'cancelled') THEN
        RAISE EXCEPTION 'tickets: التذكرة % بحالة % ولا يمكن تعديلها', OLD.ticket_number, OLD.status
            USING ERRCODE = 'check_violation';
    END IF;

    IF NEW.requester_id IS DISTINCT FROM OLD.requester_id
       OR NEW.number_year IS DISTINCT FROM OLD.number_year
       OR NEW.number_seq IS DISTINCT FROM OLD.number_seq
       OR NEW.title IS DISTINCT FROM OLD.title
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'tickets: مقدّم الطلب والرقم والعنوان وتاريخ الإنشاء لا تتغير'
            USING ERRCODE = 'check_violation';
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status THEN
        -- جدول الانتقالات المسموحة (القسم 4 بالمواصفات).
        IF NOT (
               (OLD.status = 'new'                  AND NEW.status IN ('in_progress', 'resolved', 'cancelled'))
            OR (OLD.status = 'in_progress'          AND NEW.status IN ('waiting_on_requester', 'resolved'))
            OR (OLD.status = 'waiting_on_requester' AND NEW.status IN ('in_progress', 'resolved'))
            OR (OLD.status = 'resolved'             AND NEW.status IN ('in_progress', 'closed'))
        ) THEN
            RAISE EXCEPTION 'tickets: انتقال غير مسموح من % إلى %', OLD.status, NEW.status
                USING ERRCODE = 'check_violation';
        END IF;

        -- تغيير الحالة يظهر لمقدّم الطلب.
        NEW.last_public_activity_at := now();
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_tickets_before_update
    BEFORE UPDATE ON tickets
    FOR EACH ROW
    EXECUTE FUNCTION tickets_before_update();

CREATE TRIGGER trg_tickets_set_updated_at
    BEFORE UPDATE ON tickets
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ============================ 3) رسائل التذكرة ============================
CREATE TABLE ticket_messages (
    message_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id         UUID NOT NULL REFERENCES tickets(ticket_id),
    author_id         UUID NOT NULL REFERENCES users(user_id),
    -- الصفة اللي كتب بها: requester (صاحب التذكرة) أو support (عضو الدعم).
    -- تحدد شكل الفقاعة ومستلمي الإشعار، وتفرّق لو عضو الدعم هو نفسه صاحب التذكرة.
    author_side       VARCHAR(10) NOT NULL,
    is_internal       BOOLEAN NOT NULL DEFAULT false,
    is_description    BOOLEAN NOT NULL DEFAULT false,
    -- محتوى TipTap كـ JSON (يُعرض بـ TipTap للقراءة، بدون HTML خام).
    body_json         JSONB NOT NULL,
    -- النص المجرّد من body_json (تولّده طبقة الخدمة): لفحص الطول والبحث ونص الإشعار.
    body_text         TEXT NOT NULL,
    client_message_id UUID,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ticket_messages_side_chk CHECK (author_side IN ('requester', 'support')),
    CONSTRAINT ticket_messages_internal_support_chk CHECK (NOT is_internal OR author_side = 'support'),
    CONSTRAINT ticket_messages_description_chk CHECK (
        NOT is_description OR (author_side = 'requester' AND NOT is_internal)
    ),
    CONSTRAINT ticket_messages_body_doc_chk CHECK (
        jsonb_typeof(body_json) = 'object' AND body_json ->> 'type' = 'doc'
    ),
    CONSTRAINT ticket_messages_body_json_size_chk CHECK (octet_length(body_json::text) <= 200000),
    -- الوصف 10 إلى 5000 حرف. الرد: حتى 5000، ويُسمح بنص فاضي لو معه مرفق
    -- (القيد المؤجَّل trg_ticket_messages_require_content أدناه).
    CONSTRAINT ticket_messages_body_len_chk CHECK (
        char_length(btrim(body_text))
            BETWEEN (CASE WHEN is_description THEN 10 ELSE 0 END) AND 5000
    )
);

COMMENT ON TABLE ticket_messages IS
    'محادثة التذكرة — رد عام أو ملاحظة داخلية (للدعم فقط). الرسائل لا تُعدَّل ولا تُحذف';
COMMENT ON COLUMN ticket_messages.client_message_id IS
    'معرّف من المتصفح لمنع تكرار الرسالة عند إعادة المحاولة (العرض المتفائل)';

CREATE INDEX idx_ticket_messages_ticket_created ON ticket_messages (ticket_id, created_at);
-- وصف واحد فقط لكل تذكرة.
CREATE UNIQUE INDEX uq_ticket_messages_description ON ticket_messages (ticket_id) WHERE is_description;
-- عدم التكرار عند إعادة المحاولة.
CREATE UNIQUE INDEX uq_ticket_messages_client_id ON ticket_messages (author_id, client_message_id)
    WHERE client_message_id IS NOT NULL;

-- ---------- trigger إدراج الرسالة: التذكرة مفتوحة + هوية صاحب الطلب ----------
CREATE OR REPLACE FUNCTION ticket_messages_before_insert()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_status       VARCHAR(25);
    v_requester_id UUID;
BEGIN
    -- قفل صف التذكرة (نفس مستوى قفل UPDATE العادي): يمنع تعارض رسالة مع إغلاق
    -- تلقائي بنفس اللحظة، وما يسبب Deadlock مع تحديث last_public_activity_at.
    SELECT status, requester_id INTO v_status, v_requester_id
    FROM tickets
    WHERE ticket_id = NEW.ticket_id
    FOR NO KEY UPDATE;

    IF v_status IN ('closed', 'cancelled') THEN
        RAISE EXCEPTION 'ticket_messages: لا يمكن الرد على تذكرة بحالة %', v_status
            USING ERRCODE = 'check_violation';
    END IF;

    IF NEW.author_side = 'requester' AND NEW.author_id IS DISTINCT FROM v_requester_id THEN
        RAISE EXCEPTION 'ticket_messages: رسالة بصفة مقدّم الطلب لازم يكتبها صاحب التذكرة نفسه'
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_ticket_messages_before_insert
    BEFORE INSERT ON ticket_messages
    FOR EACH ROW
    EXECUTE FUNCTION ticket_messages_before_insert();

-- ---------- بعد الإدراج: الرسالة العامة تحدّث "آخر تحديث" للتذكرة ----------
CREATE OR REPLACE FUNCTION ticket_messages_after_insert()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NOT NEW.is_internal THEN
        UPDATE tickets
        SET last_public_activity_at = NEW.created_at
        WHERE ticket_id = NEW.ticket_id
          AND last_public_activity_at < NEW.created_at;
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_ticket_messages_after_insert
    AFTER INSERT ON ticket_messages
    FOR EACH ROW
    EXECUTE FUNCTION ticket_messages_after_insert();

-- ---------- منع التعديل والحذف (مشتركة بين الرسائل والمرفقات) ----------
CREATE OR REPLACE FUNCTION ticket_content_immutable()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION '%: الرسائل والمرفقات لا تُعدَّل ولا تُحذف بعد الإرسال', TG_TABLE_NAME
        USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER trg_ticket_messages_immutable
    BEFORE UPDATE OR DELETE ON ticket_messages
    FOR EACH ROW
    EXECUTE FUNCTION ticket_content_immutable();

-- ============================ 4) مرفقات الرسائل ============================
-- الرافع = كاتب الرسالة (ما يحتاج عمود). حد الحجم من الإعدادات
-- (MAX_DOCUMENT_UPLOAD_MB) بطبقة الخدمة، لأنه قابل للتغيير بدون migration.
CREATE TABLE ticket_attachments (
    attachment_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id      UUID NOT NULL REFERENCES ticket_messages(message_id),
    file_name       VARCHAR(255) NOT NULL,
    storage_path    VARCHAR(500) NOT NULL,
    mime_type       VARCHAR(150) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ticket_attachments_storage_path_uq UNIQUE (storage_path),
    CONSTRAINT ticket_attachments_file_name_chk CHECK (char_length(btrim(file_name)) > 0),
    CONSTRAINT ticket_attachments_size_chk CHECK (file_size_bytes > 0),
    -- PNG وJPG وPDF وDOCX وXLSX (القسم 5 بالمواصفات).
    CONSTRAINT ticket_attachments_mime_chk CHECK (
        mime_type IN (
            'image/png',
            'image/jpeg',
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    )
);

COMMENT ON TABLE ticket_attachments IS
    'مرفقات رسائل التذاكر — 5 ملفات كحد أقصى لكل رسالة، وتتبع ظهور رسالتها (مرفقات الملاحظة الداخلية للدعم فقط)';

CREATE INDEX idx_ticket_attachments_message ON ticket_attachments (message_id);

-- ---------- 5 مرفقات كحد أقصى لكل رسالة ----------
CREATE OR REPLACE FUNCTION ticket_attachments_before_insert()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_count INT;
BEGIN
    -- قفل صف الرسالة يمنع إضافتين متزامنتين تتجاوزان الحد (SELECT FOR UPDATE
    -- ما يشغّل trigger منع التعديل).
    PERFORM 1 FROM ticket_messages WHERE message_id = NEW.message_id FOR UPDATE;

    SELECT count(*) INTO v_count FROM ticket_attachments WHERE message_id = NEW.message_id;
    IF v_count >= 5 THEN
        RAISE EXCEPTION 'ticket_attachments: الحد الأقصى 5 مرفقات لكل رسالة'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_ticket_attachments_before_insert
    BEFORE INSERT ON ticket_attachments
    FOR EACH ROW
    EXECUTE FUNCTION ticket_attachments_before_insert();

CREATE TRIGGER trg_ticket_attachments_immutable
    BEFORE UPDATE OR DELETE ON ticket_attachments
    FOR EACH ROW
    EXECUTE FUNCTION ticket_content_immutable();

-- ============================ 5) قيود مؤجَّلة (تُفحص عند COMMIT) ============================
-- التذكرة + وصفها + مرفقاته تنحفظ بمعاملة واحدة، فالفحص لازم يكون بعد ما تكتمل.

-- كل تذكرة لازم يكون لها وصف (أول رسالة).
CREATE OR REPLACE FUNCTION tickets_require_description()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ticket_messages WHERE ticket_id = NEW.ticket_id AND is_description
    ) THEN
        RAISE EXCEPTION 'tickets: التذكرة لازم تُحفظ مع وصفها (رسالة is_description) بنفس المعاملة'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER trg_tickets_require_description
    AFTER INSERT ON tickets
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    EXECUTE FUNCTION tickets_require_description();

-- الرد لازم يكون فيه نص أو مرفق واحد على الأقل.
CREATE OR REPLACE FUNCTION ticket_messages_require_content()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    IF char_length(btrim(NEW.body_text)) = 0 AND NOT EXISTS (
        SELECT 1 FROM ticket_attachments WHERE message_id = NEW.message_id
    ) THEN
        RAISE EXCEPTION 'ticket_messages: الرسالة لازم يكون فيها نص أو مرفق'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER trg_ticket_messages_require_content
    AFTER INSERT ON ticket_messages
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    EXECUTE FUNCTION ticket_messages_require_content();

-- ============================ 6) كتالوج الصلاحيات ============================
-- قسم جديد "tickets" بشاشة الأدوار والصلاحيات (القسم 6 بالمواصفات).
INSERT INTO permissions (code, category, label_ar, sort_order, kind) VALUES
    ('tickets.create',         'tickets', 'إرسال التذاكر ومتابعتها', 110, 'system'),
    ('tickets.view_all',       'tickets', 'عرض جميع التذاكر',        111, 'system'),
    ('tickets.reply',          'tickets', 'الرد على التذاكر',        112, 'system'),
    ('tickets.internal_notes', 'tickets', 'الملاحظات الداخلية',      113, 'system'),
    ('tickets.manage',         'tickets', 'إدارة التذكرة',           114, 'system'),
    ('tickets.assign',         'tickets', 'إسناد التذكرة',           115, 'system')
ON CONFLICT (code) DO NOTHING;

-- "إرسال التذاكر ومتابعتها" لكل الأدوار النظامية الموجودة الآن — منها
-- super_admin و"مستخدم نظام" (المنشأ يدويًا بالإنتاج) — عشان ما أحد يفقد
-- القدرة على الإرسال يوم الإطلاق. النطاق own: الصلاحية مقيدة دائمًا بتذاكر
-- المستخدم نفسه. أدوار اللجان (kind = 'committee') خارجها لأنها ما تُسند
-- كدور نظامي. أي دور يُنشأ بعد هذا الملف يفعّلها له السوبر أدمن من الشاشة.
-- خانات الدعم الخمس ما تُمنح لأي دور (قرار 2026-11-17).
INSERT INTO role_permissions (role_id, permission_id, scope)
SELECT r.role_id, p.permission_id, 'own'
FROM roles r
CROSS JOIN permissions p
WHERE r.kind = 'user'
  AND p.code = 'tickets.create'
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ============================ 7) RLS ============================
-- نفس نمط الجداول الجديدة (0047، 0049): يمنع الوصول المباشر من واجهة Supabase
-- العامة (anon/authenticated)؛ الخادم الخلفي يتصل بصلاحية مالك الجداول فلا يتأثر.
ALTER TABLE ticket_number_counters ENABLE ROW LEVEL SECURITY;
ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE ticket_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE ticket_attachments ENABLE ROW LEVEL SECURITY;

COMMIT;
