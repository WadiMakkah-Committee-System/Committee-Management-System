import { useEffect, useRef, useState } from 'react'
import type { ICameraVideoTrack, ILocalVideoTrack, IRemoteVideoTrack } from 'agora-rtc-sdk-ng'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, Circle, Loader2, MicOff, MonitorUp, RotateCcw, Users, Video, Wifi, WifiOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { LiveRecordingState, LiveReaction } from '@/hooks/useMeetingRealtime'
import type { AgoraCall, NetworkQuality } from './useAgoraCall'
import { REACTION_EMOJI } from './reactions'

type AnyVideoTrack = ICameraVideoTrack | ILocalVideoTrack | IRemoteVideoTrack

/** يشغّل مسار فيديو Agora داخل عنصر (Agora تنشئ عنصر الفيديو بنفسها). */
function AgoraVideoView({ track, mirror, fit }: { track: AnyVideoTrack; mirror?: boolean; fit: 'cover' | 'contain' }) {
  const ref = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!ref.current) return
    track.play(ref.current, { fit, mirror: Boolean(mirror) })
    return () => {
      track.stop()
    }
  }, [track, mirror, fit])
  return <div ref={ref} className="absolute inset-0" />
}

/** بطاقة مشارك: فيديو أو أيقونة، الاسم، الكتم، "يتكلم الآن"، والتفاعلات. */
function Tile({
  name,
  track,
  mirror,
  muted,
  speaking,
  large,
  screen,
  onClick,
  reactions,
}: {
  name: string
  track: AnyVideoTrack | null
  mirror?: boolean
  muted: boolean
  speaking: boolean
  large: boolean
  screen?: boolean
  onClick: () => void
  reactions: LiveReaction[]
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'relative shrink-0 overflow-hidden rounded-lg bg-[#1b2338] text-right transition-all duration-300',
        speaking ? 'ring-2 ring-status-success-main' : 'ring-1 ring-white/10',
        large ? 'w-full flex-1' : 'aspect-video w-36 sm:w-44',
      )}
    >
      {track ? (
        <AgoraVideoView track={track} mirror={mirror && !screen} fit={large || screen ? 'contain' : 'cover'} />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center text-white/30">
          <Users size={large ? 40 : 20} />
        </div>
      )}
      <div className="pointer-events-none absolute bottom-8 right-3 flex flex-col-reverse items-end gap-1">
        <AnimatePresence>
          {reactions.map((r) => (
            <motion.span
              key={r.id}
              initial={{ opacity: 0, y: 12, scale: 0.6 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -24 }}
              transition={{ duration: 0.35 }}
              className={large ? 'text-4xl' : 'text-2xl'}
            >
              {REACTION_EMOJI[r.type]}
            </motion.span>
          ))}
        </AnimatePresence>
      </div>
      <div className="absolute inset-x-2 bottom-2 flex items-center justify-between gap-1">
        <span className="flex items-center gap-1 truncate rounded-xs bg-black/60 px-2 py-0.5 text-[11px] text-white">
          {screen && <MonitorUp size={11} />}
          {name}
        </span>
        {muted && (
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-black/60 text-white">
            <MicOff size={11} />
          </span>
        )}
      </div>
    </button>
  )
}

/** مؤشر جودة الاتصال: مخفي لما ممتاز، أصفر ضعيف، أحمر سيئ/منقطع. */
function NetworkBadge({ quality }: { quality: NetworkQuality }) {
  if (quality === 'good') return null
  const offline = quality === 'offline'
  return (
    <span
      className={cn(
        'flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold text-white',
        quality === 'poor' ? 'bg-warning' : 'bg-danger',
      )}
    >
      {offline ? <WifiOff size={11} /> : <Wifi size={11} />}
      {offline ? 'انقطع الإنترنت — جاري إعادة الاتصال' : quality === 'poor' ? 'اتصالك ضعيف' : 'اتصالك سيئ'}
    </span>
  )
}

/** مؤشر "جاري التسجيل" — يظهر عند كل الحضور (شفافية: الكل يعرف إن الاجتماع يتسجّل). */
export function RecordingBadge({ state }: { state: LiveRecordingState }) {
  if (!state.active) return null
  return (
    <span className="flex items-center gap-1.5 rounded-full bg-danger px-2.5 py-1 text-[11px] font-semibold text-white">
      <Circle size={8} className="animate-pulse fill-white" />
      جاري التسجيل
    </span>
  )
}

/**
 * الهدف (الرجوع لـAgora — قرار لاما 2026-11-04):
 * المساحة الرئيسية بغرفة الاجتماع: فيديو كل الأعضاء داخل المنصة.
 * - بطاقة كبيرة + شريط مصغّرات. مشاركة الشاشة تتصدّر تلقائيًا عند الكل.
 * - المعروض كبير يُطلب بالدقة العالية والمصغّرات بالمنخفضة (call.setFeatured).
 * - الحالات: جاري الاتصال، داخل، غادرت/انقطع (إعادة الانضمام).
 *
 * المدخلات: call (useAgoraCall)، localName، selfUserId، reactions/screenSharerIds/
 * recordingState (من القناة اللحظية).
 */
export function AgoraMeetingStage({
  call,
  localName,
  selfUserId,
  reactions,
  screenSharerIds,
  recordingState,
}: {
  call: AgoraCall
  localName: string
  selfUserId: string
  reactions: LiveReaction[]
  screenSharerIds: Set<string>
  recordingState: LiveRecordingState
}) {
  const [pinnedKey, setPinnedKey] = useState<string>('local')

  // مشاركة شاشة من عضو ثاني تتصدّر تلقائيًا؛ وإلا المثبّت (أو أنا).
  const remoteSharer = call.participants.find((p) => screenSharerIds.has(p.userId) && p.video)
  const pinnedExists = pinnedKey === 'local' || call.participants.some((p) => p.userId === pinnedKey)
  const featuredKey = remoteSharer?.userId ?? (call.screenSharing ? 'local' : pinnedExists ? pinnedKey : 'local')

  const setFeatured = call.setFeatured
  useEffect(() => {
    setFeatured(featuredKey === 'local' ? null : featuredKey)
  }, [featuredKey, setFeatured])

  if (call.phase === 'idle' || call.phase === 'joining') {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 rounded-lg bg-[#1b2338] p-6 text-center text-white/70">
        <Loader2 size={28} className="animate-spin" />
        <p className="text-sm">جاري الاتصال بالاجتماع...</p>
        <p className="max-w-sm text-xs text-white/40">لو طلب المتصفح إذن الكاميرا والمايك، اسمح له.</p>
      </div>
    )
  }

  if (call.phase === 'ended' || call.phase === 'error') {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-5 rounded-lg bg-[#1b2338] p-6 text-center">
        <span className="flex h-16 w-16 items-center justify-center rounded-full bg-brand-primary/15 text-brand-accent">
          <Video size={30} />
        </span>
        <div className="flex flex-col gap-1.5">
          <h2 className="text-lg font-semibold text-white">
            {call.phase === 'ended' ? 'غادرت الاجتماع' : 'تعذّر الاتصال بالاجتماع'}
          </h2>
          <p className="max-w-md text-sm text-white/60">تقدر ترجع للاجتماع في أي وقت ما دام ما انتهى.</p>
          {call.phase === 'error' && call.errorMessage && (
            <p className="max-w-md text-sm text-danger">{call.errorMessage}</p>
          )}
        </div>
        <button
          type="button"
          onClick={() => void call.start()}
          className="flex h-11 items-center gap-2 rounded-full bg-brand-primary px-6 text-sm font-semibold text-white transition-all hover:brightness-110 active:scale-95"
        >
          <RotateCcw size={17} />
          إعادة الانضمام
        </button>
      </div>
    )
  }

  const reactionsOf = (userId: string) => reactions.filter((r) => r.userId === userId)
  const tiles: { key: string; node: (large: boolean) => React.ReactNode }[] = [
    {
      key: 'local',
      node: (large) => (
        <Tile
          key="local"
          name={`${localName} (أنت)`}
          track={call.screenSharing || call.cameraOn ? call.localVideo : null}
          mirror
          screen={call.screenSharing}
          muted={call.micMuted}
          speaking={call.localSpeaking}
          large={large}
          onClick={() => setPinnedKey('local')}
          reactions={reactionsOf(selfUserId)}
        />
      ),
    },
    ...call.participants.map((p) => ({
      key: p.userId,
      node: (large: boolean) => (
        <Tile
          key={p.userId}
          name={p.name}
          track={p.video}
          screen={screenSharerIds.has(p.userId)}
          muted={!p.hasAudio}
          speaking={p.speaking}
          large={large}
          onClick={() => setPinnedKey(p.userId)}
          reactions={reactionsOf(p.userId)}
        />
      ),
    })),
  ]

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="relative flex min-h-0 flex-1">
        {tiles.find((t) => t.key === featuredKey)!.node(true)}
        <div className="absolute left-2 top-2 flex flex-wrap items-center gap-1.5">
          <span className="flex items-center gap-1 rounded-full bg-black/60 px-2.5 py-1 text-[11px] font-medium text-white">
            <Users size={11} />
            {call.participants.length + 1} في الاجتماع
          </span>
          <RecordingBadge state={recordingState} />
          <NetworkBadge quality={call.networkQuality} />
          {call.mediaIssues.map((issue) => (
            <span
              key={issue}
              className="flex items-center gap-1 rounded-full bg-warning px-2.5 py-1 text-[11px] font-semibold text-white"
            >
              <AlertTriangle size={11} /> {issue}
            </span>
          ))}
        </div>
      </div>
      {tiles.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {tiles.filter((t) => t.key !== featuredKey).map((t) => t.node(false))}
        </div>
      )}
    </div>
  )
}
