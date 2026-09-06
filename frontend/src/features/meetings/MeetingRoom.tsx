import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion } from 'framer-motion'
import {
  Loader2,
  Mic,
  MicOff,
  MonitorUp,
  PhoneOff,
  ScreenShareOff,
  Users as UsersIcon,
  Video,
  VideoOff,
  X,
} from 'lucide-react'
import type {
  IAgoraRTCClient,
  IAgoraRTCRemoteUser,
  ICameraVideoTrack,
  ILocalVideoTrack,
  IMicrophoneAudioTrack,
} from 'agora-rtc-sdk-ng'
import { useJoinMeeting, useLeaveMeeting } from '@/hooks/useMeetings'
import { cn, extractErrorMessage } from '@/lib/utils'

/**
 * غرفة الفيديو الفعلية للاجتماع — Agora RTC Web SDK. تُفتح فوق الصفحة
 * كلها (Portal لـdocument.body، z-[60]) من MeetingDetailPage.tsx عند نقر
 * زر "دخول الاجتماع" النابض (يظهر فقط بعد وصول موعد الاجتماع، راجعي
 * isMeetingLive هناك).
 *
 * تحميل مكتبة agora-rtc-sdk-ng ديناميكيًا (import() داخل useEffect) بدل
 * الاستيراد الثابت أعلى الملف — Code-splitting: أغلب من يفتح المشروع لا
 * يدخل اجتماع فيديو كل مرة، فلا داعي لتحميل مكتبة Agora (ثقيلة نسبيًا)
 * ضمن الحزمة الرئيسية. الاستيرادات بالأعلى type-only (import type) فقط،
 * تُحذف كليًا وقت البناء ولا تُدرَج بأي Chunk.
 *
 * بيانات الدخول (token) تأتي من POST /meetings/{id}/join بالباك-إند
 * (meeting_service.join_meeting + agora_client.generate_rtc_token) —
 * قصيرة العمر (AGORA_TOKEN_TTL_SECONDS)، ولا يصل AGORA_APP_CERTIFICATE
 * للفرونت أبدًا (نفس مبدأ SUPABASE_SERVICE_ROLE_KEY، راجعي رأس
 * db/migrations/0022_meetings_agora_video.sql).
 */

type ConnectionPhase = 'connecting' | 'connected' | 'error'

interface RemoteParticipant {
  uid: string | number
  hasVideo: boolean
  hasAudio: boolean
  videoTrack: IAgoraRTCRemoteUser['videoTrack']
}

function ControlButton({
  onClick,
  active,
  danger,
  label,
  children,
}: {
  onClick: () => void
  active?: boolean
  danger?: boolean
  label: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={cn(
        'flex h-12 w-12 items-center justify-center rounded-full transition-all active:scale-95',
        danger
          ? 'bg-danger text-white hover:brightness-95'
          : active
            ? 'bg-white/15 text-white hover:bg-white/25'
            : 'bg-danger/90 text-white hover:bg-danger',
      )}
    >
      {children}
    </button>
  )
}

function RemoteVideoTile({ participant }: { participant: RemoteParticipant }) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const node = containerRef.current
    if (participant.videoTrack && node) {
      participant.videoTrack.play(node)
    }
    return () => {
      participant.videoTrack?.stop()
    }
  }, [participant.videoTrack])

  return (
    <div className="relative aspect-video overflow-hidden rounded-md bg-[#1c1f26]">
      <div ref={containerRef} className="h-full w-full [&>div]:!h-full [&>div]:!w-full" />
      {!participant.hasVideo && (
        <div className="absolute inset-0 flex items-center justify-center text-white/40">
          <UsersIcon size={28} />
        </div>
      )}
      <div className="absolute inset-x-2 bottom-2 flex items-center justify-between">
        <span className="rounded-xs bg-black/60 px-2 py-0.5 text-[11px] text-white">
          مشارك #{participant.uid}
        </span>
        {!participant.hasAudio && (
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-black/60 text-white">
            <MicOff size={11} />
          </span>
        )}
      </div>
    </div>
  )
}

export function MeetingRoom({
  meetingId,
  meetingTitle,
  onClose,
}: {
  meetingId: string
  meetingTitle: string
  onClose: () => void
}) {
  const joinMutation = useJoinMeeting()
  const leaveMutation = useLeaveMeeting()

  const [phase, setPhase] = useState<ConnectionPhase>('connecting')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [micEnabled, setMicEnabled] = useState(true)
  const [camEnabled, setCamEnabled] = useState(true)
  const [sharingScreen, setSharingScreen] = useState(false)
  const [remoteParticipants, setRemoteParticipants] = useState<RemoteParticipant[]>([])

  const clientRef = useRef<IAgoraRTCClient | null>(null)
  const micTrackRef = useRef<IMicrophoneAudioTrack | null>(null)
  const camTrackRef = useRef<ICameraVideoTrack | null>(null)
  const screenVideoTrackRef = useRef<ILocalVideoTrack | null>(null)
  const agoraUidRef = useRef<number | null>(null)
  const localVideoRef = useRef<HTMLDivElement | null>(null)
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

        client.on('user-published', async (user, mediaType) => {
          await client.subscribe(user, mediaType)
          if (mediaType === 'video') {
            setRemoteParticipants((prev) => {
              const others = prev.filter((p) => p.uid !== user.uid)
              return [...others, { uid: user.uid, hasVideo: true, hasAudio: !!user.hasAudio, videoTrack: user.videoTrack }]
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
        if (localVideoRef.current) camTrack.play(localVideoRef.current)
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
        if (localVideoRef.current) result.play(localVideoRef.current)
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
      if (localVideoRef.current) camTrackRef.current.play(localVideoRef.current)
    }
    setSharingScreen(false)
  }

  async function handleLeaveClick() {
    await cleanupAndLeave()
    onClose()
  }

  const gridParticipantsCount = remoteParticipants.length + 1
  const gridClass =
    gridParticipantsCount <= 1
      ? 'grid-cols-1'
      : gridParticipantsCount <= 4
        ? 'grid-cols-2'
        : 'grid-cols-3'

  return createPortal(
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.18 }}
      className="fixed inset-0 z-[60] flex flex-col bg-[#111318]"
      dir="rtl"
    >
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
        <div className="flex items-center gap-2 text-white">
          <Video size={16} />
          <p className="truncate text-sm font-semibold">{meetingTitle}</p>
          {phase === 'connected' && (
            <span className="flex items-center gap-1 rounded-xs bg-success/15 px-2 py-0.5 text-[11px] font-semibold text-success">
              <span className="h-1.5 w-1.5 rounded-full bg-success animate-live-dot-pulse" />
              جارٍ الآن
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={handleLeaveClick}
          aria-label="إغلاق"
          className="flex h-8 w-8 items-center justify-center rounded-full text-white/60 transition-colors hover:bg-white/10 hover:text-white"
        >
          <X size={18} />
        </button>
      </div>

      <div className="flex flex-1 flex-col items-center justify-center gap-4 overflow-auto p-4">
        {phase === 'connecting' && (
          <div className="flex flex-col items-center gap-3 text-white/70">
            <Loader2 size={28} className="animate-spin" />
            <p className="text-sm">جاري الاتصال بالاجتماع...</p>
          </div>
        )}

        {phase === 'error' && (
          <div className="flex flex-col items-center gap-3 text-center">
            <p className="max-w-sm text-sm text-danger">{errorMessage ?? 'تعذّر الاتصال بالاجتماع.'}</p>
            <button
              type="button"
              onClick={onClose}
              className="rounded-sm bg-white/10 px-4 py-2 text-sm text-white hover:bg-white/15"
            >
              إغلاق
            </button>
          </div>
        )}

        {phase === 'connected' && (
          <div className={cn('grid w-full max-w-5xl gap-3', gridClass)}>
            <div className="relative aspect-video overflow-hidden rounded-md bg-[#1c1f26]">
              <div ref={localVideoRef} className="h-full w-full [&>div]:!h-full [&>div]:!w-full" />
              {!camEnabled && !sharingScreen && (
                <div className="absolute inset-0 flex items-center justify-center text-white/40">
                  <UsersIcon size={28} />
                </div>
              )}
              <span className="absolute bottom-2 right-2 rounded-xs bg-black/60 px-2 py-0.5 text-[11px] text-white">
                أنتِ
              </span>
              {!micEnabled && (
                <span className="absolute top-2 right-2 flex h-5 w-5 items-center justify-center rounded-full bg-black/60 text-white">
                  <MicOff size={11} />
                </span>
              )}
            </div>
            {remoteParticipants.map((participant) => (
              <RemoteVideoTile key={participant.uid} participant={participant} />
            ))}
          </div>
        )}
      </div>

      {phase === 'connected' && (
        <div className="flex items-center justify-center gap-3 border-t border-white/10 px-4 py-4">
          <ControlButton onClick={toggleMic} active={micEnabled} label={micEnabled ? 'كتم الصوت' : 'تشغيل الصوت'}>
            {micEnabled ? <Mic size={18} /> : <MicOff size={18} />}
          </ControlButton>
          <ControlButton onClick={toggleCamera} active={camEnabled} label={camEnabled ? 'إيقاف الكاميرا' : 'تشغيل الكاميرا'}>
            {camEnabled ? <Video size={18} /> : <VideoOff size={18} />}
          </ControlButton>
          <ControlButton
            onClick={toggleScreenShare}
            active={sharingScreen}
            label={sharingScreen ? 'إيقاف مشاركة الشاشة' : 'مشاركة الشاشة'}
          >
            {sharingScreen ? <ScreenShareOff size={18} /> : <MonitorUp size={18} />}
          </ControlButton>
          <ControlButton onClick={handleLeaveClick} danger label="مغادرة الاجتماع">
            <PhoneOff size={18} />
          </ControlButton>
        </div>
      )}
    </motion.div>,
    document.body,
  )
}
