import { useCallback, useEffect, useRef, useState } from 'react'
import { io, type Socket } from 'socket.io-client'
import { API_BASE_URL } from '@/lib/apiClient'
import { useAuthStore } from '@/store/authStore'
import type { MeetingChatMessage } from '@/types'

/**
 * القناة اللحظية لغرفة الاجتماع — Socket.IO (قرار لاما 2026-09-10، بدّل
 * WebSocket الخام السابق — راجعي app/core/socketio_server.py بالباك-إند
 * للتصميم الكامل الجديد ومعالجات الأحداث). محادثة + رفع اليد + بث "بند
 * الأجندة قيد المناقشة الآن" — كلها عبر نفس الاتصال، بنفس الأحداث
 * بالضبط (الاسم الآن اسم حدث Socket.IO نفسه بدل حقل "type" بالحمولة).
 *
 * المصادقة: التوكن يمر عبر خيار Socket.IO "auth" (دالة تُستدعى قبل كل
 * محاولة اتصال/إعادة اتصال — تضمن دائمًا أحدث توكن من authStore وقتها،
 * بنفس فلسفة الكود القديم). لا حاجة بعد الآن للحيلة اليدوية لتفادي تسابق
 * اتصالات React StrictMode القديمة/الجديدة (كانت ضرورية فقط مع
 * WebSocket الخام لأن أحداثه onopen/onclose/onerror يمكن تصل متأخرة من
 * اتصال مهجور) — socket.io-client يدير هذا داخليًا بشكل آمن عبر
 * socket.disconnect() بدالة التنظيف.
 */

// socket.io-client يتصل بجذر الخادم (origin) لا مسار الـREST API —
// API_BASE_URL ينتهي بـ/api/v1 دائمًا (راجعي src/lib/apiClient.ts)، فنشتق
// الأصل بإزالة هذا اللاحق الثابت.
const SOCKET_ORIGIN = API_BASE_URL.replace(/\/api\/v1\/?$/, '')

/** يُصدَّر لاستخدامه أيضًا من useMinutesRealtime.ts — نفس منطق الاتصال
 * بالضبط (غرفة الاجتماع نفسها)، فقط باتصال Socket.IO منفصل (كل هوك له
 * اتصاله الخاص، بنفس فصل التصميم القديم — راجعي رأس useMinutesRealtime.ts). */
export function createMeetingSocket(meetingId: string): Socket {
  return io(SOCKET_ORIGIN, {
    path: '/socket.io',
    auth: (cb) => cb({ token: useAuthStore.getState().accessToken, meeting_id: meetingId }),
  })
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

  const socketRef = useRef<Socket | null>(null)

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

    setStatus('connecting')

    const socket = createMeetingSocket(meetingId)
    socketRef.current = socket

    socket.on('connect', () => setStatus('open'))

    socket.on('disconnect', (reason) => {
      // تشخيص إضافي (نفس روح تعليق 2026-09-10 القديم بكود WebSocket):
      // سبب الانقطاع الفعلي من طرف socket.io-client — يساعد لو رجعت
      // مشكلة تعليق مستقبلًا نعرف مباشرة هل انقطاع طبيعي أو خطأ فعلي.
      console.info(`[useMeetingRealtime] Socket.IO disconnected — reason=${reason}`)
      setStatus('closed')
    })

    socket.on('connect_error', (err) => {
      console.info(`[useMeetingRealtime] Socket.IO connect_error — ${err.message}`)
      setStatus('closed')
    })

    socket.on('chat.message', (payload: { message: MeetingChatMessage }) => {
      setLiveMessages((prev) => [...prev, payload.message])
    })

    socket.on('hand.raised', (payload: { user_id: string; full_name: string }) => {
      setRaisedHands((prev) =>
        prev.some((h) => h.userId === payload.user_id)
          ? prev
          : [...prev, { userId: payload.user_id, fullName: payload.full_name }],
      )
      pushActivity(`${payload.full_name} رفعت يدها`)
    })

    socket.on('hand.lowered', (payload: { user_id: string }) => {
      setRaisedHands((prev) => prev.filter((h) => h.userId !== payload.user_id))
    })

    socket.on('agenda.discussing', (payload: { agenda_item_id: string; title: string }) => {
      setDiscussingAgendaItem({ id: payload.agenda_item_id, title: payload.title })
      pushActivity(`بدأت مناقشة: ${payload.title}`)
    })

    socket.on('presence.joined', (payload: { user_id: string; full_name: string }) => {
      setOnlineUserIds((prev) => new Set(prev).add(payload.user_id))
      pushActivity(`انضم ${payload.full_name} إلى الاجتماع`)
    })

    socket.on('presence.left', (payload: { user_id: string; full_name: string }) => {
      setOnlineUserIds((prev) => {
        const next = new Set(prev)
        next.delete(payload.user_id)
        return next
      })
      setRaisedHands((prev) => prev.filter((h) => h.userId !== payload.user_id))
    })

    return () => {
      socket.disconnect()
      socketRef.current = null
    }
  }, [meetingId, pushActivity])

  const send = useCallback((event: string, payload?: Record<string, unknown>) => {
    socketRef.current?.emit(event, payload)
  }, [])

  const sendChatMessage = useCallback((body: string) => send('chat.send', { body }), [send])
  const raiseHand = useCallback(() => send('hand.raise'), [send])
  const lowerHand = useCallback(() => send('hand.lower'), [send])
  const announceDiscussing = useCallback(
    (agendaItemId: string, title: string) =>
      send('agenda.discussing', { agenda_item_id: agendaItemId, title }),
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
