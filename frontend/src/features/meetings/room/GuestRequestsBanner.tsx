import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, UserPlus, X } from 'lucide-react'
import type { Socket } from 'socket.io-client'
import * as guestsApi from '@/api/meetingGuests'
import { useToast } from '@/components/ui/Toast'
import { meetingsKeys } from '@/hooks/useMeetings'
import { extractErrorMessage } from '@/lib/utils'

/**
 * قاعة انتظار الضيوف داخل الغرفة (migration 0047 — قرار لاما 2026-11-10):
 * "فلان يطلب الدخول" مع قبول/رفض لأي شخص داخل الاجتماع (الباك-إند يفحص
 * meetings.join). تتحدث فورًا عبر أحداث Socket.IO (guests.requested /
 * guests.updated) وبجلب دوري احتياطي.
 */
export function GuestRequestsBanner({ meetingId, socket }: { meetingId: string; socket: Socket | null }) {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [busyId, setBusyId] = useState<string | null>(null)
  const key = [...meetingsKeys.detail(meetingId), 'guest-requests']

  const requestsQuery = useQuery({
    queryKey: key,
    queryFn: () => guestsApi.fetchGuestRequests(meetingId),
    refetchInterval: 15_000,
    retry: false,
  })

  useEffect(() => {
    if (!socket) return
    const refresh = () => void queryClient.invalidateQueries({ queryKey: key })
    const onUpdated = (payload: { status?: string }) => {
      refresh()
      // ضيف انقبل ⇒ يظهر بقائمة المشاركين واسمه بالفيديو.
      if (payload.status === 'admitted') void queryClient.invalidateQueries({ queryKey: meetingsKeys.detail(meetingId), exact: true })
    }
    socket.on('guests.requested', refresh)
    socket.on('guests.updated', onUpdated)
    return () => {
      socket.off('guests.requested', refresh)
      socket.off('guests.updated', onUpdated)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [socket, meetingId, queryClient])

  async function decide(requestId: string, admit: boolean) {
    setBusyId(requestId)
    try {
      const result = await guestsApi.decideGuestRequest(meetingId, requestId, admit)
      showToast(admit ? `تم قبول ${result.display_name}` : `تم رفض ${result.display_name}`, admit ? 'success' : 'info')
    } catch (err) {
      showToast(extractErrorMessage(err), 'error')
    } finally {
      setBusyId(null)
      void queryClient.invalidateQueries({ queryKey: key })
      void queryClient.invalidateQueries({ queryKey: meetingsKeys.detail(meetingId), exact: true })
    }
  }

  const pending = requestsQuery.data ?? []
  if (pending.length === 0) return null

  return (
    <div className="flex flex-col gap-2">
      {pending.map((r) => (
        <div
          key={r.request_id}
          className="flex items-center justify-between gap-3 rounded-md border border-info/30 bg-info-bg px-3 py-2"
        >
          <p className="flex min-w-0 items-center gap-2 text-[13px] text-text-primary">
            <UserPlus size={15} className="shrink-0 text-info" />
            <span className="truncate">
              <span className="font-semibold">{r.display_name}</span> (ضيف) يطلب الدخول
            </span>
          </p>
          <div className="flex shrink-0 items-center gap-1.5">
            <button
              type="button"
              disabled={busyId === r.request_id}
              onClick={() => void decide(r.request_id, true)}
              className="flex items-center gap-1 rounded-full bg-success px-3 py-1 text-[12px] font-semibold text-white transition-all hover:brightness-95 disabled:opacity-50"
            >
              <Check size={13} /> قبول
            </button>
            <button
              type="button"
              disabled={busyId === r.request_id}
              onClick={() => void decide(r.request_id, false)}
              className="flex items-center gap-1 rounded-full border border-border-default bg-bg-surface px-3 py-1 text-[12px] font-semibold text-text-secondary transition-colors hover:border-danger hover:text-danger disabled:opacity-50"
            >
              <X size={13} /> رفض
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
