import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  CallAgentCommon,
  CallCommon,
  JoinCallOptions,
  LocalVideoStream,
  RemoteParticipant,
  RemoteVideoStream,
} from '@azure/communication-calling'
import { getTeamsCallToken, getTeamsKnownGuests } from '@/api/meetings'
import { getMicrosoftTeamsToken } from '@/lib/microsoftSignIn'
import { useAuthStore } from '@/store/authStore'
import { extractErrorMessage } from '@/lib/utils'

/** مراحل الاتصال المدمج: idle قبل البدء، joining أثناء الاتصال، lobby بانتظار
 * السماح بالدخول، connected داخل الاجتماع، ended بعد المغادرة/الإنهاء، error فشل،
 * needs_signin: جلسة Microsoft انتهت وتحتاج ضغطة (المتصفح يمنع فتح نافذة
 * تسجيل الدخول تلقائيًا بدون ضغطة من المستخدم). */
export type EmbeddedCallPhase = 'idle' | 'joining' | 'lobby' | 'connected' | 'ended' | 'error' | 'needs_signin'

/** نوع هوية المستخدم داخل الاجتماع: teams_user بحساب الشركة، guest ضيف. */
export type EmbeddedCallIdentity = 'teams_user' | 'guest'

/** مشارك ينتظر بالـLobby (يقبله المنظّم/الرئيس من داخل المنصة). */
export interface LobbyParticipant {
  key: string
  name: string
}

/** لقطة عرض لمشارك بعيد — تُشتق من كائنات SDK بعد كل حدث (لا تُخزَّن الكائنات الحية بالـState). */
export interface EmbeddedParticipant {
  key: string
  name: string
  isMuted: boolean
  isSpeaking: boolean
  video: RemoteVideoStream | null
  screen: RemoteVideoStream | null
}

/**
 * الهدف (تجربة poc/acs-teams-embed — 2026-11-02):
 * الانضمام لاجتماع Microsoft Teams **من داخل غرفة الاجتماع بالمنصة** (نفس
 * الـframe الذي كان يعرض فيديو Agora) عبر Azure Communication Services —
 * بدل فتح تطبيق Teams. الاجتماع نفسه اجتماع Teams حقيقي (يسجَّل ويُفرَّغ هناك).
 *
 * المسؤولية:
 * - طلب توكن ACS + رابط الاجتماع من الباك-إند (فحص meetings.join هناك).
 * - إنشاء CallAgent والانضمام بـcallAgent.join({ meetingLink }).
 * - تتبّع الحالة (Lobby/متصل/انتهى) والمشاركين ومقاطع الفيديو والمايك.
 * - أدوات التحكم: كتم المايك، الكاميرا، مشاركة الشاشة، المغادرة.
 *
 * المدخلات: meetingId.
 * المخرجات: الحالة + الدوال أعلاه + localVideo (للمعاينة).
 * التأثيرات الجانبية: يطلب إذن الكاميرا/المايك من المتصفح، ويُنهي المكالمة
 * تلقائيًا عند إغلاق الغرفة (unmount).
 * ملاحظة أداء: مكتبة الاتصال كبيرة، فتُحمَّل ديناميكيًا (import()) عند
 * الضغط على "انضمام" فقط — لا تُثقل تحميل بقية صفحات المنصة.
 * نوعا الدخول:
 * - بحساب Microsoft (microsoftToken مُمرَّر لـjoin): createTeamsCallAgent —
 *   يدخل باسمه الحقيقي، بدون Lobby (موظف بالشركة)، والمنظّم/الرئيس يقدر
 *   يقبل المنتظرين (admit/admitAll). التوكن يُجدَّد تلقائيًا كل ساعة تقريبًا.
 * - ضيف: createCallAgent — ينتظر بالـLobby حتى يقبله أحد من الشركة.
 * قيود موثّقة (مايكروسوفت): لا أحد من الاثنين يقدر يشغّل التسجيل/التفريغ من
 * هنا — الاجتماع يُنشأ بتسجيل تلقائي (recordAutomatically) بالباك-إند.
 *
 * تحديث لاما 2026-11-03:
 * - start: الدخول يبدأ تلقائيًا أول ما تفتح الغرفة (MeetingRoom) — بدون زر
 *   انضمام ثاني داخل الإطار. يختار نوع الدخول حسب جلسة المنصة (Microsoft/كلمة مرور).
 * - قاعة الانتظار: reject + قبول تلقائي لأعضاء اللجنة اللي دخلوا كضيوف من
 *   المنصة (GET /teams/known-guests) — onAutoAdmitted يبلّغ الغرفة بأسمائهم.
 */
export function useTeamsEmbeddedCall(
  meetingId: string,
  options: { onAutoAdmitted?: (name: string) => void } = {},
) {
  const [phase, setPhase] = useState<EmbeddedCallPhase>('idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [participants, setParticipants] = useState<EmbeddedParticipant[]>([])
  const [micMuted, setMicMuted] = useState(false)
  const [cameraOn, setCameraOn] = useState(false)
  const [screenSharing, setScreenSharing] = useState(false)
  const [localVideo, setLocalVideo] = useState<LocalVideoStream | null>(null)
  const [identity, setIdentity] = useState<EmbeddedCallIdentity | null>(null)
  const [lobbyParticipants, setLobbyParticipants] = useState<LobbyParticipant[]>([])

  const agentRef = useRef<CallAgentCommon | null>(null)
  const callRef = useRef<CallCommon | null>(null)
  const localVideoRef = useRef<LocalVideoStream | null>(null)
  const idOfRef = useRef<((p: RemoteParticipant) => string) | null>(null)
  const identityRef = useRef<EmbeddedCallIdentity | null>(null)
  const joiningRef = useRef(false)
  // مفاتيح المنتظرين اللي بدأ قبولهم تلقائيًا — يمنع تكرار القبول لنفس الشخص.
  const autoAdmittingRef = useRef(new Set<string>())
  const onAutoAdmittedRef = useRef(options.onAutoAdmitted)
  useEffect(() => {
    onAutoAdmittedRef.current = options.onAutoAdmitted
  }, [options.onAutoAdmitted])

  /** يعيد اشتقاق لقطة المشاركين وحالة المايك/الشاشة من كائن المكالمة الحي. */
  const refresh = useCallback(() => {
    const call = callRef.current
    const idOf = idOfRef.current
    if (!call || !idOf) return
    setMicMuted(call.isMuted)
    setScreenSharing(call.isScreenSharingOn)
    setParticipants(
      call.remoteParticipants.map((p) => ({
        key: idOf(p),
        name: p.displayName || 'مشارك',
        isMuted: p.isMuted,
        isSpeaking: p.isSpeaking,
        video: p.videoStreams.find((s) => s.mediaStreamType === 'Video' && s.isAvailable) ?? null,
        screen: p.videoStreams.find((s) => s.mediaStreamType === 'ScreenSharing' && s.isAvailable) ?? null,
      })),
    )
  }, [])

  /** يعيد اشتقاق قائمة المنتظرين بالـLobby (تظهر فقط لمن يملك صلاحية القبول). */
  const refreshLobby = useCallback(() => {
    const call = callRef.current
    const idOf = idOfRef.current
    if (!call || !idOf) return
    setLobbyParticipants(call.lobby.participants.map((p) => ({ key: idOf(p), name: p.displayName || 'ضيف' })))
  }, [])

  /**
   * القبول التلقائي: لو أنا داخل بحساب Microsoft (أقدر أقبل)، أي منتظر هويته
   * صادرة من منصتنا لعضو مصرّح له بهذا الاجتماع يُقبل فورًا. غير المعروفين
   * (دخلوا برابط Teams من خارج المنصة) يبقون للقبول اليدوي. الفشل صامت —
   * مثلًا لو حسابي ما عنده صلاحية القبول بـTeams.
   */
  const autoAdmitKnownGuests = useCallback(async () => {
    const call = callRef.current
    const idOf = idOfRef.current
    if (!call || !idOf || identityRef.current !== 'teams_user' || call.state !== 'Connected') return
    const waiting = call.lobby.participants.filter((p) => !autoAdmittingRef.current.has(idOf(p)))
    if (waiting.length === 0) return
    let known: Set<string>
    try {
      known = new Set((await getTeamsKnownGuests(meetingId)).map((g) => g.acs_user_id))
    } catch {
      return
    }
    for (const p of waiting) {
      const key = idOf(p)
      if (!known.has(key)) continue
      autoAdmittingRef.current.add(key)
      call.lobby
        .admit(p.identifier)
        .then(() => onAutoAdmittedRef.current?.(p.displayName || 'عضو باللجنة'))
        .catch(() => autoAdmittingRef.current.delete(key))
    }
  }, [meetingId])

  /** يشترك بأحداث مشارك بعيد (فيديو/مايك/تحدّث/اسم) ليُحدَّث العرض لحظيًا. */
  const watchParticipant = useCallback(
    (p: RemoteParticipant) => {
      p.on('isMutedChanged', refresh)
      p.on('isSpeakingChanged', refresh)
      p.on('displayNameChanged', refresh)
      p.on('videoStreamsUpdated', (e) => {
        e.added.forEach((s) => s.on('isAvailableChanged', refresh))
        refresh()
      })
      p.videoStreams.forEach((s) => s.on('isAvailableChanged', refresh))
    },
    [refresh],
  )

  /**
   * الانضمام. microsoftToken (اختياري) ⇒ دخول بحساب Microsoft حق الشركة،
   * وبدونه ⇒ ضيف. الباك-إند يقرر النوع النهائي ويرجعه بـidentity.
   */
  const join = useCallback(async (microsoftToken?: string | null) => {
    if (callRef.current || joiningRef.current) return
    joiningRef.current = true
    setPhase('joining')
    setErrorMessage(null)
    try {
      const [sdk, common, joinInfo] = await Promise.all([
        import('@azure/communication-calling'),
        import('@azure/communication-common'),
        getTeamsCallToken(meetingId, microsoftToken),
      ])
      idOfRef.current = (p) => common.getIdentifierRawId(p.identifier)
      setIdentity(joinInfo.identity)
      identityRef.current = joinInfo.identity

      const callClient = new sdk.CallClient()
      let agent: CallAgentCommon
      // الانضمام الفعلي يتأخر لما بعد تجهيز الكاميرا (joinOptions) — نحفظه كدالة.
      let startCall: (options: JoinCallOptions) => CallCommon
      if (joinInfo.identity === 'teams_user') {
        // توكن مستخدم Teams صالح ساعة تقريبًا ⇒ تجديد تلقائي قبل انتهائه بتوكن
        // Microsoft صامت جديد (اجتماعات اللجان قد تطول عن ساعة).
        const credential = new common.AzureCommunicationTokenCredential({
          token: joinInfo.token,
          refreshProactively: true,
          tokenRefresher: async () => {
            const fresh = await getMicrosoftTeamsToken()
            if (!fresh) throw new Error('انتهت جلسة حساب Microsoft — أعد تسجيل الدخول')
            return (await getTeamsCallToken(meetingId, fresh)).token
          },
        })
        const teamsAgent = await callClient.createTeamsCallAgent(credential)
        agent = teamsAgent
        startCall = (options) => teamsAgent.join({ meetingLink: joinInfo.join_url }, options)
      } else {
        const guestAgent = await callClient.createCallAgent(new common.AzureCommunicationTokenCredential(joinInfo.token), {
          displayName: joinInfo.display_name,
        })
        agent = guestAgent
        startCall = (options) => guestAgent.join({ meetingLink: joinInfo.join_url }, options)
      }
      agentRef.current = agent

      const deviceManager = await callClient.getDeviceManager()
      await deviceManager.askDevicePermission({ audio: true, video: true })
      const cameras = await deviceManager.getCameras()
      const video = cameras[0] ? new sdk.LocalVideoStream(cameras[0]) : null
      localVideoRef.current = video
      setLocalVideo(video)
      setCameraOn(!!video)

      const joinOptions: JoinCallOptions = {
        audioOptions: { muted: false },
        videoOptions: video ? { localVideoStreams: [video] } : undefined,
      }
      const call = startCall(joinOptions)
      callRef.current = call

      call.on('stateChanged', () => {
        if (call.state === 'InLobby') setPhase('lobby')
        else if (call.state === 'Connected') {
          setPhase('connected')
          // منتظرين كانوا قبل دخولي (مثلًا أعضاء دخلوا قبل الرئيس) ⇒ نقبلهم الحين.
          refreshLobby()
          void autoAdmitKnownGuests()
        }
        else if (call.state === 'Disconnected') {
          const reason = call.callEndReason
          // 0 = إنهاء طبيعي (مغادرة/إنهاء الاجتماع). غير ذلك = رفض/خطأ.
          if (reason && reason.code !== 0) {
            setErrorMessage(`انتهى الاتصال (رمز ${reason.code}${reason.subCode ? `/${reason.subCode}` : ''})`)
            setPhase('error')
          } else {
            setPhase('ended')
          }
          callRef.current = null
        }
        refresh()
      })
      call.on('remoteParticipantsUpdated', (e) => {
        e.added.forEach(watchParticipant)
        refresh()
      })
      call.on('isMutedChanged', refresh)
      call.on('isScreenSharingOnChanged', refresh)
      call.lobby.on('lobbyParticipantsUpdated', () => {
        refreshLobby()
        void autoAdmitKnownGuests()
      })
      call.remoteParticipants.forEach(watchParticipant)
      refresh()
      refreshLobby()
      joiningRef.current = false
    } catch (err) {
      joiningRef.current = false
      setErrorMessage(extractErrorMessage(err))
      setPhase('error')
      callRef.current = null
      agentRef.current?.dispose().catch(() => {})
      agentRef.current = null
    }
  }, [meetingId, refresh, refreshLobby, watchParticipant, autoAdmitKnownGuests])

  /**
   * بدء الدخول حسب جلسة المنصة: دخل بحساب Microsoft ⇒ توكن Teams صامت (بهويته)،
   * وإلا ضيف. interactive=true فقط من ضغطة زر (يسمح بنافذة Microsoft لو انتهت
   * جلستها) — بدونه ننتقل لـneeds_signin بدل نافذة يحجبها المتصفح.
   */
  const start = useCallback(
    async (interactive = false) => {
      if (callRef.current || joiningRef.current) return
      if (useAuthStore.getState().authMethod !== 'microsoft') {
        await join(null)
        return
      }
      setPhase('joining')
      setErrorMessage(null)
      const token = await getMicrosoftTeamsToken(interactive).catch(() => null)
      if (!token) {
        setPhase('needs_signin')
        return
      }
      await join(token)
    },
    [join],
  )

  const leave = useCallback(async () => {
    const call = callRef.current
    callRef.current = null
    await call?.hangUp().catch(() => {})
    await agentRef.current?.dispose().catch(() => {})
    agentRef.current = null
    setPhase('ended')
  }, [])

  const toggleMic = useCallback(async () => {
    const call = callRef.current
    if (!call) return
    await (call.isMuted ? call.unmute() : call.mute()).catch(() => {})
  }, [])

  const toggleCamera = useCallback(async () => {
    const call = callRef.current
    const video = localVideoRef.current
    if (!call || !video) return
    try {
      if (call.localVideoStreams.some((s) => s.mediaStreamType === 'Video')) {
        await call.stopVideo(video)
        setCameraOn(false)
      } else {
        await call.startVideo(video)
        setCameraOn(true)
      }
    } catch {
      /* تجاهل: المتصفح رفض أو الكاميرا مستخدمة — الحالة تبقى كما هي */
    }
  }, [])

  const toggleScreenShare = useCallback(async () => {
    const call = callRef.current
    if (!call) return
    await (call.isScreenSharingOn ? call.stopScreenSharing() : call.startScreenSharing()).catch(() => {})
  }, [])

  /** قبول مشارك من الـLobby (للمنظّم/الرئيس الداخل بحساب Microsoft). key فارغ ⇒ قبول الكل. */
  const admit = useCallback(async (key?: string) => {
    const call = callRef.current
    const idOf = idOfRef.current
    if (!call || !idOf) return
    if (!key) {
      await call.lobby.admitAll()
      return
    }
    const target = call.lobby.participants.find((p) => idOf(p) === key)
    if (target) await call.lobby.admit(target.identifier)
  }, [])

  /** رفض منتظر من قاعة الانتظار (يطلع من الاجتماع). */
  const reject = useCallback(async (key: string) => {
    const call = callRef.current
    const idOf = idOfRef.current
    if (!call || !idOf) return
    const target = call.lobby.participants.find((p) => idOf(p) === key)
    if (target) await call.lobby.reject(target.identifier)
  }, [])

  // إغلاق الغرفة (unmount) ⇒ إنهاء المكالمة وتحرير الموارد حتى لا يبقى المستخدم
  // "داخل" اجتماع Teams بعد مغادرة الصفحة.
  useEffect(() => {
    return () => {
      callRef.current?.hangUp().catch(() => {})
      agentRef.current?.dispose().catch(() => {})
    }
  }, [])

  return {
    phase,
    errorMessage,
    participants,
    micMuted,
    cameraOn,
    screenSharing,
    localVideo,
    identity,
    lobbyParticipants,
    admit,
    reject,
    start,
    join,
    leave,
    toggleMic,
    toggleCamera,
    toggleScreenShare,
  }
}

export type TeamsEmbeddedCall = ReturnType<typeof useTeamsEmbeddedCall>
