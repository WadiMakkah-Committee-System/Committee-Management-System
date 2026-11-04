import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  IAgoraRTCClient,
  IAgoraRTCRemoteUser,
  ICameraVideoTrack,
  ILocalVideoTrack,
  IMicrophoneAudioTrack,
  IRemoteAudioTrack,
  IRemoteVideoTrack,
  NetworkQuality as AgoraNetworkQuality,
} from 'agora-rtc-sdk-ng'
import { joinAgora } from '@/api/meetings'
import { extractErrorMessage } from '@/lib/utils'
import { getDevicePrefs, type DevicePrefs } from './devicePrefs'

/** مراحل الاتصال: idle قبل البدء، joining أثناء الاتصال، connected داخل الغرفة،
 * ended بعد المغادرة، error فشل (errorMessage يوضح السبب). */
export type AgoraCallPhase = 'idle' | 'joining' | 'connected' | 'ended' | 'error'

/** جودة الاتصال: good/poor/bad، أو offline لو انقطع النت (Agora يعيد الاتصال لحاله). */
export type NetworkQuality = 'good' | 'poor' | 'bad' | 'offline'

/** لقطة عرض لمشارك بعيد. userId = حسابه بالمنصة (التوكن مبني عليه بالخادم). */
export interface AgoraParticipant {
  userId: string
  name: string
  hasAudio: boolean
  speaking: boolean
  video: IRemoteVideoTrack | null
}

/** مصادر صوت الاجتماع الحالية — يستهلكها مسجّل الرئيس (useMeetingRecorder). */
export interface AudioSources {
  local: MediaStreamTrack | null
  remote: Map<string, MediaStreamTrack>
}

const SPEAKING_LEVEL = 8
/**
 * دقة الفيديو (قرار التكلفة — تقرير Agora 2026-11-03): Agora تحسب الدقيقة حسب
 * مجموع دقة كل الفيديوهات اللي يشوفها المشارك. الرئيسي بدقة 640×360 والمصغّرات
 * بالمسار المنخفض 320×180 ⇒ المجموع يبقى بشريحة HD (≤ 921,600 بكسل) حتى مع 10 أعضاء.
 */
const CAMERA_ENCODER = '360p_7' as const
const LOW_STREAM = { width: 320, height: 180, framerate: 15, bitrate: 140 }
/** مشاركة الشاشة 720p — واضحة لقراءة المستندات. */
const SCREEN_ENCODER = '720p_2' as const

function mapQuality(q: AgoraNetworkQuality): NetworkQuality {
  const worst = Math.max(q.uplinkNetworkQuality, q.downlinkNetworkQuality)
  if (worst >= 6) return 'offline'
  if (worst === 5) return 'bad'
  if (worst >= 3) return 'poor'
  return 'good'
}

/**
 * الهدف (الرجوع لـAgora — قرار لاما 2026-11-04):
 * اتصال الفيديو/الصوت داخل غرفة الاجتماع بالمنصة عبر Agora.
 *
 * المسؤولية:
 * - توكن من الخادم (POST /agora/join — فحص meetings.join هناك) ثم client.join
 *   بالحساب = user_id، فكل جهاز يعرف هوية كل صوت/فيديو مباشرة (userId).
 * - نشر المايك والكاميرا حسب تفضيلات الجهاز (DeviceCheck)، والاشتراك بالآخرين.
 * - أدوات التحكم: كتم/كاميرا/مشاركة شاشة/تبديل الأجهزة/مغادرة.
 * - جودة الاتصال، ومن يتكلم الآن (مستوى الصوت)، وتجديد التوكن قبل انتهائه.
 * - مصادر الصوت للتسجيل (getAudioSources + audioVersion يتغير مع كل تغيير).
 *
 * قرارات:
 * - كتم المايك = setMuted (يبقى الالتقاط شغال ويرسل صمت) بدل setEnabled — فمسار
 *   الصوت يبقى نفسه وتسجيل الرئيس ما ينقطع لما يكتم ويرجع.
 * - إطفاء الكاميرا = setEnabled(false) (يطفي ضوء الكاميرا — خصوصية).
 * - لو ما فيه كاميرا/مايك أو رفض الإذن: يدخل بدونها مع تنبيه (mediaIssues) بدل الفشل.
 * - مكتبة Agora كبيرة، تُحمَّل ديناميكيًا عند الدخول فقط.
 *
 * المدخلات: meetingId، nameOf(userId) لاسم المشارك من بيانات الاجتماع.
 */
export function useAgoraCall(meetingId: string, options: { nameOf: (userId: string) => string }) {
  const [phase, setPhase] = useState<AgoraCallPhase>('idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [participants, setParticipants] = useState<AgoraParticipant[]>([])
  const [micMuted, setMicMuted] = useState(false)
  const [cameraOn, setCameraOn] = useState(false)
  const [screenSharing, setScreenSharing] = useState(false)
  const [localVideo, setLocalVideo] = useState<ICameraVideoTrack | ILocalVideoTrack | null>(null)
  const [localSpeaking, setLocalSpeaking] = useState(false)
  const [networkQuality, setNetworkQuality] = useState<NetworkQuality>('good')
  const [mediaIssues, setMediaIssues] = useState<string[]>([])
  const [audioVersion, setAudioVersion] = useState(0)
  const [selfUserId, setSelfUserId] = useState<string | null>(null)

  const clientRef = useRef<IAgoraRTCClient | null>(null)
  const micRef = useRef<IMicrophoneAudioTrack | null>(null)
  const camRef = useRef<ICameraVideoTrack | null>(null)
  const screenRef = useRef<ILocalVideoTrack | null>(null)
  const remoteAudioRef = useRef(new Map<string, IRemoteAudioTrack>())
  const speakerIdRef = useRef<string | null>(null)
  const featuredRef = useRef<string | null>(null)
  const nameOfRef = useRef(options.nameOf)
  nameOfRef.current = options.nameOf
  const startingRef = useRef(false)

  /** يعيد بناء قائمة المشاركين من حالة Agora الحية (الكائنات الحية ما تُخزَّن بالـState). */
  const refreshParticipants = useCallback((levels?: Map<string, number>) => {
    const client = clientRef.current
    if (!client) return
    setParticipants((prev) => {
      const prevSpeaking = new Map(prev.map((p) => [p.userId, p.speaking]))
      return client.remoteUsers.map((u: IAgoraRTCRemoteUser) => {
        const userId = String(u.uid)
        return {
          userId,
          name: nameOfRef.current(userId),
          hasAudio: Boolean(u.hasAudio),
          speaking: levels ? (levels.get(userId) ?? 0) > SPEAKING_LEVEL : (prevSpeaking.get(userId) ?? false),
          video: u.videoTrack ?? null,
        }
      })
    })
  }, [])

  const cleanup = useCallback(async () => {
    micRef.current?.close()
    camRef.current?.close()
    screenRef.current?.close()
    micRef.current = null
    camRef.current = null
    screenRef.current = null
    remoteAudioRef.current.clear()
    const client = clientRef.current
    clientRef.current = null
    if (client) {
      client.removeAllListeners()
      await client.leave().catch(() => {})
    }
    setLocalVideo(null)
    setParticipants([])
    setScreenSharing(false)
    setAudioVersion((v) => v + 1)
  }, [])

  /** الدخول للغرفة (تلقائيًا من MeetingRoom أول ما تفتح، أو "إعادة الانضمام"). */
  const start = useCallback(async () => {
    if (startingRef.current || clientRef.current) return
    startingRef.current = true
    setPhase('joining')
    setErrorMessage(null)
    setMediaIssues([])
    try {
      const info = await joinAgora(meetingId)
      const { default: AgoraRTC } = await import('agora-rtc-sdk-ng')
      AgoraRTC.setLogLevel(3) // تحذيرات وأخطاء فقط بالكونسول
      const client = AgoraRTC.createClient({ mode: 'rtc', codec: 'vp8' })
      clientRef.current = client
      setSelfUserId(info.account)

      client.on('user-joined', () => refreshParticipants())
      client.on('user-left', (user) => {
        remoteAudioRef.current.delete(String(user.uid))
        setAudioVersion((v) => v + 1)
        refreshParticipants()
      })
      client.on('user-published', async (user, mediaType) => {
        try {
          await client.subscribe(user, mediaType)
        } catch {
          return
        }
        if (mediaType === 'audio' && user.audioTrack) {
          if (speakerIdRef.current) await user.audioTrack.setPlaybackDevice(speakerIdRef.current).catch(() => {})
          user.audioTrack.play()
          remoteAudioRef.current.set(String(user.uid), user.audioTrack)
          setAudioVersion((v) => v + 1)
        }
        if (mediaType === 'video') {
          // المصغّرات بالمسار المنخفض (أرخص + أخف)، والمعروض كبير بالعالي.
          const uid = String(user.uid)
          await client.setRemoteVideoStreamType(user.uid, featuredRef.current === uid ? 0 : 1).catch(() => {})
        }
        refreshParticipants()
      })
      client.on('user-unpublished', (user, mediaType) => {
        if (mediaType === 'audio') {
          remoteAudioRef.current.delete(String(user.uid))
          setAudioVersion((v) => v + 1)
        }
        refreshParticipants()
      })
      client.on('network-quality', (q) => setNetworkQuality(mapQuality(q)))
      client.on('connection-state-change', (state) => {
        if (state === 'RECONNECTING') setNetworkQuality('offline')
        if (state === 'CONNECTED') setNetworkQuality('good')
      })
      client.on('token-privilege-will-expire', async () => {
        try {
          const renewed = await joinAgora(meetingId)
          await client.renewToken(renewed.token)
        } catch {
          /* لو فشل التجديد: Agora يطلّعه عند الانتهاء ويظهر "إعادة الانضمام" */
        }
      })
      client.enableAudioVolumeIndicator()
      client.on('volume-indicator', (volumes) => {
        const levels = new Map(volumes.map((v) => [String(v.uid), v.level]))
        const own = levels.get(info.account) ?? 0
        setLocalSpeaking(own > SPEAKING_LEVEL && !(micRef.current?.muted ?? true))
        refreshParticipants(levels)
      })

      await client.enableDualStream().catch(() => {})
      client.setLowStreamParameter(LOW_STREAM)
      await client.join(info.app_id, info.channel, info.token, info.account)

      // المايك والكاميرا حسب تفضيلات الجهاز (فحص الأجهزة). أي فشل ⇒ يدخل بدونه + تنبيه.
      const prefs = getDevicePrefs()
      speakerIdRef.current = prefs.speakerId
      const issues: string[] = []
      try {
        const mic = await AgoraRTC.createMicrophoneAudioTrack({
          microphoneId: prefs.microphoneId ?? undefined,
          AEC: true,
          ANS: true,
          AGC: true,
        })
        micRef.current = mic
        await client.publish(mic)
        if (!prefs.micOn) await mic.setMuted(true)
        setMicMuted(!prefs.micOn)
        setAudioVersion((v) => v + 1)
      } catch {
        issues.push('ما قدرنا نشغّل المايك — تأكد من إذن المتصفح')
        setMicMuted(true)
      }
      if (prefs.cameraOn) {
        try {
          const cam = await AgoraRTC.createCameraVideoTrack({
            cameraId: prefs.cameraId ?? undefined,
            encoderConfig: CAMERA_ENCODER,
          })
          camRef.current = cam
          await client.publish(cam)
          setLocalVideo(cam)
          setCameraOn(true)
        } catch {
          issues.push('ما قدرنا نشغّل الكاميرا')
          setCameraOn(false)
        }
      } else {
        setCameraOn(false)
      }
      setMediaIssues(issues)
      refreshParticipants()
      setPhase('connected')
    } catch (err) {
      await cleanup()
      setErrorMessage(extractErrorMessage(err))
      setPhase('error')
    } finally {
      startingRef.current = false
    }
  }, [meetingId, refreshParticipants, cleanup])

  const leave = useCallback(async () => {
    await cleanup()
    setPhase('ended')
  }, [cleanup])

  const toggleMic = useCallback(async () => {
    const mic = micRef.current
    if (!mic) return
    const next = !mic.muted
    await mic.setMuted(next)
    setMicMuted(next)
  }, [])

  const toggleCamera = useCallback(async () => {
    const client = clientRef.current
    if (!client) return
    if (!camRef.current) {
      // أول تشغيل للكاميرا (دخل وهي مطفية).
      try {
        const { default: AgoraRTC } = await import('agora-rtc-sdk-ng')
        const cam = await AgoraRTC.createCameraVideoTrack({
          cameraId: getDevicePrefs().cameraId ?? undefined,
          encoderConfig: CAMERA_ENCODER,
        })
        camRef.current = cam
        if (!screenRef.current) {
          await client.publish(cam)
          setLocalVideo(cam)
        }
        setCameraOn(true)
      } catch {
        setMediaIssues((prev) => [...new Set([...prev, 'ما قدرنا نشغّل الكاميرا'])])
      }
      return
    }
    const next = !camRef.current.enabled
    await camRef.current.setEnabled(next)
    setCameraOn(next)
  }, [])

  const stopScreenShare = useCallback(async () => {
    const client = clientRef.current
    const screen = screenRef.current
    if (!client || !screen) return
    screenRef.current = null
    await client.unpublish(screen).catch(() => {})
    screen.close()
    if (camRef.current) {
      await client.publish(camRef.current).catch(() => {})
      setLocalVideo(camRef.current)
    } else {
      setLocalVideo(null)
    }
    setScreenSharing(false)
  }, [])

  /** مشاركة الشاشة تحل محل الكاميرا مؤقتًا (مسار فيديو واحد لكل مشارك). */
  const toggleScreenShare = useCallback(async (): Promise<boolean | null> => {
    const client = clientRef.current
    if (!client) return null
    if (screenRef.current) {
      await stopScreenShare()
      return false
    }
    try {
      const { default: AgoraRTC } = await import('agora-rtc-sdk-ng')
      const screen = (await AgoraRTC.createScreenVideoTrack({ encoderConfig: SCREEN_ENCODER }, 'disable')) as ILocalVideoTrack
      screenRef.current = screen
      if (camRef.current) await client.unpublish(camRef.current).catch(() => {})
      await client.publish(screen)
      setLocalVideo(screen)
      setScreenSharing(true)
      // إيقاف المشاركة من شريط المتصفح نفسه.
      screen.on('track-ended', () => void stopScreenShare())
      return true
    } catch {
      // ألغى اختيار الشاشة — مو خطأ.
      return null
    }
  }, [stopScreenShare])

  /** تبديل الأجهزة من نافذة الإعدادات (بدون خروج من الاجتماع). */
  const switchDevices = useCallback(async (prefs: DevicePrefs) => {
    if (prefs.microphoneId && micRef.current) await micRef.current.setDevice(prefs.microphoneId).catch(() => {})
    if (prefs.cameraId && camRef.current) await camRef.current.setDevice(prefs.cameraId).catch(() => {})
    speakerIdRef.current = prefs.speakerId
    if (prefs.speakerId) {
      for (const track of remoteAudioRef.current.values()) await track.setPlaybackDevice(prefs.speakerId).catch(() => {})
    }
    // تبديل المايك يغيّر المسار ⇒ المسجّل يعيد ربطه.
    setAudioVersion((v) => v + 1)
  }, [])

  /** من المعروض كبير — الاشتراك بالمسار العالي له والمنخفض للبقية. */
  const setFeatured = useCallback((userId: string | null) => {
    featuredRef.current = userId
    const client = clientRef.current
    if (!client) return
    for (const user of client.remoteUsers) {
      if (!user.hasVideo) continue
      void client.setRemoteVideoStreamType(user.uid, String(user.uid) === userId ? 0 : 1).catch(() => {})
    }
  }, [])

  /** مصادر الصوت الحالية للتسجيل: مايكي + صوت كل عضو (MediaStreamTrack خام). */
  const getAudioSources = useCallback((): AudioSources => {
    const remote = new Map<string, MediaStreamTrack>()
    for (const [userId, track] of remoteAudioRef.current) remote.set(userId, track.getMediaStreamTrack())
    return { local: micRef.current?.getMediaStreamTrack() ?? null, remote }
  }, [])

  // إغلاق الغرفة ⇒ خروج من القناة وتحرير الكاميرا/المايك.
  useEffect(() => {
    return () => {
      void cleanup()
    }
  }, [cleanup])

  return {
    phase,
    errorMessage,
    selfUserId,
    participants,
    micMuted,
    cameraOn,
    screenSharing,
    localVideo,
    localSpeaking,
    networkQuality,
    mediaIssues,
    audioVersion,
    start,
    leave,
    toggleMic,
    toggleCamera,
    toggleScreenShare,
    switchDevices,
    setFeatured,
    getAudioSources,
  }
}

export type AgoraCall = ReturnType<typeof useAgoraCall>
