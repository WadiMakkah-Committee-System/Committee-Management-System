-- =====================================================================
-- 0024_tasks_schema.sql
-- الهدف: وحدة "إدارة المهام" — الإنشاء المباشر من واجهة المهام فقط
-- (§4 SRS، §6 BRS) — بدون مسار استخراج البنود من ملخص الاجتماع بالذكاء
-- الاصطناعي (FR-TASK-005 إلى FR-TASK-012)؛ هذا يُبنى لاحقًا مع تكامل
-- AI/Teams، بنفس القرار المتّبع بوحدة القرارات (decisions، migration
-- 0021). لا تُلمس meetings.* أو decisions.* بهذا الملف إطلاقًا.
--
-- ملاحظات تصميم واجتهادات موثّقة (بالاتفاق مع صاحبة المشروع 2026-09-06):
-- 1) مسؤول واحد فقط لكل مهمة في أي لحظة (FR-TASK-002: "الشخص المسؤول"
--    بصيغة المفرد حرفيًا) — بخلاف نمط decision_assignees (منفذون
--    متعددون تلقائيًا من أعضاء اللجنة). قرار صريح: عدم السماح بتعدد
--    المسؤولين المتزامن، تفاديًا لتذويب المسؤولية (نفس منطق نموذج DRI
--    المتّبع بمنصات مثل Asana/Jira). عمود assignee_user_id بسيط، لا جدول
--    ربط.
-- 2) "مسار المهمة" (Task Trail) — ميزة إضافية اقترحتها صاحبة المشروع
--    (خارج BRS/SRS الأصلي، 2026-09-06): تتبّع من كان مسؤولًا عن المهمة
--    عبر الزمن، ظاهر بواجهة تفاصيل المهمة حتى اكتمالها. لهذا أُفرد جدول
--    مخصّص (task_assignment_history) بدل الاكتفاء بـaudit_logs العام —
--    لأنها ميزة عرض أساسية بالواجهة (Front-and-center) لا مجرد سجل
--    تدقيق خلفي، فتحتاج استعلامًا مباشرًا وسريعًا لكل مهمة. تحديثات
--    الحالة (FR-TASK-013/016) تبقى تُسجَّل بـaudit_logs فقط، بنفس نمط
--    القرارات — بدون جدول تاريخ حالة مخصّص (لا حاجة موثّقة له، بخلاف
--    إعادة التعيين).
-- 3) enum الحالة بالإنجليزي داخليًا (todo/in_progress/on_hold/completed)
--    مع عرض ثنائي اللغة (عربي/إنجليزي، NFR-USA-001) بطبقة الواجهة —
--    نفس نمط decision_status/decision_classification بالضبط، لا قيم
--    عربية خامًا بقاعدة البيانات.
-- 4) القفل الحرج (FR-TASK-016/018): التعديل/الحذف ممنوعان فعليًا إذا
--    status = 'completed' — يُفرض بطبقة الخدمة (Backend)، غير قابل
--    للتعبير كـCHECK constraint وحيد لأنه يعتمد على القيمة قبل التحديث.
-- 5) عضوية assignee_user_id باللجنة (عضو أو رئيسها) — نفس قيد
--    decision_assignees (بدون فرضه كـDB constraint، يُتحقق منه بطبقة
--    الخدمة لأنه يتطلب JOIN مع committee_members).
-- 6) بدون أي ربط بالوثائق أو تذكيرات بهذه المرحلة — نفس نطاق القرارات.
-- =====================================================================

CREATE TYPE task_status AS ENUM (
    'todo',         -- للقيام — الحالة الافتراضية عند الإنشاء (FR-TASK-003)
    'in_progress',  -- جارية
    'on_hold',      -- معلقة
    'completed'     -- مكتملة — تُنهي دورة المتابعة تلقائيًا (FR-TASK-015)
);

-- ============================== المهمة ==============================
CREATE TABLE tasks (
    task_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    committee_id     UUID NOT NULL REFERENCES committees(committee_id),
    title            VARCHAR(255) NOT NULL,               -- اسم المهمة (FR-TASK-002)
    status           task_status NOT NULL DEFAULT 'todo',

    start_date       DATE NOT NULL,                       -- تاريخ البدء
    end_date         DATE NOT NULL,                        -- تاريخ الانتهاء

    assignee_user_id UUID NOT NULL REFERENCES users(user_id),  -- المسؤول الحالي — واحد فقط (ملاحظة 1)

    created_by       UUID NOT NULL REFERENCES users(user_id),

    deleted_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT tasks_end_after_start_chk CHECK (end_date >= start_date)
);

CREATE INDEX idx_tasks_committee_id     ON tasks (committee_id);
CREATE INDEX idx_tasks_status           ON tasks (status);
CREATE INDEX idx_tasks_assignee_user_id ON tasks (assignee_user_id);

CREATE TRIGGER trg_tasks_set_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ============================== مسار المهمة (سجل إعادة التعيين) ==============================
-- ميزة "Task Trail" — راجعي ملاحظة التصميم (2) أعلاه. صف واحد لكل
-- إعادة تعيين فعلية؛ from_user_id يكون NULL لصف الإنشاء الأول (لا يوجد
-- "من" عند الإنشاء، المسؤول الأول يُسجَّل كـto_user_id فقط).
CREATE TABLE task_assignment_history (
    history_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id       UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    from_user_id  UUID REFERENCES users(user_id),          -- NULL = التعيين الأول عند الإنشاء
    to_user_id    UUID NOT NULL REFERENCES users(user_id),
    changed_by    UUID NOT NULL REFERENCES users(user_id), -- من نفّذ التغيير (رئيس اللجنة)
    changed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_task_assignment_history_task_id ON task_assignment_history (task_id);

-- ============================== Row Level Security ==============================
ALTER TABLE tasks                    ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_assignment_history  ENABLE ROW LEVEL SECURITY;
