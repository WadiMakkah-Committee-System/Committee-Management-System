import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { io, type Socket } from 'socket.io-client'
import { decisionsKeys } from '@/hooks/useDecisions'
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
  // إصلاح 2026-09-14 (بلاغ لاما — Bug 2: اسم المشارك بمربّع الفيديو يظهر
  // كرقم بدل اسمها): يربط agora_uid (رقمي، مختلف عن user_id) باسم صاحبه
  // الحقيقي — راجعي تعليق video_uid بـsocketio_server.py للتفصيل الكامل.
  const [videoUidNames, setVideoUidNames] = useState<Map<string, string>>(new Map())

  const socketRef = useRef<Socket | null>(null)
  const queryClient = useQueryClient()

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

    socket.on('video.uid', (payload: { user_id: string; full_name: string; agora_uid: number }) => {
      setVideoUidNames((prev) => new Map(prev).set(String(payload.agora_uid), payload.full_name))
    })

    socket.on(
      'video.roster',
      (payload: { entries: { user_id: string; full_name: string; agora_uid: number }[] }) => {
        setVideoUidNames((prev) => {
          const next = new Map(prev)
          for (const entry of payload.entries) next.set(String(entry.agora_uid), entry.full_name)
          return next
        })
      },
    )

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

    // إصلاح 2026-09-14 (بلاغ لاما — قرار ينشئه رئيس اللجنة داخل الاجتماع
    // لا يظهر للأعضاء الآخرين إلا بعد تحديث الصفحة يدويًا): DecisionsPanel
    // يعتمد كليًا على React Query بلا أي بث لحظي — بث "decision.created"
    // (جديد، راجعي app/api/v1/decisions.py) لا يحمل بيانات القرار نفسه،
    // فقط إشارة لإعادة الجلب — نفس فلسفة "minutes.updated" الموجودة أصلًا.
    socket.on('decision.created', (payload: { meeting_id: string }) => {
      queryClient.invalidateQueries({ queryKey: decisionsKeys.byMeeting(payload.meeting_id) })
      pushActivity('تم إنشاء قرار جديد')
    })

    // إصلاح 2026-09-13 (بلاغ لاما — عضو يفتح الاجتماع بعد غيره يرى البقية
    // "غير متصلين" رغم اتصالهم الفعلي): presence.joined وحده لا يكفي —
    // من يتصل الآن لا يعرف حالة الأعضاء المتصلين *قبله* أصلًا (أحداث
    // انضمامهم بُثّت قبل وجوده). presence.roster (جديد، راجعي
    // app/core/socketio_server.py::connect) يصل مرة واحدة فقط لهذا
    // الاتصال عند فتحه، بصورة كاملة لكل من هو متصل بالغرفة حاليًا.
    socket.on('presence.roster', (payload: { user_ids: string[] }) => {
      setOnlineUserIds((prev) => new Set([...prev, ...payload.user_ids]))
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

  // إصلاح 2026-09-14 (بلاغ لاما — رسالة الدردشة "تختفي، ما أدري وصلت ولا
  // لا"): send() أعلاه (لا تزال تُستخدم لأحداث بلا حاجة لتأكيد: رفع/خفض
  // اليد، بث بند الأجندة قيد المناقشة) كانت نفسها المستخدَمة سابقًا
  // لإرسال الدردشة أيضًا — emit عادي بلا أي انتظار لرد، فمهما حدث بجهة
  // الخادم (نجاح، رفض صلاحية، خطأ DB) الفرونت لا يعرف شيئًا إطلاقًا.
  // sendChatMessage الآن تستخدم emitWithAck (socket.io-client v4.5+، مع
  // .timeout() لتفادي انتظار أبدي لو الاتصال ميت فعليًا لكن لم يُطلق
  // حدث disconnect بعد) وتُرجع Promise حقيقي بنتيجة الإرسال، ليقرر
  // ChatPanel.tsx بناءً عليها: مسح الحقل فقط عند النجاح الفعلي، وإظهار
  // خطأ واضح للمستخدم عند الفشل بدل صمت الواجهة. الخادم (socketio_server.
  // py::chat_send) يُرجع الآن {ok, error?} أو {ok, message} من كل مسار —
  // راجعي تعليقه المقابل هناك.
  const sendChatMessage = useCallback(
    async (body: string): Promise<{ ok: boolean; error?: string }> => {
      const socket = socketRef.current
      if (!socket || !socket.connected) {
        return { ok: false, error: 'لا يوجد اتصال بقناة الدردشة حاليًا — تحققي من الاتصال وحاولي مجددًا.' }
      }
      try {
        const ack = (await socket.timeout(8000).emitWithAck('chat.send', { body })) as
          | { ok: true; message: MeetingChatMessage }
          | { ok: false; error?: string }
          | undefined
        if (!ack) {
          return { ok: false, error: 'لم يصل رد من الخادم — حاولي مجددًا.' }
        }
        if (!ack.ok) {
          return { ok: false, error: ack.error || 'تعذر إرسال الرسالة.' }
        }
        return { ok: true }
      } catch (err) {
        // socket.timeout(...) يرفض الـPromise لو انقضت المهلة بلا رد.
        console.error('[useMeetingRealtime] chat.send: لم يصل رد (timeout/خطأ اتصال)', err)
        return { ok: false, error: 'انتهت مهلة انتظار رد الخادم — تحققي من الاتصال وحاولي مجددًا.' }
      }
    },
    [],
  )
  const announceAgoraUid = useCallback((agoraUid: number) => send('video.uid', { agora_uid: agoraUid }), [send])
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
    videoUidNames,
    sendChatMessage,
    raiseHand,
    lowerHand,
    announceDiscussing,
    announceAgoraUid,
  }
}
