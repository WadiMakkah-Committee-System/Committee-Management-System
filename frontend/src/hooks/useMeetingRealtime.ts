import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE_URL } from '@/lib/apiClient'
import { useAuthStore } from '@/store/authStore'
import type { MeetingChatMessage, MeetingRealtimeEvent } from '@/types'

/**
 * القناة اللحظية لغرفة الاجتماع — WebSocket حقيقي (قرار موثّق مع لاما
 * 2026-09-06، راجعي رأس db/migrations/0026_meeting_realtime.sql
 * وapp/core/meeting_realtime.py بالباك-إند للتصميم الكامل). محادثة +
 * رفع اليد + بث "بند الأجندة قيد المناقشة الآن" — كلها عبر نفس الاتصال.
 *
 * المصادقة: التوكن يُمرَّر كـQuery Param (?token=...) لأن اتصال
 * WebSocket من المتصفح لا يقدر يحمل Authorization Header مخصص (راجعي
 * app/core/dependencies.py::get_current_user_ws بالباك-إند). لا نحاول
 * تجديد Access Token منتصف الاتصال — لو انقطع الاتصال بسبب انتهاء صلاحية
 * التوكن (أو أي سبب آخر)، منطق إعادة المحاولة أدناه يعيد الاتصال بأحدث
 * توكن موجود بـauthStore وقتها (React Query/axios interceptor يكونان
 * جدّداه أصلًا لو انتهت صلاحيته أثناء طلبات REST موازية).
 */

const MAX_RECONNECT_DELAY_MS = 8000

function buildSocketUrl(meetingId: string, token: string): string {
  const wsBase = API_BASE_URL.replace(/^http/, 'ws')
  return `${wsBase}/meetings/${meetingId}/live?token=${encodeURIComponent(token)}`
}

export type MeetingConnectionStatus = 'connecting' | 'open' | 'closed'

export interface RaisedHand {
  userId: string
  fullName: string
}

export interface LiveActivityEvent {
  id: string
  text: string
  at: string
}

export function useMeetingRealtime(meetingId: string | undefined) {
  const [status, setStatus] = useState<MeetingConnectionStatus>('connecting')
  const [liveMessages, setLiveMessages] = useState<MeetingChatMessage[]>([])
  const [raisedHands, setRaisedHands] = useState<RaisedHand[]>([])
  const [discussingAgendaItem, setDiscussingAgendaItem] = useState<{ id: string; title: string } | null>(
    null,
  )
  const [activityEvents, setActivityEvents] = useState<LiveActivityEvent[]>([])
  const [onlineUserIds, setOnlineUserIds] = useState<Set<string>>(new Set())

  const socketRef = useRef<WebSocket | null>(null)
  const reconnectAttemptRef = useRef(0)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closedByUsRef = useRef(false)

  const pushActivity = useCallback((text: string) => {
    setActivityEvents((prev) =>
      [{ id: `${Date.now()}-${Math.random()}`, text, at: new Date().toISOString() }, ...prev].slice(
        0,
        50,
      ),
    )
  }, [])

  useEffect(() => {
    if (!meetingId) return
    closedByUsRef.current = false

    function connect() {
      const token = useAuthStore.getState().accessToken
      if (!token || !meetingId) return

      setStatus('connecting')
      const socket = new WebSocket(buildSocketUrl(meetingId, token))
      socketRef.current = socket

      socket.onopen = () => {
        reconnectAttemptRef.current = 0
        setStatus('open')
      }

      socket.onmessage = (event) => {
        let payload: MeetingRealtimeEvent
        try {
          payload = JSON.parse(event.data)
        } catch {
          return
        }

        switch (payload.type) {
          case 'chat.message':
            setLiveMessages((prev) => [...prev, payload.message])
            break
          case 'hand.raised':
            setRaisedHands((prev) =>
              prev.some((h) => h.userId === payload.user_id)
                ? prev
                : [...prev, { userId: payload.user_id, fullName: payload.full_name }],
            )
            pushActivity(`${payload.full_name} رفعت يدها`)
            break
          case 'hand.lowered':
            setRaisedHands((prev) => prev.filter((h) => h.userId !== payload.user_id))
            break
          case 'agenda.discussing':
            setDiscussingAgendaItem({ id: payload.agenda_item_id, title: payload.title })
            pushActivity(`بدأت مناقشة: ${payload.title}`)
            break
          case 'presence.joined':
            setOnlineUserIds((prev) => new Set(prev).add(payload.user_id))
            pushActivity(`انضم ${payload.full_name} إلى الاجتماع`)
            break
          case 'presence.left':
            setOnlineUserIds((prev) => {
              const next = new Set(prev)
              next.delete(payload.user_id)
              return next
            })
            setRaisedHands((prev) => prev.filter((h) => h.userId !== payload.user_id))
            break
        }
      }

      socket.onclose = () => {
        socketRef.current = null
        setStatus('closed')
        if (closedByUsRef.current) return

        const attempt = reconnectAttemptRef.current + 1
        reconnectAttemptRef.current = attempt
        const delay = Math.min(1000 * 2 ** attempt, MAX_RECONNECT_DELAY_MS)
        reconnectTimeoutRef.current = setTimeout(connect, delay)
      }

      socket.onerror = () => {
        socket.close()
      }
    }

    connect()

    return () => {
      closedByUsRef.current = true
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [meetingId, pushActivity])

  const send = useCallback((payload: Record<string, unknown>) => {
    const socket = socketRef.current
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload))
    }
  }, [])

  const sendChatMessage = useCallback((body: string) => send({ type: 'chat.send', body }), [send])
  const raiseHand = useCallback(() => send({ type: 'hand.raise' }), [send])
  const lowerHand = useCallback(() => send({ type: 'hand.lower' }), [send])
  const announceDiscussing = useCallback(
    (agendaItemId: string, title: string) =>
      send({ type: 'agenda.discussing', agenda_item_id: agendaItemId, title }),
    [send],
  )

  return {
    status,
    liveMessages,
    raisedHands,
    discussingAgendaItem,
    activityEvents,
    onlineUserIds,
    sendChatMessage,
    raiseHand,
    lowerHand,
    announceDiscussing,
  }
}
