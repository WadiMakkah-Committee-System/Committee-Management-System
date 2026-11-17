import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { io } from 'socket.io-client'
import { API_BASE_URL } from '@/lib/apiClient'
import { useAuthStore } from '@/store/authStore'
import { ticketsKeys } from '@/hooks/useTickets'
import type { TicketMessage } from '@/types/tickets'

/** socket.io يتصل بجذر الخادم لا بمسار REST — نفس اشتقاق useMeetingRealtime.ts. */
const SOCKET_ORIGIN = API_BASE_URL.replace(/\/api\/v1\/?$/, '')

/** namespace التذاكر بالباك-إند (app/core/ticket_realtime.py) — منفصل عن الاجتماعات. */
const TICKETS_NAMESPACE = '/tickets'

export type TicketConnectionStatus = 'connecting' | 'open' | 'closed'

/**
 * الهدف:
 * استقبال التحديثات اللحظية لتذكرة مفتوحة (TKT-FR-024) — للاستقبال فقط؛
 * الإرسال REST (القسم 7 بالمواصفات).
 *
 * المسؤولية:
 * - اتصال مستقل بـnamespace "/tickets" (forceNew: ما يشارك اتصال الاجتماع).
 * - الاشتراك بالتذكرة بعد كل اتصال (ticket.subscribe) — الباك-إند يفحص
 *   الصلاحية نفسها بالـREST، والدعم ينضم لقناة الملاحظات الداخلية.
 * - "ticket.message": يعيد جلب المحادثة (لو الرسالة مو موجودة بالكاش أصلًا).
 * - "ticket.updated": يعيد جلب التذكرة وسجلها.
 * - بعد انقطاع ورجوع: يعيد جلب الكل، فما يضيع شيء انبث أثناء الانقطاع.
 *
 * قرار التصميم: البث يحمل المعرّفات فقط، والبيانات تُجلب من الـREST اللي
 * يطبّق الصلاحيات — فما يتسرّب شيء عبر القناة اللحظية.
 *
 * المدخلات: ticketId — التذكرة المفتوحة (undefined = بدون اتصال).
 * المخرجات: حالة الاتصال لعرض مؤشر "غير متصل" عند الانقطاع.
 * التأثيرات الجانبية: اتصال Socket.IO يُغلق عند مغادرة الصفحة.
 */
export function useTicketRealtime(ticketId: string | undefined): TicketConnectionStatus {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<TicketConnectionStatus>('connecting')

  useEffect(() => {
    if (!ticketId) return
    let connectedBefore = false
    const socket = io(`${SOCKET_ORIGIN}${TICKETS_NAMESPACE}`, {
      path: '/socket.io',
      forceNew: true,
      // دالة (وليس قيمة ثابتة): كل إعادة اتصال تاخذ أحدث توكن بعد تجديده.
      auth: (cb) => cb({ token: useAuthStore.getState().accessToken }),
    })

    const refreshAll = () => {
      queryClient.invalidateQueries({ queryKey: ticketsKeys.detail(ticketId) })
    }

    socket.on('connect', () => {
      setStatus('open')
      socket.emit('ticket.subscribe', { ticket_id: ticketId })
      // أول اتصال: البيانات للتو انجلبت بالـREST. بعد انقطاع: نلحق اللي فاتنا.
      if (connectedBefore) refreshAll()
      connectedBefore = true
    })
    socket.on('disconnect', () => setStatus('closed'))
    socket.on('connect_error', () => setStatus('closed'))

    socket.on('ticket.message', (payload: { ticket_id: string; message_id: string }) => {
      if (payload.ticket_id !== ticketId) return
      const cached = queryClient.getQueryData<TicketMessage[]>(ticketsKeys.messages(ticketId))
      // رسالتي اللي أرسلتها للتو تكون بالكاش من رد الإرسال — ما نعيد الجلب لها.
      if (cached?.some((m) => m.message_id === payload.message_id)) return
      queryClient.invalidateQueries({ queryKey: ticketsKeys.messages(ticketId) })
      // رد جديد يغيّر "آخر تحديث" وقد يغيّر الحالة (إعادة فتح مثلًا).
      queryClient.invalidateQueries({ queryKey: ticketsKeys.detail(ticketId), exact: true })
    })

    socket.on('ticket.updated', (payload: { ticket_id: string }) => {
      if (payload.ticket_id !== ticketId) return
      queryClient.invalidateQueries({ queryKey: ticketsKeys.detail(ticketId), exact: true })
      queryClient.invalidateQueries({ queryKey: ticketsKeys.history(ticketId) })
      // القوائم غير مفتوحة الآن — تُعلَّم قديمة فتنجلب عند الرجوع لها.
      queryClient.invalidateQueries({ queryKey: ticketsKeys.mineAll })
      queryClient.invalidateQueries({ queryKey: ticketsKeys.supportAll })
    })

    return () => {
      socket.disconnect()
    }
  }, [ticketId, queryClient])

  return status
}
