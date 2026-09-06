-- =====================================================================
-- 0023_meetings_scheduled_end_at.sql
-- الهدف: إضافة وقت نهاية مخطَّط (scheduled_end_at) للاجتماع — منفصل تمامًا
-- عن ended_at (Phase Agora، migration 0022) الذي يسجّل وقت آخر مغادرة
-- فعلية من غرفة الفيديو. هذا هنا هو الوقت المخطَّط له مسبقًا عند الجدولة،
-- بطلب صريح من صاحبة المشروع 2026-09-05 لدعم:
--   1) حساب حالة الاجتماع (upcoming/ongoing/finished) ديناميكيًا من
--      الوقت الفعلي مقارنة بـ(scheduled_at, scheduled_end_at) — راجعي
--      app/services/meeting_service.py::_maybe_transition_status.
--   2) منع الانضمام لغرفة الفيديو (POST /meetings/{id}/join) بعد تجاوز
--      وقت النهاية المخطَّط ("الإغلاق التلقائي").
--
-- قرار تصميم: العمود Nullable وليس NOT NULL — الاجتماعات القديمة (قبل
-- هذا الملف) ليس لها وقت نهاية حقيقي معروف، فلا نفبركه (Backfill وهمي).
-- الإلزام (required) مطبَّق فقط على اجتماعات جديدة، على مستوى Pydantic
-- schema (MeetingCreate) — نفس نمط location مع mode='in_person'
-- (migration 0020: عمود Nullable + CHECK شرطي + إلزام إضافي بطبقة أعلى).
--
-- ملاحظة مزامنة: طُبِّق هذا الملف مباشرة على قاعدة Supabase الحقيقية أولًا
-- عبر Supabase MCP، ثم نُسخ إلى هذا المستودع (نفس نمط 0018/0020/0022 —
-- راجعي رأس 0020 لسبب هذا النمط).
-- =====================================================================

ALTER TABLE meetings
    ADD COLUMN IF NOT EXISTS scheduled_end_at TIMESTAMPTZ;

ALTER TABLE meetings
    ADD CONSTRAINT meetings_scheduled_end_at_after_start_chk
    CHECK (scheduled_end_at IS NULL OR scheduled_end_at > scheduled_at);

COMMENT ON COLUMN meetings.scheduled_end_at IS
    'وقت نهاية الاجتماع المخطَّط له عند الجدولة (وليس وقت آخر مغادرة فعلية — ذاك ended_at). NULL للاجتماعات القديمة قبل هذا الحقل.';
