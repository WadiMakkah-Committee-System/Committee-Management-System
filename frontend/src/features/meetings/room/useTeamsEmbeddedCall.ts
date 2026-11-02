import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  CallAgentCommon,
  CallCommon,
  JoinCallOptions,
  LocalVideoStream,
  RemoteParticipant,
  RemoteVideoStream,
} from '@azure/communication-calling'
import { getTeamsCallToken } from '@/api/meetings'
import { getMicrosoftTeamsToken } from '@/lib/microsoftSignIn'
import { extractErrorMessage } from '@/lib/utils'

/** مراحل الاتصال المدمج: idle قبل الضغط، joining أثناء الاتصال، lobby بانتظار
 * سماح المنظّم، connected داخل الاجتماع، ended بعد المغادرة/الإنهاء، error فشل. */
export type EmbeddedCallPhase = 'idle' | 'joining' | 'lobby' | 'connected' | 'ended' | 'error'

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
 */
export function useTeamsEmbeddedCall(meetingId: string) {
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
    if (callRef.current) return
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
        else if (call.state === 'Connected') setPhase('connected')
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
      call.lobby.on('lobbyParticipantsUpdated', refreshLobby)
      call.remoteParticipants.forEach(watchParticipant)
      refresh()
      refreshLobby()
    } catch (err) {
      setErrorMessage(extractErrorMessage(err))
      setPhase('error')
      callRef.current = null
      agentRef.current?.dispose().catch(() => {})
      agentRef.current = null
    }
  }, [meetingId, refresh, refreshLobby, watchParticipant])

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
    join,
    leave,
    toggleMic,
    toggleCamera,
    toggleScreenShare,
  }
}

export type TeamsEmbeddedCall = ReturnType<typeof useTeamsEmbeddedCall>
