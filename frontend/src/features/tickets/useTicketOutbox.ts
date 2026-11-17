import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import * as ticketsApi from '@/api/tickets'
import { storePostedMessage } from '@/hooks/useTickets'
import { extractErrorMessage } from '@/lib/utils'
import { newClientMessageId } from './ticketContent'
import type { TicketDoc, TicketMessageInput, TicketSupportSettableStatus } from '@/types/tickets'

/** رسالة بانتظار الحفظ بالخادم أو فشل إرسالها. */
export interface OutboxEntry {
  clientId: string
  doc: TicketDoc | null
  files: File[]
  isInternal: boolean
  statusAfter: TicketSupportSettableStatus | null
  status: 'sending' | 'failed'
  error: string | null
  createdAt: string
}

/** ما يرسله صندوق الكتابة. */
export interface OutgoingMessage {
  doc: TicketDoc | null
  files: File[]
  isInternal: boolean
  statusAfter: TicketSupportSettableStatus | null
}

/**
 * الهدف:
 * الإرسال المتفائل لرسائل التذكرة (TKT-FR-025، القسم 7 بالمواصفات): الرسالة
 * تظهر فورًا بحالة "جاري الإرسال"، وصندوق الكتابة ما ينقفل، وعند الفشل تبقى
 * بعلامة "فشل" مع "إعادة المحاولة".
 *
 * المسؤولية:
 * - قائمة "صندوق الصادر" (entries) للرسائل اللي ما انحفظت بعد.
 * - الإرسال عبر TanStack Query (useMutation) بالـREST.
 * - عند النجاح: الرسالة تنضاف لكاش المحادثة والتذكرة تتحدّث (storePostedMessage)
 *   وتنشال من الصادر — بنفس الدفعة فما يصير تكرار ولا وميض.
 * - إعادة المحاولة ترسل نفس client_message_id، فلو كان الطلب الأول نجح فعلًا
 *   (وانقطع الرد فقط) يرجع الباك-إند نفس الرسالة بدل تكرارها.
 * - بدون إنترنت (المتصفح offline): TanStack Query يوقف الإرسال مؤقتًا ويكمله
 *   تلقائيًا أول ما يرجع الاتصال (الرسالة تبقى "بانتظار الاتصال")؛ أما رفض
 *   الخادم أو تعذّر الوصول له وهو متصل فيظهر "فشل" مع إعادة المحاولة.
 *
 * المدخلات: ticketId.
 * المخرجات: { entries, send, retry, discard }.
 * التأثيرات الجانبية: طلبات POST، وتحديث كاش التذكرة والمحادثة والقوائم.
 * ملاحظة: الصادر حالة بالصفحة فقط — لو غادر المستخدم الصفحة قبل نجاح
 * الإرسال، الرسائل الفاشلة ما تنحفظ (ما انحسبت مرسلة أصلًا).
 */
export function useTicketOutbox(ticketId: string) {
  const queryClient = useQueryClient()
  const [entries, setEntries] = useState<OutboxEntry[]>([])
  // نسخة حالية للقراءة داخل retry بدون إعادة إنشاء الدالة مع كل تغيير.
  const entriesRef = useRef(entries)
  useLayoutEffect(() => {
    entriesRef.current = entries
  })

  const { mutateAsync } = useMutation({
    mutationFn: (input: TicketMessageInput) => ticketsApi.postTicketMessage(ticketId, input),
  })

  const deliver = useCallback(
    async (entry: OutboxEntry) => {
      setEntries((prev) => {
        const next = { ...entry, status: 'sending' as const, error: null }
        return prev.some((e) => e.clientId === entry.clientId)
          ? prev.map((e) => (e.clientId === entry.clientId ? next : e))
          : [...prev, next]
      })
      try {
        const result = await mutateAsync({
          body: entry.doc,
          is_internal: entry.isInternal,
          status_after: entry.isInternal ? null : entry.statusAfter,
          client_message_id: entry.clientId,
          files: entry.files,
        })
        storePostedMessage(queryClient, result)
        setEntries((prev) => prev.filter((e) => e.clientId !== entry.clientId))
        return true
      } catch (error) {
        setEntries((prev) =>
          prev.map((e) =>
            e.clientId === entry.clientId ? { ...e, status: 'failed', error: extractErrorMessage(error) } : e,
          ),
        )
        return false
      }
    },
    [mutateAsync, queryClient],
  )

  /** يرسل رسالة جديدة. المخرجات: Promise<true> عند الحفظ، <false> عند الفشل. */
  const send = useCallback(
    (message: OutgoingMessage) =>
      deliver({
        clientId: newClientMessageId(),
        doc: message.doc,
        files: message.files,
        isInternal: message.isInternal,
        statusAfter: message.statusAfter,
        status: 'sending',
        error: null,
        createdAt: new Date().toISOString(),
      }),
    [deliver],
  )

  /** يعيد إرسال رسالة فاشلة بنفس معرّفها. */
  const retry = useCallback(
    (clientId: string) => {
      const entry = entriesRef.current.find((e) => e.clientId === clientId)
      if (entry) void deliver(entry)
    },
    [deliver],
  )

  /** يحذف رسالة فاشلة من المحادثة (ما انحفظت أصلًا). */
  const discard = useCallback((clientId: string) => {
    setEntries((prev) => prev.filter((e) => e.clientId !== clientId))
  }, [])

  return { entries, send, retry, discard }
}
