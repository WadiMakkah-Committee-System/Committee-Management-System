import { apiClient } from '@/lib/apiClient'
import { fileNameFromDisposition } from '@/lib/utils'
import type {
  MyTicketsFilters,
  SupportTicketsFilters,
  Ticket,
  TicketCreateInput,
  TicketFieldsUpdate,
  TicketHistoryEntry,
  TicketMessage,
  TicketMessageInput,
  TicketMessagePostResult,
  TicketPage,
  TicketSupportMember,
  TicketSupportSettableStatus,
} from '@/types/tickets'

/**
 * وحدة "التذاكر" — تقابل app/api/v1/tickets.py بالباك-إند (القسم 15 بالمواصفات).
 *
 * الصلاحيات كلها تُفحص بالباك-إند: تذكرة مستخدم آخر ترجع 404، ومقدّم طلب
 * بدون "إرسال التذاكر ومتابعتها" يرجع 403، وخانات الدعم تشتغل بنطاق "الكل"
 * فقط. هذا الملف طبقة نقل فقط بدون أي منطق صلاحيات.
 *
 * الإنشاء والرد multipart/form-data (المرفقات) — apiClient يحذف Content-Type
 * الثابت مع FormData فيضبطه المتصفح مع الـboundary الصحيح.
 */

/**
 * الهدف: بناء معاملات استعلام فيها قيم مكررة (status=new&status=in_progress)
 * — الشكل اللي يقرأه FastAPI لـlist[...]، بدل status[]=... الافتراضي بـaxios.
 *
 * المدخلات: كائن قيمه نص أو رقم أو مصفوفة نصوص أو undefined (تُتجاهل).
 * المخرجات: URLSearchParams جاهزة لـaxios.
 */
function toSearchParams(values: Record<string, string | number | string[] | undefined>): URLSearchParams {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === '') continue
    if (Array.isArray(value)) value.forEach((v) => params.append(key, v))
    else params.append(key, String(value))
  }
  return params
}

/**
 * الهدف: تحويل مدخلات رسالة إلى FormData بنفس أسماء حقول الراوت.
 * body يُرسل نص JSON (مستند TipTap) — والفارغ نص فاضي (رد بمرفق فقط).
 */
function messageFormData(input: TicketMessageInput): FormData {
  const form = new FormData()
  form.append('body', input.body ? JSON.stringify(input.body) : '')
  form.append('is_internal', input.is_internal ? 'true' : 'false')
  if (input.status_after) form.append('status_after', input.status_after)
  form.append('client_message_id', input.client_message_id)
  input.files.forEach((file) => form.append('files', file))
  return form
}

/** إرسال تذكرة جديدة (tickets.create). الوصف أول رسالة، ويرجع مع التذكرة. */
export async function createTicket(input: TicketCreateInput): Promise<TicketMessagePostResult> {
  const form = new FormData()
  form.append('title', input.title)
  form.append('ticket_type', input.ticket_type)
  form.append('module', input.module)
  form.append('body', JSON.stringify(input.body))
  form.append('client_message_id', input.client_message_id)
  input.files.forEach((file) => form.append('files', file))
  const { data } = await apiClient.post<TicketMessagePostResult>('/tickets', form)
  return data
}

/** تذاكر المستخدم نفسه فقط (مرتبة بآخر نشاط عام). */
export async function fetchMyTickets(filters: MyTicketsFilters): Promise<TicketPage> {
  const params = toSearchParams({ status: filters.statuses, limit: filters.limit, offset: filters.offset })
  const { data } = await apiClient.get<TicketPage>('/tickets/mine', { params })
  return data
}

/** قائمة الدعم بتبويباتها وفلاترها (tickets.view_all بنطاق الكل). */
export async function fetchSupportTickets(filters: SupportTicketsFilters): Promise<TicketPage> {
  const params = toSearchParams({
    tab: filters.tab,
    status: filters.statuses,
    ticket_type: filters.ticket_type,
    module: filters.module,
    priority: filters.priority,
    q: filters.q?.trim() || undefined,
    limit: filters.limit,
    offset: filters.offset,
  })
  const { data } = await apiClient.get<TicketPage>('/tickets', { params })
  return data
}

/** أعضاء الدعم اللي يقدر يُسند لهم (tickets.assign). */
export async function fetchSupportMembers(): Promise<TicketSupportMember[]> {
  const { data } = await apiClient.get<TicketSupportMember[]>('/tickets/support-members')
  return data
}

export async function fetchTicket(ticketId: string): Promise<Ticket> {
  const { data } = await apiClient.get<Ticket>(`/tickets/${ticketId}`)
  return data
}

/** المحادثة بالترتيب الزمني — بدون الملاحظات الداخلية لمن لا يملكها (فلترة بالباك-إند). */
export async function fetchTicketMessages(ticketId: string): Promise<TicketMessage[]> {
  const { data } = await apiClient.get<TicketMessage[]>(`/tickets/${ticketId}/messages`)
  return data
}

/**
 * رد أو ملاحظة داخلية. إعادة الإرسال بنفس client_message_id ترجع نفس
 * الرسالة بدل تكرارها (الباك-إند idempotent) — أساس "إعادة المحاولة".
 */
export async function postTicketMessage(ticketId: string, input: TicketMessageInput): Promise<TicketMessagePostResult> {
  const { data } = await apiClient.post<TicketMessagePostResult>(`/tickets/${ticketId}/messages`, messageFormData(input))
  return data
}

/** إلغاء التذكرة (صاحبها، وهي "جديدة" فقط). */
export async function cancelTicket(ticketId: string): Promise<Ticket> {
  const { data } = await apiClient.post<Ticket>(`/tickets/${ticketId}/cancel`)
  return data
}

/** استلام (إسناد لنفسي). 409 لو استلمها عضو آخر قبله. */
export async function claimTicket(ticketId: string): Promise<Ticket> {
  const { data } = await apiClient.post<Ticket>(`/tickets/${ticketId}/claim`)
  return data
}

export async function assignTicket(ticketId: string, assigneeId: string): Promise<Ticket> {
  const { data } = await apiClient.post<Ticket>(`/tickets/${ticketId}/assign`, { assignee_id: assigneeId })
  return data
}

export async function changeTicketStatus(ticketId: string, status: TicketSupportSettableStatus): Promise<Ticket> {
  const { data } = await apiClient.post<Ticket>(`/tickets/${ticketId}/status`, { status })
  return data
}

export async function updateTicketFields(ticketId: string, payload: TicketFieldsUpdate): Promise<Ticket> {
  const { data } = await apiClient.patch<Ticket>(`/tickets/${ticketId}`, payload)
  return data
}

/** سجل التذكرة (للدعم فقط). */
export async function fetchTicketHistory(ticketId: string): Promise<TicketHistoryEntry[]> {
  const { data } = await apiClient.get<TicketHistoryEntry[]>(`/tickets/${ticketId}/history`)
  return data
}

/**
 * الهدف: تنزيل مرفق عبر المسار المحمي (يتحقق الباك-إند من صلاحية المشاهد على
 * التذكرة والرسالة) — ما فيه رابط عام للملفات.
 * المخرجات: الملف واسمه من Content-Disposition (filename* للاسم العربي).
 */
export async function fetchTicketAttachmentBlob(
  ticketId: string,
  attachmentId: string,
): Promise<{ blob: Blob; fileName: string }> {
  const response = await apiClient.get(`/tickets/${ticketId}/attachments/${attachmentId}/download`, {
    responseType: 'blob',
  })
  const disposition = String(response.headers['content-disposition'] ?? '')
  return { blob: response.data as Blob, fileName: fileNameFromDisposition(disposition, 'attachment') }
}
