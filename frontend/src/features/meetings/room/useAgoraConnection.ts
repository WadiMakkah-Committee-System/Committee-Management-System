import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  IAgoraRTCClient,
  IAgoraRTCRemoteUser,
  ICameraVideoTrack,
  ILocalVideoTrack,
  IMicrophoneAudioTrack,
} from 'agora-rtc-sdk-ng'
import { useJoinMeeting, useLeaveMeeting } from '@/hooks/useMeetings'
import { extractErrorMessage } from '@/lib/utils'

/**
 * منطق اتصال Agora RTC الفعلي — مستخرَج من المكوّن القديم MeetingRoom.tsx
 * (الإصدار السابق لإعادة تصميم غرفة الاجتماع 2026-09-06) بلا أي تغيير
 * جوهري بمنطق الاتصال نفسه، فقط بشكل Hook مستقل تستهلكه MeetingStage.tsx
 * الجديدة. راجعي رأس db/migrations/0022_meetings_agora_video.sql
 * بالباك-إند لتفصيل التوكن/القناة.
 *
 * localDisplayTrack: قيمة تفاعلية واحدة (State وليس Ref) تمثّل "مسار
 * الفيديو المحلي المعروض حاليًا" — الكاميرا عاديًا، أو الشاشة أثناء
 * مشاركتها (تستبدلها بنفس الموضع، تمامًا كالسلوك القديم) — بدل تمرير
 * Ref حاوية تشغيل يدويًا من الخارج كما كان بالتصميم السابق. تسمح لأي
 * مكوّن عرض (MeetingStage) بإعادة تشغيل نفس المسار بأي حاوية DOM يريدها
 * (كبيرة بالمنصة الرئيسية أو صغيرة بشريط المصغّرات) عبر track.play()
 * ببساطة — Agora ينقل الالتصاق تلقائيًا للحاوية الجديدة الأخيرة.
 */

export type ConnectionPhase = 'connecting' | 'connected' | 'error'

export interface RemoteParticipant {
  uid: string | number
  hasVideo: boolean
  hasAudio: boolean
  audioLevel: number
  videoTrack: IAgoraRTCRemoteUser['videoTrack']
}

export function useAgoraConnection(meetingId: string) {
  const joinMutation = useJoinMeeting()
  const leaveMutation = useLeaveMeeting()

  const [phase, setPhase] = useState<ConnectionPhase>('connecting')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [micEnabled, setMicEnabled] = useState(true)
  const [camEnabled, setCamEnabled] = useState(true)
  const [sharingScreen, setSharingScreen] = useState(false)
  const [remoteParticipants, setRemoteParticipants] = useState<RemoteParticipant[]>([])
  const [localAudioLevel, setLocalAudioLevel] = useState(0)
  const [localDisplayTrack, setLocalDisplayTrack] = useState<
    ICameraVideoTrack | ILocalVideoTrack | null
  >(null)

  const clientRef = useRef<IAgoraRTCClient | null>(null)
  const micTrackRef = useRef<IMicrophoneAudioTrack | null>(null)
  const camTrackRef = useRef<ICameraVideoTrack | null>(null)
  const screenVideoTrackRef = useRef<ILocalVideoTrack | null>(null)
  const agoraUidRef = useRef<number | null>(null)
  const leftRef = useRef(false)

  const cleanupAndLeave = useCallback(async () => {
    if (leftRef.current) return
    leftRef.current = true

    micTrackRef.current?.close()
    camTrackRef.current?.close()
    screenVideoTrackRef.current?.close()

    const client = clientRef.current
    clientRef.current = null
    if (client) {
      try {
        await client.leave()
      } catch {
        // تجاهل — الهدف الأساسي إغلاق المسارات محليًا، مو ضمان نجاح leave بالسيرفر.
      }
    }

    if (agoraUidRef.current !== null) {
      leaveMutation.mutate({ meetingId, agoraUid: agoraUidRef.current })
    }
  }, [leaveMutation, meetingId])

  useEffect(() => {
    let cancelled = false

    async function connect() {
      try {
        setPhase('connecting')
        setErrorMessage(null)

        const joinInfo = await joinMutation.mutateAsync(meetingId)
        if (cancelled) return
        agoraUidRef.current = joinInfo.uid

        const { default: AgoraRTC } = await import('agora-rtc-sdk-ng')
        if (cancelled) return

        const client = AgoraRTC.createClient({ mode: 'rtc', codec: 'vp8' })
        clientRef.current = client

        // مؤشر "المتحدث الآن" الحقيقي — مستوى صوت كل مشارك (Agora
        // Volume Indicator، كل 200ms افتراضيًا) — تستخدمه MeetingStage.tsx
        // لتمييز صاحب الصوت الأعلى بإطار مضيء، بدل تخمين بصري وهمي.
        client.enableAudioVolumeIndicator()
        client.on('volume-indicator', (volumes) => {
          setRemoteParticipants((prev) =>
            prev.map((p) => {
              const match = volumes.find((v) => v.uid === p.uid)
              return match ? { ...p, audioLevel: match.level } : p
            }),
          )
          const own = volumes.find((v) => v.uid === joinInfo.uid)
          if (own) setLocalAudioLevel(own.level)
        })

        client.on('user-published', async (user, mediaType) => {
          await client.subscribe(user, mediaType)
          if (mediaType === 'video') {
            setRemoteParticipants((prev) => {
              const others = prev.filter((p) => p.uid !== user.uid)
              return [
                ...others,
                {
                  uid: user.uid,
                  hasVideo: true,
                  hasAudio: !!user.hasAudio,
                  audioLevel: 0,
                  videoTrack: user.videoTrack,
                },
              ]
            })
          }
          if (mediaType === 'audio') {
            user.audioTrack?.play()
            setRemoteParticipants((prev) =>
              prev.map((p) => (p.uid === user.uid ? { ...p, hasAudio: true } : p)),
            )
          }
        })

        client.on('user-unpublished', (user, mediaType) => {
          if (mediaType === 'video') {
            setRemoteParticipants((prev) =>
              prev.map((p) => (p.uid === user.uid ? { ...p, hasVideo: false, videoTrack: undefined } : p)),
            )
          }
          if (mediaType === 'audio') {
            setRemoteParticipants((prev) =>
              prev.map((p) => (p.uid === user.uid ? { ...p, hasAudio: false } : p)),
            )
          }
        })

        client.on('user-left', (user) => {
          setRemoteParticipants((prev) => prev.filter((p) => p.uid !== user.uid))
        })

        await client.join(joinInfo.app_id, joinInfo.channel, joinInfo.token, joinInfo.uid)
        if (cancelled) {
          await client.leave().catch(() => {})
          return
        }

        const [micTrack, camTrack] = await AgoraRTC.createMicrophoneAndCameraTracks()
        if (cancelled) {
          micTrack.close()
          camTrack.close()
          await client.leave().catch(() => {})
          return
        }
        micTrackRef.current = micTrack
        camTrackRef.current = camTrack
        setLocalDisplayTrack(camTrack)
        await client.publish([micTrack, camTrack])

        setPhase('connected')
      } catch (err) {
        if (!cancelled) {
          setPhase('error')
          setErrorMessage(extractErrorMessage(err))
        }
      }
    }

    connect()

    return () => {
      cancelled = true
      cleanupAndLeave()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetingId])

  function toggleMic() {
    const track = micTrackRef.current
    if (!track) return
    const next = !micEnabled
    track.setEnabled(next)
    setMicEnabled(next)
  }

  function toggleCamera() {
    const track = camTrackRef.current
    if (!track) return
    const next = !camEnabled
    track.setEnabled(next)
    setCamEnabled(next)
  }

  async function toggleScreenShare() {
    const client = clientRef.current
    if (!client) return

    try {
      if (!sharingScreen) {
        const result = await import('agora-rtc-sdk-ng').then(({ default: AgoraRTC }) =>
          AgoraRTC.createScreenVideoTrack({}, 'disable'),
        )
        screenVideoTrackRef.current = result
        if (camTrackRef.current) await client.unpublish([camTrackRef.current])
        await client.publish([result])
        setLocalDisplayTrack(result)
        setSharingScreen(true)

        // لو المستخدم أوقف المشاركة من شريط المتصفح نفسه (وليس زرّنا)
        result.on('track-ended', () => {
          stopScreenShare()
        })
      } else {
        await stopScreenShare()
      }
    } catch (err) {
      // رفض صلاحية اختيار الشاشة من المتصفح مثلًا — نادر ولا نعتبره خطأ فادح بالاتصال.
      setErrorMessage(extractErrorMessage(err))
    }
  }

  async function stopScreenShare() {
    const client = clientRef.current
    if (!client || !screenVideoTrackRef.current) return
    await client.unpublish([screenVideoTrackRef.current])
    screenVideoTrackRef.current.close()
    screenVideoTrackRef.current = null
    if (camTrackRef.current) {
      await client.publish([camTrackRef.current])
      setLocalDisplayTrack(camTrackRef.current)
    }
    setSharingScreen(false)
  }

  async function leave() {
    await cleanupAndLeave()
  }

  return {
    phase,
    errorMessage,
    micEnabled,
    camEnabled,
    sharingScreen,
    remoteParticipants,
    localAudioLevel,
    localDisplayTrack,
    toggleMic,
    toggleCamera,
    toggleScreenShare,
    leave,
  }
}
