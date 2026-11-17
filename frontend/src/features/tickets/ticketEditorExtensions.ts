import StarterKit from '@tiptap/starter-kit'

/**
 * امتدادات TipTap لرسائل التذاكر — نفس القائمة للكتابة والعرض، فالمعروض
 * يطابق المكتوب حرفيًا.
 *
 * المسموح: فقرات، سطر جديد، قوائم مرقمة ونقطية، عريض/مائل/تسطير — ضمن القائمة
 * البيضاء بالخادم (minutes_general/editor_content.py). الباقي (روابط، كود،
 * اقتباس، عناوين...) معطّل، فاللصق من مكان ثاني يُسقطه تلقائيًا بدل ما يرفضه الخادم.
 */
export const TICKET_EDITOR_EXTENSIONS = [
  StarterKit.configure({
    blockquote: false,
    codeBlock: false,
    code: false,
    heading: false,
    horizontalRule: false,
    link: false,
    strike: false,
  }),
]
