import type {
  TicketHistoryEntry,
  TicketModule,
  TicketPriority,
  TicketStatus,
  TicketSupportSettableStatus,
  TicketType,
  TicketViewer,
} from '@/types/tickets'

/**
 * الهدف:
 * كل نصوص وحدة التذاكر المعروضة للمستخدم في مكان واحد — المواصفات (القسم 5)
 * تشترط أن تكون النصوص والقوائم قابلة للترجمة، فأي ترجمة إنجليزية لاحقًا تبدّل
 * هذا الملف بدل البحث في كل المكوّنات.
 *
 * المسؤولية: تسميات الحالات (بنسختين: للدعم ولمقدّم الطلب — القسم 4)،
 * والأنواع والوحدات والأولويات، ولون كل حالة، ونص أحداث سجل التذكرة.
 * بدون أي منطق صلاحيات (الصلاحيات من الباك-إند عبر ticket.actions).
 */

export type TicketTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

/** اسم الحالة كما يراها الدعم (العمود الأول بجدول القسم 4). */
const SUPPORT_STATUS_LABELS: Record<TicketStatus, string> = {
  new: 'جديدة',
  in_progress: 'قيد المعالجة',
  waiting_on_requester: 'بانتظار رد المستخدم',
  resolved: 'تم الحل',
  closed: 'مغلقة',
  cancelled: 'ملغاة',
}

/** اسم الحالة كما يراها مقدّم الطلب (العمود الأخير بجدول القسم 4). */
const REQUESTER_STATUS_LABELS: Record<TicketStatus, string> = {
  new: 'تم الإرسال',
  in_progress: 'قيد المعالجة',
  waiting_on_requester: 'بانتظار ردك',
  resolved: 'تم الحل',
  closed: 'مغلقة',
  cancelled: 'ملغاة',
}

/**
 * لون الحالة حسب "الدور على مين" (القسم 4): التحذيري يعني الدور على المشاهد
 * نفسه — "جديدة" للدعم و"بانتظار ردك" لمقدّم الطلب — فيلفت انتباهه للي ينتظره.
 */
const STATUS_TONES: Record<TicketViewer, Record<TicketStatus, TicketTone>> = {
  support: {
    new: 'warning',
    in_progress: 'info',
    waiting_on_requester: 'neutral',
    resolved: 'success',
    closed: 'neutral',
    cancelled: 'neutral',
  },
  requester: {
    new: 'info',
    in_progress: 'info',
    waiting_on_requester: 'warning',
    resolved: 'success',
    closed: 'neutral',
    cancelled: 'neutral',
  },
}

/** الهدف: اسم الحالة المناسب للمشاهد. المدخلات: الحالة وصفة المشاهد. */
export function ticketStatusLabel(status: TicketStatus, viewer: TicketViewer): string {
  return (viewer === 'support' ? SUPPORT_STATUS_LABELS : REQUESTER_STATUS_LABELS)[status]
}

/** الهدف: لون شارة الحالة للمشاهد. */
export function ticketStatusTone(status: TicketStatus, viewer: TicketViewer): TicketTone {
  return STATUS_TONES[viewer][status]
}

/** الحالات المفتوحة (ما وصلت لنهاية) — للفلترة والعرض. */
export const OPEN_TICKET_STATUSES: TicketStatus[] = ['new', 'in_progress', 'waiting_on_requester', 'resolved']

/** هل التذكرة نهائية (للقراءة فقط)؟ */
export function isFinalTicketStatus(status: TicketStatus): boolean {
  return status === 'closed' || status === 'cancelled'
}

export const TICKET_TYPE_LABELS: Record<TicketType, string> = {
  change_request: 'طلب تعديل أو ميزة',
  bug: 'بلاغ خلل',
  inquiry: 'استفسار',
  account_access: 'مشكلة حساب أو صلاحية',
}

export const TICKET_MODULE_LABELS: Record<TicketModule, string> = {
  users_departments: 'الإدارات والمستخدمين',
  committees: 'اللجان',
  meetings: 'الاجتماعات',
  tasks: 'المهام',
  decisions: 'القرارات',
  documents: 'الوثائق',
  minutes: 'المحاضر',
  dashboard: 'لوحة التحكم',
  other: 'أخرى',
}

export const TICKET_PRIORITY_LABELS: Record<TicketPriority, string> = {
  low: 'منخفضة',
  medium: 'متوسطة',
  high: 'عالية',
  urgent: 'عاجلة',
}

export const TICKET_PRIORITY_TONES: Record<TicketPriority, TicketTone> = {
  low: 'neutral',
  medium: 'info',
  high: 'warning',
  urgent: 'danger',
}

/** خيارات قوائم الاختيار (بنفس ترتيب المواصفات). */
export const TICKET_TYPE_OPTIONS = (Object.keys(TICKET_TYPE_LABELS) as TicketType[]).map((value) => ({
  value,
  label: TICKET_TYPE_LABELS[value],
}))

export const TICKET_MODULE_OPTIONS = (Object.keys(TICKET_MODULE_LABELS) as TicketModule[]).map((value) => ({
  value,
  label: TICKET_MODULE_LABELS[value],
}))

export const TICKET_PRIORITY_OPTIONS = (Object.keys(TICKET_PRIORITY_LABELS) as TicketPriority[]).map((value) => ({
  value,
  label: TICKET_PRIORITY_LABELS[value],
}))

/** الحالة بعد رد الدعم العام (القسم 7): الافتراضي "بانتظار رد المستخدم". */
export const STATUS_AFTER_REPLY_OPTIONS: { value: TicketSupportSettableStatus; label: string }[] = [
  { value: 'waiting_on_requester', label: 'بانتظار رد المستخدم' },
  { value: 'in_progress', label: 'قيد المعالجة' },
  { value: 'resolved', label: 'تم الحل' },
]

/**
 * الانتقالات اليدوية المسموحة للدعم من كل حالة (القسم 4، ونفس _MANUAL_TRANSITIONS
 * بالباك-إند): قيد المعالجة ⇄ بانتظار رد المستخدم، و(جديدة/قيد المعالجة/بانتظار) ← تم الحل.
 * للعرض فقط — الباك-إند وقاعدة البيانات يرفضان غيرها.
 */
export const MANUAL_STATUS_TRANSITIONS: Record<TicketStatus, TicketSupportSettableStatus[]> = {
  new: ['resolved'],
  in_progress: ['waiting_on_requester', 'resolved'],
  waiting_on_requester: ['in_progress', 'resolved'],
  resolved: [],
  closed: [],
  cancelled: [],
}

/** اسم إجراء تغيير الحالة بقائمة الدعم. */
export const STATUS_ACTION_LABELS: Record<TicketSupportSettableStatus, string> = {
  in_progress: 'إرجاعها لقيد المعالجة',
  waiting_on_requester: 'بانتظار رد المستخدم',
  resolved: 'تم الحل',
}

/** يحوّل قيمة مخزنة بالسجل (حالة/أولوية/نوع/وحدة) إلى اسمها المعروض. */
function historyValueLabel(event: string, value: string | null): string {
  if (!value) return '—'
  switch (event) {
    case 'status_changed':
      return SUPPORT_STATUS_LABELS[value as TicketStatus] ?? value
    case 'priority_changed':
      return TICKET_PRIORITY_LABELS[value as TicketPriority] ?? value
    case 'type_changed':
      return TICKET_TYPE_LABELS[value as TicketType] ?? value
    case 'module_changed':
      return TICKET_MODULE_LABELS[value as TicketModule] ?? value
    default:
      return value
  }
}

/**
 * الهدف: جملة مقروءة لحدث بسجل التذكرة (TKT-FR-017).
 * المدخلات: الحدث كما يرجعه GET /tickets/{id}/history.
 * المخرجات: نص مثل "غيّر الحالة من «جديدة» إلى «تم الحل»".
 * الإسناد يحمل الأسماء نفسها (from/to) لأن الباك-إند يحفظها وقت الحدث.
 */
export function ticketHistoryText(entry: Pick<TicketHistoryEntry, 'event' | 'from_value' | 'to_value'>): string {
  const from = historyValueLabel(entry.event, entry.from_value)
  const to = historyValueLabel(entry.event, entry.to_value)
  switch (entry.event) {
    case 'created':
      return 'أنشأ التذكرة'
    case 'status_changed':
      return `غيّر الحالة من «${from}» إلى «${to}»`
    case 'assigned':
      return entry.from_value ? `أعاد الإسناد من ${from} إلى ${to}` : `أسند التذكرة إلى ${to}`
    case 'priority_changed':
      return `غيّر الأولوية من «${from}» إلى «${to}»`
    case 'type_changed':
      return `غيّر النوع من «${from}» إلى «${to}»`
    case 'module_changed':
      return `غيّر الوحدة من «${from}» إلى «${to}»`
    default:
      return entry.event
  }
}
