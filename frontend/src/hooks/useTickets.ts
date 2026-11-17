import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import * as ticketsApi from '@/api/tickets'
import type {
  MyTicketsFilters,
  SupportTicketsFilters,
  Ticket,
  TicketCreateInput,
  TicketFieldsUpdate,
  TicketMessage,
  TicketMessagePostResult,
  TicketPage,
  TicketSupportSettableStatus,
} from '@/types/tickets'

/**
 * مفاتيح كاش التذاكر. كل شيء تحت ['tickets'] فإبطال واحد يشمل الكل عند الحاجة.
 * تفاصيل التذكرة ومحادثتها وسجلها تحت ['tickets', 'detail', id] عشان تنبطل معًا.
 */
export const ticketsKeys = {
  all: ['tickets'] as const,
  mineAll: ['tickets', 'mine'] as const,
  mine: (filters: MyTicketsFilters) => ['tickets', 'mine', filters] as const,
  supportAll: ['tickets', 'support'] as const,
  support: (filters: SupportTicketsFilters) => ['tickets', 'support', filters] as const,
  supportMembers: ['tickets', 'support-members'] as const,
  detail: (ticketId: string) => ['tickets', 'detail', ticketId] as const,
  messages: (ticketId: string) => ['tickets', 'detail', ticketId, 'messages'] as const,
  history: (ticketId: string) => ['tickets', 'detail', ticketId, 'history'] as const,
}

/** "تذاكري" (TKT-FR-002) — تبقى الصفحة السابقة ظاهرة أثناء تحميل التالية. */
export function useMyTickets(filters: MyTicketsFilters) {
  return useQuery({
    queryKey: ticketsKeys.mine(filters),
    queryFn: () => ticketsApi.fetchMyTickets(filters),
    placeholderData: keepPreviousData,
  })
}

/** قائمة الدعم (TKT-FR-010). */
export function useSupportTickets(filters: SupportTicketsFilters, enabled = true) {
  return useQuery({
    queryKey: ticketsKeys.support(filters),
    queryFn: () => ticketsApi.fetchSupportTickets(filters),
    placeholderData: keepPreviousData,
    enabled,
  })
}

/** أعضاء الدعم لنافذة إعادة الإسناد — تُجلب فقط لما تنفتح النافذة. */
export function useTicketSupportMembers(enabled: boolean) {
  return useQuery({
    queryKey: ticketsKeys.supportMembers,
    queryFn: ticketsApi.fetchSupportMembers,
    enabled,
  })
}

/**
 * الهدف: عرض التذكرة فورًا لو كانت ضمن قائمة محمّلة (نفس شكل التفاصيل بالضبط
 * — TicketOut)، ثم تتحدّث بالخلفية حسب staleTime. نفس فكرة lib/listCache.ts
 * لكن القوائم هنا صفحات ({items}) وليست مصفوفات.
 */
function seedTicketFromPages(queryClient: QueryClient, ticketId: string) {
  let found: { ticket: Ticket; updatedAt: number } | undefined
  const lookup = () => {
    found = undefined
    for (const prefix of [ticketsKeys.mineAll, ticketsKeys.supportAll]) {
      for (const [key, page] of queryClient.getQueriesData<TicketPage>({ queryKey: prefix })) {
        const ticket = page?.items.find((t) => t.ticket_id === ticketId)
        if (!ticket) continue
        const updatedAt = queryClient.getQueryState(key)?.dataUpdatedAt ?? 0
        if (!found || updatedAt > found.updatedAt) found = { ticket, updatedAt }
      }
    }
    return found
  }
  return {
    initialData: () => lookup()?.ticket,
    initialDataUpdatedAt: () => found?.updatedAt,
  }
}

/** تفاصيل تذكرة واحدة (الطرفين) — الصفة والأزرار المتاحة من الباك-إند. */
export function useTicket(ticketId: string | undefined) {
  const queryClient = useQueryClient()
  return useQuery({
    queryKey: ticketsKeys.detail(ticketId ?? ''),
    queryFn: () => ticketsApi.fetchTicket(ticketId as string),
    enabled: !!ticketId,
    ...seedTicketFromPages(queryClient, ticketId ?? ''),
  })
}

/** المحادثة. staleTime صفر: التحديث اللحظي يعتمد على إعادة الجلب عند الإبطال. */
export function useTicketMessages(ticketId: string | undefined) {
  return useQuery({
    queryKey: ticketsKeys.messages(ticketId ?? ''),
    queryFn: () => ticketsApi.fetchTicketMessages(ticketId as string),
    enabled: !!ticketId,
    staleTime: 0,
  })
}

/** سجل التذكرة — للدعم فقط (enabled بعد معرفة الصفة). */
export function useTicketHistory(ticketId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ticketsKeys.history(ticketId ?? ''),
    queryFn: () => ticketsApi.fetchTicketHistory(ticketId as string),
    enabled: !!ticketId && enabled,
  })
}

/**
 * الهدف: كتابة تذكرة محدّثة بكل الأماكن بعد نجاح عملية عليها.
 * التأثيرات: يضع التفاصيل بالكاش مباشرة (بدون طلب إضافي)، ويبطل القوائم
 * (الترتيب والتبويب قد يتغيّران)، والسجل.
 */
export function storeTicket(queryClient: QueryClient, ticket: Ticket) {
  queryClient.setQueryData(ticketsKeys.detail(ticket.ticket_id), ticket)
  queryClient.invalidateQueries({ queryKey: ticketsKeys.mineAll })
  queryClient.invalidateQueries({ queryKey: ticketsKeys.supportAll })
  queryClient.invalidateQueries({ queryKey: ticketsKeys.history(ticket.ticket_id) })
}

/**
 * الهدف: إضافة رسالة أُرسلت بنجاح للمحادثة بالكاش بدون انتظار إعادة الجلب.
 * قاعدة: بدون تكرار — لو وصلت نفس الرسالة من إعادة جلب (بعد تنبيه لحظي) قبل
 * رد الإرسال، ما تنضاف مرة ثانية.
 */
export function storePostedMessage(queryClient: QueryClient, result: TicketMessagePostResult) {
  const { message, ticket } = result
  queryClient.setQueryData<TicketMessage[]>(ticketsKeys.messages(ticket.ticket_id), (current) => {
    if (!current) return current
    if (current.some((m) => m.message_id === message.message_id)) return current
    return [...current, message]
  })
  storeTicket(queryClient, ticket)
}

/** إنشاء تذكرة: التذكرة ووصفها يُكتبان بالكاش فتنفتح صفحتها فورًا. */
export function useCreateTicket() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: TicketCreateInput) => ticketsApi.createTicket(input),
    onSuccess: (result) => {
      queryClient.setQueryData(ticketsKeys.messages(result.ticket.ticket_id), [result.message])
      storeTicket(queryClient, result.ticket)
    },
  })
}

/** يبني Hook لعملية ترجع التذكرة المحدّثة (إلغاء، استلام، إسناد، حالة، حقول). */
function useTicketMutation<TVars>(fn: (vars: TVars) => Promise<Ticket>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (ticket) => storeTicket(queryClient, ticket),
  })
}

export function useCancelTicket() {
  return useTicketMutation((ticketId: string) => ticketsApi.cancelTicket(ticketId))
}

export function useClaimTicket() {
  return useTicketMutation((ticketId: string) => ticketsApi.claimTicket(ticketId))
}

export function useAssignTicket() {
  return useTicketMutation(({ ticketId, assigneeId }: { ticketId: string; assigneeId: string }) =>
    ticketsApi.assignTicket(ticketId, assigneeId),
  )
}

export function useChangeTicketStatus() {
  return useTicketMutation(({ ticketId, status }: { ticketId: string; status: TicketSupportSettableStatus }) =>
    ticketsApi.changeTicketStatus(ticketId, status),
  )
}

export function useUpdateTicketFields() {
  return useTicketMutation(({ ticketId, payload }: { ticketId: string; payload: TicketFieldsUpdate }) =>
    ticketsApi.updateTicketFields(ticketId, payload),
  )
}
