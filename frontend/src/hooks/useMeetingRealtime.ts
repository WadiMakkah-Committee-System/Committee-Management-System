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
  /** وقت الرفع (من الخادم) — ترتيب طابور المتحدثين: أول من رفع أول من يتكلم. */
  raisedAt: string
}

/** بند المناقشة الحالي + مؤقته الاختياري (durationSeconds=null ⇒ بدون مؤقت). */
export interface DiscussingAgendaItem {
  id: string
  title: string
  startedAt: string | null
  durationSeconds: number | null
}

interface DiscussingPayload {
  agenda_item_id: string
  title: string
  started_at?: string | null
  duration_seconds?: number | null
}

function toDiscussing(p: DiscussingPayload): DiscussingAgendaItem {
  return {
    id: p.agenda_item_id,
    title: p.title,
    startedAt: p.started_at ?? null,
    durationSeconds: p.duration_seconds ?? null,
  }
}

/** ترتيب الطابور حسب وقت الرفع. */
function sortHands(hands: RaisedHand[]): RaisedHand[] {
  return [...hands].sort((a, b) => a.raisedAt.localeCompare(b.raisedAt))
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
  const [discussingAgendaItem, setDiscussingAgendaItem] = useState<DiscussingAgendaItem | null>(null)
  // آخر من أعطاه الرئيس الكلمة (طابور المتحدثين) — الغرفة تعرض تنبيه.
  // الترجمة النصية الحية للاجتماع (يشغّلها رئيس اللجنة للكل) — قرار لاما 2026-11-03.
  const [captionsState, setCaptionsState] = useState<{ enabled: boolean; language: string }>({
    enabled: false,
    language: 'ar-sa',
  })
  const [floorGiven, setFloorGiven] = useState<{ userId: string; fullName: string; at: number } | null>(null)
  const [activityEvents, setActivityEvents] = useState<LiveActivityEvent[]>([])
  const [onlineUserIds, setOnlineUserIds] = useState<Set<string>>(new Set())

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

    // الصورة الحالية للغرفة عند الدخول (طابور الأيدي + بند المناقشة ومؤقته) —
    // للي يدخل متأخر (تحديث لاما 2026-11-03).
    socket.on(
      'room.state',
      (payload: {
        hands: { user_id: string; full_name: string; raised_at: string | null }[]
        discussing: DiscussingPayload | null
        captions?: { enabled: boolean; language: string } | null
      }) => {
        setCaptionsState(payload.captions ?? { enabled: false, language: 'ar-sa' })
        setRaisedHands(
          sortHands(
            payload.hands.map((h) => ({ userId: h.user_id, fullName: h.full_name, raisedAt: h.raised_at ?? '' })),
          ),
        )
        setDiscussingAgendaItem(payload.discussing ? toDiscussing(payload.discussing) : null)
      },
    )

    socket.on('hand.raised', (payload: { user_id: string; full_name: string; raised_at?: string }) => {
      setRaisedHands((prev) =>
        prev.some((h) => h.userId === payload.user_id)
          ? prev
          : sortHands([
              ...prev,
              { userId: payload.user_id, fullName: payload.full_name, raisedAt: payload.raised_at ?? new Date().toISOString() },
            ]),
      )
      pushActivity(`${payload.full_name} رفع/ت يده/ا`)
    })

    socket.on('captions.state', (payload: { enabled: boolean; language: string }) => {
      setCaptionsState(payload)
      pushActivity(payload.enabled ? 'شُغّلت الترجمة النصية' : 'أُوقفت الترجمة النصية')
    })

    socket.on('floor.given', (payload: { user_id: string; full_name: string }) => {
      setFloorGiven({ userId: payload.user_id, fullName: payload.full_name, at: Date.now() })
      if (payload.full_name) pushActivity(`الكلمة الآن لـ ${payload.full_name}`)
    })

    socket.on('hand.lowered', (payload: { user_id: string }) => {
      setRaisedHands((prev) => prev.filter((h) => h.userId !== payload.user_id))
    })

    socket.on('agenda.discussing', (payload: DiscussingPayload) => {
      setDiscussingAgendaItem(toDiscussing(payload))
      pushActivity(`بدأت مناقشة: ${payload.title}`)
    })

    socket.on('agenda.stopped', (payload: { title?: string | null }) => {
      setDiscussingAgendaItem(null)
      pushActivity(payload.title ? `انتهت مناقشة: ${payload.title}` : 'انتهت المناقشة')
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

    // تحديث لاما 2026-11-03: فتح التصويت يطلّع نافذة التصويت للحاضرين، وكل صوت
    // يحدّث العدّاد/النتيجة لحظيًا.
    socket.on('decision.voting_opened', (payload: { meeting_id: string }) => {
      queryClient.invalidateQueries({ queryKey: decisionsKeys.byMeeting(payload.meeting_id) })
      pushActivity('تم فتح التصويت على قرار')
    })
    socket.on('decision.voted', (payload: { meeting_id: string }) => {
      queryClient.invalidateQueries({ queryKey: decisionsKeys.byMeeting(payload.meeting_id) })
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
  }, [meetingId, pushActivity, queryClient])

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

      // إصلاح 2026-09-14 (بلاغ لاما الثاني — تظهر "انتهت قناة الاتصال"
      // رغم أن الرسالة تصل فعليًا لبقية المشاركين): تبيّن أن emitWithAck
      // وحدها قد تنتهي مهلتها (أو ترفض) حتى لو نجح الحفظ والبث فعليًا على
      // الخادم — فقط حزمة الـack بعينها ضاعت/تأخرت على اتصال غير مستقر
      // (لا الإرسال نفسه). الحل: عند فشل/انتهاء مهلة الـack تحديدًا، قبل
      // الجزم بالفشل نمنح بثّ "chat.message" ذاته مهلة أخيرة قصيرة —
      // المرسل نفسه عضو بغرفة الاجتماع فيستقبل بثّ رسالته هو أيضًا، فوصول
      // رسالة بنفس نصّه ومرسِلها إثبات استقلالي على النجاح الفعلي حتى لو
      // ضاع ردّ الـack بعينه. لا تُستخدم إلا بمسار timeout/الاستثناء
      // فقط — رفض الخادم الصريح (ack.ok === false) يبقى نهائيًا وفوريًا
      // كما هو، فهو ليس حالة غموض.
      const myUserId = useAuthStore.getState().user?.user_id
      let broadcastHandler: ((payload: { message: MeetingChatMessage }) => void) | null = null
      const broadcastConfirmed = new Promise<true>((resolve) => {
        broadcastHandler = (payload) => {
          if (payload.message.body === body && payload.message.sender.user_id === myUserId) resolve(true)
        }
        socket.on('chat.message', broadcastHandler)
      })

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
        // socket.timeout(...) يرفض الـPromise لو انقضت المهلة بلا رد —
        // قبل إظهار خطأ للمستخدمة، تحققي أولًا هل وصل بثّ رسالتها فعليًا.
        console.error(
          '[useMeetingRealtime] chat.send: لم يصل رد (timeout/خطأ اتصال) — بانتظار تأكيد البث كإثبات بديل...',
          err,
        )
        const confirmedViaBroadcast = await Promise.race([
          broadcastConfirmed,
          new Promise<false>((resolve) => setTimeout(() => resolve(false), 1500)),
        ])
        if (confirmedViaBroadcast) return { ok: true }
        return { ok: false, error: 'انتهت مهلة انتظار رد الخادم — تحققي من الاتصال وحاولي مجددًا.' }
      } finally {
        if (broadcastHandler) socket.off('chat.message', broadcastHandler)
      }
    },
    [],
  )
  const raiseHand = useCallback(() => send('hand.raise'), [send])
  const lowerHand = useCallback(() => send('hand.lower'), [send])
  // إصلاح 2026-09-14 (بلاغ لاما — رئيس اللجنة يضغط "بدء المناقشة" ولا
  // يظهر له أي مؤشر، كأنه لم يضغط شيئًا): كانت announceDiscussing تستخدم
  // send() العادي (بلا انتظار رد) — نفس عِلّة الدردشة قبل إصلاحها بالضبط.
  // الآن emitWithAck حقيقي بنتيجة واضحة — راجعي agenda_discussing
  // بـsocketio_server.py.
  /** إعطاء الكلمة لصاحب يد مرفوعة (رئيس اللجنة فقط — الخادم يتحقق). */
  const giveFloor = useCallback(async (userId: string): Promise<{ ok: boolean; error?: string }> => {
    const socket = socketRef.current
    if (!socket || !socket.connected) return { ok: false, error: 'لا يوجد اتصال بقناة الاجتماع حاليًا.' }
    try {
      const ack = (await socket.timeout(8000).emitWithAck('floor.give', { user_id: userId })) as
        | { ok: boolean; error?: string }
        | undefined
      return ack ?? { ok: false, error: 'لم يصل رد من الخادم — حاولي مجددًا.' }
    } catch {
      return { ok: false, error: 'انتهت مهلة انتظار رد الخادم — حاولي مجددًا.' }
    }
  }, [])

  /** تشغيل/إيقاف الترجمة النصية للكل (رئيس اللجنة — الخادم يتحقق). */
  const setCaptions = useCallback(
    async (enabled: boolean, language = 'ar-sa'): Promise<{ ok: boolean; error?: string }> => {
      const socket = socketRef.current
      if (!socket || !socket.connected) return { ok: false, error: 'لا يوجد اتصال بقناة الاجتماع حاليًا.' }
      try {
        const ack = (await socket.timeout(8000).emitWithAck('captions.set', { enabled, language })) as
          | { ok: boolean; error?: string }
          | undefined
        return ack ?? { ok: false, error: 'لم يصل رد من الخادم — حاولي مجددًا.' }
      } catch {
        return { ok: false, error: 'انتهت مهلة انتظار رد الخادم — حاولي مجددًا.' }
      }
    },
    [],
  )

  /** إيقاف مناقشة البند الحالي (رئيس اللجنة) — بلاغ لاما 2026-11-03. */
  const stopDiscussing = useCallback(async (): Promise<{ ok: boolean; error?: string }> => {
    const socket = socketRef.current
    if (!socket || !socket.connected) return { ok: false, error: 'لا يوجد اتصال بقناة الاجتماع حاليًا.' }
    try {
      const ack = (await socket.timeout(8000).emitWithAck('agenda.stop', {})) as
        | { ok: boolean; error?: string }
        | undefined
      return ack ?? { ok: false, error: 'لم يصل رد من الخادم — حاولي مجددًا.' }
    } catch {
      return { ok: false, error: 'انتهت مهلة انتظار رد الخادم — حاولي مجددًا.' }
    }
  }, [])

  /** durationSeconds اختياري: مؤقت البند (null/undefined ⇒ بدون مؤقت). */
  const announceDiscussing = useCallback(
    async (agendaItemId: string, title: string, durationSeconds?: number | null): Promise<{ ok: boolean; error?: string }> => {
      const socket = socketRef.current
      if (!socket || !socket.connected) {
        return { ok: false, error: 'لا يوجد اتصال بقناة الاجتماع حاليًا — تحققي من الاتصال وحاولي مجددًا.' }
      }
      try {
        const ack = (await socket
          .timeout(8000)
          .emitWithAck('agenda.discussing', {
            agenda_item_id: agendaItemId,
            title,
            duration_seconds: durationSeconds ?? null,
          })) as
          | { ok: true }
          | { ok: false; error?: string }
          | undefined
        if (!ack) return { ok: false, error: 'لم يصل رد من الخادم — حاولي مجددًا.' }
        if (!ack.ok) return { ok: false, error: ack.error || 'تعذر بدء المناقشة.' }
        return { ok: true }
      } catch (err) {
        console.error('[useMeetingRealtime] agenda.discussing: لم يصل رد (timeout/خطأ اتصال)', err)
        return { ok: false, error: 'انتهت مهلة انتظار رد الخادم — تحققي من الاتصال وحاولي مجددًا.' }
      }
    },
    [],
  )

  return {
    status,
    liveMessages,
    raisedHands,
    discussingAgendaItem,
    floorGiven,
    giveFloor,
    stopDiscussing,
    captionsState,
    setCaptions,
    activityEvents,
    onlineUserIds,
    sendChatMessage,
    raiseHand,
    lowerHand,
    announceDiscussing,
  }
}
