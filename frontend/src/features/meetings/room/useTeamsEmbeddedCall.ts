import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  Call,
  CallAgent,
  LocalVideoStream,
  RemoteParticipant,
  RemoteVideoStream,
} from '@azure/communication-calling'
import { getTeamsCallToken } from '@/api/meetings'
import { extractErrorMessage } from '@/lib/utils'

/** مراحل الاتصال المدمج: idle قبل الضغط، joining أثناء الاتصال، lobby بانتظار
 * سماح المنظّم، connected داخل الاجتماع، ended بعد المغادرة/الإنهاء، error فشل. */
export type EmbeddedCallPhase = 'idle' | 'joining' | 'lobby' | 'connected' | 'ended' | 'error'

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
 * قيود موثّقة (مايكروسوفت): المشارك من هنا ينضم كضيف — لا يدخل إلا بعد وجود
 * مستخدم Teams واحد على الأقل، ويمر بالـLobby حسب إعداد الاجتماع، ولا يستطيع
 * تشغيل التسجيل/التفريغ (يُشغَّلان من تطبيق Teams أو تلقائيًا).
 */
export function useTeamsEmbeddedCall(meetingId: string) {
  const [phase, setPhase] = useState<EmbeddedCallPhase>('idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [participants, setParticipants] = useState<EmbeddedParticipant[]>([])
  const [micMuted, setMicMuted] = useState(false)
  const [cameraOn, setCameraOn] = useState(false)
  const [screenSharing, setScreenSharing] = useState(false)
  const [localVideo, setLocalVideo] = useState<LocalVideoStream | null>(null)

  const agentRef = useRef<CallAgent | null>(null)
  const callRef = useRef<Call | null>(null)
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

  const join = useCallback(async () => {
    if (callRef.current) return
    setPhase('joining')
    setErrorMessage(null)
    try {
      const [sdk, common, joinInfo] = await Promise.all([
        import('@azure/communication-calling'),
        import('@azure/communication-common'),
        getTeamsCallToken(meetingId),
      ])
      idOfRef.current = (p) => common.getIdentifierRawId(p.identifier)

      const callClient = new sdk.CallClient()
      const agent = await callClient.createCallAgent(
        new common.AzureCommunicationTokenCredential(joinInfo.token),
        { displayName: joinInfo.display_name },
      )
      agentRef.current = agent

      const deviceManager = await callClient.getDeviceManager()
      await deviceManager.askDevicePermission({ audio: true, video: true })
      const cameras = await deviceManager.getCameras()
      const video = cameras[0] ? new sdk.LocalVideoStream(cameras[0]) : null
      localVideoRef.current = video
      setLocalVideo(video)
      setCameraOn(!!video)

      const call = agent.join(
        { meetingLink: joinInfo.join_url },
        {
          audioOptions: { muted: false },
          videoOptions: video ? { localVideoStreams: [video] } : undefined,
        },
      )
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
      call.remoteParticipants.forEach(watchParticipant)
      refresh()
    } catch (err) {
      setErrorMessage(extractErrorMessage(err))
      setPhase('error')
      callRef.current = null
      agentRef.current?.dispose().catch(() => {})
      agentRef.current = null
    }
  }, [meetingId, refresh, watchParticipant])

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
    join,
    leave,
    toggleMic,
    toggleCamera,
    toggleScreenShare,
  }
}

export type TeamsEmbeddedCall = ReturnType<typeof useTeamsEmbeddedCall>
