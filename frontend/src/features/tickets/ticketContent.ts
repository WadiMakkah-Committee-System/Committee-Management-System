import type { TicketDoc } from '@/types/tickets'

/**
 * الهدف:
 * حدود وقواعد محتوى التذاكر بالواجهة — نسخة مطابقة لـ
 * app/services/ticket_service/content.py بالباك-إند (القسم 5 بالمواصفات،
 * معتمدة 2026-11-17). الفحص هنا لتجربة أسرع فقط؛ الباك-إند وقاعدة البيانات
 * يفحصان نفس الحدود ولا يعتمدان على الواجهة.
 */

export const TITLE_MIN = 5
export const TITLE_MAX = 150
export const DESCRIPTION_MIN = 10
export const BODY_MAX = 5000
export const MAX_FILES_PER_MESSAGE = 5
/**
 * حد حجم الملف — نفس MAX_DOCUMENT_UPLOAD_MB بإعدادات الباك-إند (25). لو تغيّر
 * هناك يرفض الباك-إند برسالة واضحة حتى لو ما تحدّث هنا.
 */
export const MAX_FILE_MB = 25
export const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024

const DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

/** أنواع الملفات المسموحة بصيغة react-dropzone (نوع ← امتدادات). */
export const ACCEPTED_FILE_TYPES: Record<string, string[]> = {
  'image/png': ['.png'],
  'image/jpeg': ['.jpg', '.jpeg'],
  'application/pdf': ['.pdf'],
  [DOCX]: ['.docx'],
  [XLSX]: ['.xlsx'],
}

/** نص يوضح المسموح تحت منطقة الإرفاق. */
export const ACCEPTED_FILES_HINT = `PNG وJPG وPDF وDOCX وXLSX — حتى ${MAX_FILES_PER_MESSAGE} ملفات، و${MAX_FILE_MB} ميجابايت للملف`

/**
 * الهدف: النص المجرّد من مستند TipTap بنفس طريقة plain_text بالباك-إند حرفيًا
 * (كل فقرة/عنصر قائمة بسطر، والفقرات الفاضية تُتجاهل)، عشان عدّاد الأحرف
 * بالواجهة يطابق الحد اللي يطبّقه الخادم.
 *
 * المدخلات: مستند أو null. المخرجات: نص بدون مسافات طرفية.
 */
export function ticketPlainText(doc: TicketDoc | null | undefined): string {
  if (!doc) return ''
  const walk = (node: TicketDoc): string => {
    if (node.type === 'text') return node.text ?? ''
    if (node.type === 'hardBreak') return '\n'
    const parts = (node.content ?? []).map(walk)
    if (node.type === 'tableRow') return parts.join(' | ')
    if (['doc', 'bulletList', 'orderedList', 'listItem', 'table', 'tableCell', 'tableHeader'].includes(node.type)) {
      return parts.filter(Boolean).join('\n')
    }
    return parts.join('')
  }
  return walk(doc).trim()
}

/**
 * الهدف: عدد الأحرف كما يعدّها الباك-إند (Python len = عدد نقاط Unicode).
 * length بالجافاسكربت يعدّ الإيموجي حرفين، فنعدّ بالتكرار على النص.
 */
export function countChars(text: string): number {
  return Array.from(text).length
}

/** هل المستند فاضي فعليًا (بدون أي نص)؟ */
export function isEmptyTicketDoc(doc: TicketDoc | null | undefined): boolean {
  return ticketPlainText(doc).length === 0
}

/**
 * الهدف: معرّف فريد للرسالة من جهة الواجهة (client_message_id) — الباك-إند
 * يرجع نفس الرسالة لو وصله نفس المعرّف مرتين، فإعادة المحاولة ما تكرر الرسالة.
 *
 * crypto.randomUUID متاح فقط بالسياقات الآمنة (HTTPS أو localhost)، فالبديل
 * يبني UUID v4 من crypto.getRandomValues (متاح بكل المتصفحات الحديثة).
 */
export function newClientMessageId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

/** امتداد الملف بأحرف صغيرة (مع النقطة) — لاختيار أيقونته. */
export function fileExtension(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot).toLowerCase() : ''
}
