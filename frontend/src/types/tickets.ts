/**
 * أنواع وحدة "التذاكر" (الدعم الفني) — تطابق app/schemas/ticket.py بالباك-إند
 * حرفيًا. راجعي مواصفات claude/tickets_spec.md (الأقسام 4 و5 و7 و15).
 *
 * ملاحظة: الحقول الخاصة بالدعم (priority وبريد مقدّم الطلب وحالة عضو الدعم
 * المسند) ترجع null لمقدّم الطلب — الباك-إند يبني الاستجابة حسب صفة المشاهد
 * (viewer)، فالواجهة ما تخفي بيانات بنفسها.
 */

/** حالات التذكرة (القسم 4). مقدّم الطلب يشوف بعضها باسم مختلف — راجعي ticketLabels.ts. */
export type TicketStatus = 'new' | 'in_progress' | 'waiting_on_requester' | 'resolved' | 'closed' | 'cancelled'

/** الحالات اللي يحددها الدعم يدويًا أو مع الرد (SupportSettableStatus بالباك-إند). */
export type TicketSupportSettableStatus = 'in_progress' | 'waiting_on_requester' | 'resolved'

export type TicketType = 'change_request' | 'bug' | 'inquiry' | 'account_access'

export type TicketModule =
  | 'users_departments'
  | 'committees'
  | 'meetings'
  | 'tasks'
  | 'decisions'
  | 'documents'
  | 'minutes'
  | 'dashboard'
  | 'other'

export type TicketPriority = 'low' | 'medium' | 'high' | 'urgent'

/** صفة المشاهد اللي بُنيت عليها الاستجابة. */
export type TicketViewer = 'requester' | 'support'

/** مستند TipTap (ProseMirror JSON) — المحتوى الوحيد المسموح للرسائل (بدون HTML خام). */
export interface TicketDoc {
  type: string
  attrs?: Record<string, unknown>
  content?: TicketDoc[]
  marks?: { type: string; attrs?: Record<string, unknown> }[]
  text?: string
}

/** اسم مستخدم مختصر داخل التذكرة. email للدعم فقط (null لمقدّم الطلب). */
export interface TicketPerson {
  user_id: string
  first_name: string
  last_name: string
  email: string | null
}

/**
 * وش يقدر المشاهد الحالي يسوي الآن — يحسبها الباك-إند من الصلاحيات والحالة.
 * الواجهة تعرض الأزرار حسبها فقط؛ الأمان نفسه يبقى بالباك-إند لكل عملية.
 */
export interface TicketViewerActions {
  can_reply: boolean
  can_add_internal_note: boolean
  can_cancel: boolean
  can_manage: boolean
  can_assign: boolean
}

export interface Ticket {
  ticket_id: string
  ticket_number: string
  title: string
  ticket_type: TicketType
  module: TicketModule
  status: TicketStatus
  /** null لمقدّم الطلب. */
  priority: TicketPriority | null
  requester: TicketPerson
  assignee: TicketPerson | null
  /** للدعم فقط: هل المسند إليه ما زال عضو دعم نشط؟ (null لمقدّم الطلب) */
  assignee_is_active_support: boolean | null
  created_at: string
  /** لمقدّم الطلب = last_public_activity_at (ما ينكشف له نشاط داخلي). */
  updated_at: string
  last_public_activity_at: string
  resolved_at: string | null
  closed_at: string | null
  cancelled_at: string | null
  viewer: TicketViewer
  actions: TicketViewerActions
}

export interface TicketPage {
  items: Ticket[]
  total: number
  limit: number
  offset: number
}

export interface TicketAttachment {
  attachment_id: string
  file_name: string
  mime_type: string
  file_size_bytes: number
}

export interface TicketMessage {
  message_id: string
  ticket_id: string
  author: TicketPerson
  author_side: 'requester' | 'support'
  is_internal: boolean
  is_description: boolean
  body_json: TicketDoc
  client_message_id: string | null
  created_at: string
  attachments: TicketAttachment[]
}

/** نتيجة إرسال رسالة أو إنشاء تذكرة: الرسالة + التذكرة بعد أي تغيير حالة. */
export interface TicketMessagePostResult {
  message: TicketMessage
  ticket: Ticket
}

/** أحداث سجل التذكرة (TKT-FR-017) — مقروءة من audit_logs بالباك-إند. */
export type TicketHistoryEvent =
  | 'created'
  | 'status_changed'
  | 'assigned'
  | 'priority_changed'
  | 'type_changed'
  | 'module_changed'

export interface TicketHistoryEntry {
  event: TicketHistoryEvent | string
  from_value: string | null
  to_value: string | null
  /** null للعمليات التلقائية (الإغلاق بالمجدول). */
  actor: TicketPerson | null
  created_at: string
}

/** عضو دعم يقدر يُسند له (يملك "عرض جميع التذاكر" بنطاق الكل). */
export interface TicketSupportMember {
  user_id: string
  first_name: string
  last_name: string
  email: string
}

/** تبويبات قائمة الدعم (TKT-FR-010). */
export type SupportTicketsTab = 'unassigned' | 'mine' | 'all'

/** فلاتر قائمة الدعم — كلها اختيارية. */
export interface SupportTicketsFilters {
  tab: SupportTicketsTab
  statuses?: TicketStatus[]
  ticket_type?: TicketType
  module?: TicketModule
  priority?: TicketPriority
  q?: string
  limit: number
  offset: number
}

/** فلاتر "تذاكري" (TKT-FR-002). */
export interface MyTicketsFilters {
  statuses?: TicketStatus[]
  limit: number
  offset: number
}

/** مدخلات إنشاء تذكرة — تُرسل multipart (بسبب المرفقات). */
export interface TicketCreateInput {
  title: string
  ticket_type: TicketType
  module: TicketModule
  body: TicketDoc
  client_message_id: string
  files: File[]
}

/** مدخلات رسالة (رد عام أو ملاحظة داخلية). */
export interface TicketMessageInput {
  body: TicketDoc | null
  is_internal: boolean
  /** لرد الدعم العام فقط — الحالة بعد الإرسال (بدونها: الافتراضي بالباك-إند). */
  status_after: TicketSupportSettableStatus | null
  client_message_id: string
  files: File[]
}

/** تعديل حقول الدعم (tickets.manage). العنوان ما يتعدّل (قرار 2026-11-17). */
export interface TicketFieldsUpdate {
  priority?: TicketPriority
  ticket_type?: TicketType
  module?: TicketModule
}
