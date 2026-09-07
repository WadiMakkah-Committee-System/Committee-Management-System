-- الهدف: إضافة ثلاثة أقسام جديدة لمسودة اجتماع الذكاء الاصطناعي
-- (meeting_drafts، migration 0025) عشان تصير أقرب لمحضر اجتماع رسمي
-- للجنة حوكمة والتزام — راجعي app/core/gemini_client.py (البرومت +
-- _RESPONSE_SCHEMA) وapp/schemas/meeting_draft.py للشكل الدقيق:
--
-- recommendations   : توصيات مرفوعة لجهة أعلى (تختلف عن decisions —
--                     القرار بتّ فعلي بنفس الاجتماع، التوصية اقتراح
--                     للاعتماد لاحقًا). [{text, proposed_by}]
-- open_items        : نقاط معلّقة/أسئلة مفتوحة لم تُحسم بالاجتماع.
--                     [{text, raised_by}]
-- compliance_notes  : ملاحظات/مخاطر التزام أو حوكمة أُثيرت بالنقاش.
--                     [{text, severity}] — severity: مرتفع/متوسط/منخفض/null
--
-- كل الأعمدة JSONB nullable (نفس نمط full_transcript/decisions/
-- action_items/key_points بـ0025 — بدون قيمة افتراضية، تُملأ فقط عند
-- توليد مسودة جديدة بعد هذا التعديل؛ المسودات القديمة تبقى null لهذي
-- الحقول الثلاثة إلى أن يُعاد توليدها).

ALTER TABLE public.meeting_drafts
  ADD COLUMN IF NOT EXISTS recommendations JSONB,
  ADD COLUMN IF NOT EXISTS open_items JSONB,
  ADD COLUMN IF NOT EXISTS compliance_notes JSONB;
