import { useEffect, useRef, useState } from 'react'
import type { LocalVideoStream, RemoteVideoStream } from '@azure/communication-calling'
import { AnimatePresence, motion } from 'framer-motion'
import {
  ExternalLink,
  Hourglass,
  Info,
  Loader2,
  LogIn,
  MicOff,
  MonitorUp,
  RotateCcw,
  UserCheck,
  Users,
  Video,
  Wifi,
  WifiOff,
  AlertTriangle,
} from 'lucide-react'
import { useTeamsJoinUrl } from '@/hooks/useMeetings'
import { useToast } from '@/components/ui/Toast'
import { cn, extractErrorMessage } from '@/lib/utils'
import type { Meeting } from '@/types'
import type { EmbeddedParticipant, FloatingReaction, NetworkQuality, TeamsEmbeddedCall } from './useTeamsEmbeddedCall'
import { REACTION_EMOJI } from './reactions'

/**
 * يعرض مقطع فيديو (محلي أو بعيد) من Azure Communication Services داخل عنصر DOM.
 * VideoStreamRenderer يُنشئ عنصر الفيديو بنفسه، فنُلحقه بالـdiv ونحرّره عند
 * التغيير/الإزالة (dispose) لتفادي تسريب الذاكرة. المكتبة تُحمَّل ديناميكيًا.
 */
function StreamView({ stream, mirror }: { stream: LocalVideoStream | RemoteVideoStream; mirror?: boolean }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    let disposed = false
    let dispose: (() => void) | null = null
    void (async () => {
      const sdk = await import('@azure/communication-calling')
      if (disposed) return
      const renderer = new sdk.VideoStreamRenderer(stream)
      const view = await renderer.createView({ scalingMode: 'Fit', isMirrored: !!mirror })
      if (disposed) {
        renderer.dispose()
        return
      }
      containerRef.current?.replaceChildren(view.target)
      dispose = () => renderer.dispose()
    })()
    return () => {
      disposed = true
      dispose?.()
    }
  }, [stream, mirror])
  return <div ref={containerRef} className="h-full w-full [&>div]:!h-full [&>div]:!w-full" />
}

/** بطاقة مشارك (بنفس شكل بطاقات غرفة Agora السابقة): فيديو أو أيقونة، اسم، ومؤشر كتم/تحدّث. */
function Tile({
  name,
  stream,
  mirror,
  muted,
  speaking,
  large,
  onClick,
  reactions = [],
}: {
  /** تفاعلات صاحب البطاقة الحالية — تطير فوق الفيديو لثواني. */
  reactions?: FloatingReaction[]
  name: string
  stream: LocalVideoStream | RemoteVideoStream | null
  mirror?: boolean
  muted: boolean
  speaking: boolean
  large: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'relative shrink-0 overflow-hidden rounded-lg bg-[#1b2338] text-right transition-all duration-300',
        speaking ? 'ring-2 ring-status-success-main' : 'ring-1 ring-white/10',
        large ? 'aspect-video w-full flex-1' : 'aspect-video w-36 sm:w-44',
      )}
    >
      {stream ? (
        <StreamView stream={stream} mirror={mirror} />
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
        <span className="truncate rounded-xs bg-black/60 px-2 py-0.5 text-[11px] text-white">{name}</span>
        {muted && (
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-black/60 text-white">
            <MicOff size={11} />
          </span>
        )}
      </div>
    </button>
  )
}

/** زر "فتح في تيمز" الاحتياطي — يطلب الرابط عند الضغط (نفس TeamsMeetingStage). */
function OpenInTeamsButton({ meetingId, subtle }: { meetingId: string; subtle?: boolean }) {
  const joinMutation = useTeamsJoinUrl()
  const { showToast } = useToast()
  async function handleOpen() {
    const tab = window.open('', '_blank')
    try {
      const { join_url } = await joinMutation.mutateAsync(meetingId)
      if (tab) {
        tab.opener = null
        tab.location.href = join_url
      } else {
        window.location.assign(join_url)
      }
    } catch (err) {
      tab?.close()
      showToast(extractErrorMessage(err), 'error')
    }
  }
  return (
    <button
      type="button"
      onClick={handleOpen}
      disabled={joinMutation.isPending}
      className={cn(
        'flex items-center gap-1.5 text-xs font-medium transition-colors disabled:opacity-60',
        subtle ? 'text-white/50 hover:text-white' : 'rounded-full bg-white/10 px-4 py-2 text-white hover:bg-white/20',
      )}
    >
      <ExternalLink size={13} />
      فتح في تطبيق تيمز
    </button>
  )
}

/**
 * شريط المنتظرين بالـLobby — يظهر فقط لمن دخل بحساب Microsoft (المنظّم/الرئيس
 * يقدر يقبلهم من داخل المنصة بدل تطبيق تيمز). فشل القبول = لا يملك الصلاحية.
 */
function LobbyBar({ call }: { call: TeamsEmbeddedCall }) {
  const { showToast } = useToast()
  const [busy, setBusy] = useState(false)
  if (call.identity !== 'teams_user' || call.lobbyParticipants.length === 0) return null

  async function handleAdmit(key?: string) {
    setBusy(true)
    try {
      await call.admit(key)
    } catch {
      showToast('لا تملك صلاحية السماح بالدخول — يسمح بها منظّم الاجتماع أو رئيس اللجنة', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-warning/30 bg-warning-bg px-3 py-2 text-[13px] text-warning">
      <Hourglass size={14} className="shrink-0" />
      <span className="font-semibold">بانتظار السماح بالدخول ({call.lobbyParticipants.length}):</span>
      {call.lobbyParticipants.map((p) => (
        <button
          key={p.key}
          type="button"
          disabled={busy}
          onClick={() => void handleAdmit(p.key)}
          className="flex items-center gap-1 rounded-full bg-white/10 px-2.5 py-1 text-white transition-colors hover:bg-white/20 disabled:opacity-60"
        >
          <UserCheck size={12} />
          {p.name}
        </button>
      ))}
      {call.lobbyParticipants.length > 1 && (
        <button
          type="button"
          disabled={busy}
          onClick={() => void handleAdmit()}
          className="mr-auto rounded-full bg-brand-primary px-3 py-1 font-semibold text-white transition-all hover:brightness-110 disabled:opacity-60"
        >
          السماح للكل
        </button>
      )}
    </div>
  )
}

/**
 * مؤشر جودة الاتصال (قرار لاما 2026-11-03): مخفي لما الاتصال ممتاز، أصفر
 * "اتصالك ضعيف"، أحمر "اتصالك سيئ"، و"انقطع الإنترنت" — قبل ما ينقطع فعليًا.
 */
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
      {offline ? 'انقطع الإنترنت' : quality === 'poor' ? 'اتصالك ضعيف' : 'اتصالك سيئ'}
    </span>
  )
}

/** تنبيه رئيس اللجنة بخصوص التسجيل/التفريغ (ما يقدر أحد يشغلهما من داخل المنصة). */
function RecordingHint() {
  return (
    <div className="mt-2 flex max-w-md items-start gap-2 rounded-md border border-warning/30 bg-warning-bg px-3 py-2 text-right text-[12px] text-warning">
      <Info size={14} className="mt-0.5 shrink-0" />
      <span>
        بصفتك رئيس اللجنة: التسجيل يبدأ <strong>تلقائيًا</strong> مع بداية الاجتماع. لو ما ظهر تنبيه التفريغ
        (Transcription)، شغّليه من <strong>تطبيق تيمز</strong> — بدونه لا يمكن توليد مسودة المحضر.
      </span>
    </div>
  )
}

/**
 * الهدف (تجربة poc/acs-teams-embed — 2026-11-02):
 * المساحة الرئيسية بغرفة الاجتماع: فيديو اجتماع Microsoft Teams **داخل المنصة**
 * (نفس مكان فيديو Agora سابقًا) عبر Azure Communication Services.
 *
 * الدخول: من دخل المنصة بحساب Microsoft حق الشركة يدخل الاجتماع بهويته
 * تلقائيًا (باسمه، بدون انتظار، والمنظّم/الرئيس يقبل الضيوف من شريط LobbyBar)
 * — بدون أي نافذة. ومن دخل بكلمة المرور يدخل كضيف وينتظر حتى يُقبل.
 *
 * الحالات: جارٍ الاتصال (يبدأ تلقائيًا)، يحتاج تأكيد Microsoft، بانتظار
 * السماح بالدخول (Lobby)، داخل الاجتماع (بطاقة مميزة + شريط مصغّرات، ومشاركة
 * الشاشة تُعرض كبطاقة مميزة تلقائيًا)، انتهى، أو خطأ.
 *
 * المدخلات: meeting، call (من useTeamsEmbeddedCall بمستوى MeetingRoom)، localName،
 * canRecord (لعرض تنبيه التسجيل لرئيس اللجنة).
 */
export function EmbeddedTeamsStage({
  meeting,
  call,
  localName,
  canRecord,
}: {
  meeting: Meeting
  call: TeamsEmbeddedCall
  localName: string
  canRecord: boolean
}) {
  const [pinnedKey, setPinnedKey] = useState<string>('local')

  // تحديث لاما 2026-11-03: الدخول يبدأ تلقائيًا من MeetingRoom (call.start) أول ما
  // تفتح الغرفة — فالحالات هنا: جاري الاتصال، أو يحتاج ضغطة (انتهت جلسة
  // Microsoft)، أو انقطع/غادر (إعادة الانضمام). لا يوجد زر "انضمام" ثاني.
  if (call.phase === 'idle' || call.phase === 'joining' || call.phase === 'lobby') {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 rounded-lg bg-[#1b2338] p-6 text-center text-white/70">
        {call.phase === 'lobby' ? (
          <>
            <Hourglass size={28} className="text-warning" />
            <p className="text-sm text-white">في انتظار السماح بدخولك</p>
            <p className="max-w-sm text-xs text-white/50">يسمح لك منظّم الاجتماع أو رئيس اللجنة بالدخول.</p>
          </>
        ) : (
          <>
            <Loader2 size={28} className="animate-spin" />
            <p className="text-sm">جاري الاتصال بالاجتماع...</p>
            <p className="max-w-sm text-xs text-white/40">لو طلب المتصفح إذن الكاميرا والمايك، اسمح له.</p>
          </>
        )}
        {canRecord && <RecordingHint />}
      </div>
    )
  }

  if (call.phase === 'needs_signin' || call.phase === 'ended' || call.phase === 'error') {
    const needsSignIn = call.phase === 'needs_signin'
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-5 rounded-lg bg-[#1b2338] p-6 text-center">
        <span className="flex h-16 w-16 items-center justify-center rounded-full bg-brand-primary/15 text-brand-accent">
          {needsSignIn ? <LogIn size={30} /> : <Video size={30} />}
        </span>
        <div className="flex flex-col gap-1.5">
          <h2 className="text-lg font-semibold text-white">
            {needsSignIn ? 'تأكيد حساب Microsoft' : call.phase === 'ended' ? 'غادرت الاجتماع' : 'انقطع الاتصال بالاجتماع'}
          </h2>
          <p className="max-w-md text-sm text-white/60">
            {needsSignIn
              ? 'انتهت جلسة حسابك في Microsoft على هذا الجهاز — اضغط للمتابعة وبتدخل باسمك مباشرة.'
              : 'تقدر ترجع للاجتماع في أي وقت ما دام ما انتهى.'}
          </p>
          {call.phase === 'error' && call.errorMessage && (
            <p className="max-w-md text-sm text-danger">{call.errorMessage}</p>
          )}
        </div>
        <button
          type="button"
          onClick={() => void call.start(true)}
          className="flex h-11 items-center gap-2 rounded-full bg-brand-primary px-6 text-sm font-semibold text-white transition-all hover:brightness-110 active:scale-95"
        >
          {needsSignIn ? <LogIn size={17} /> : <RotateCcw size={17} />}
          {needsSignIn ? 'المتابعة بحساب Microsoft' : 'إعادة الانضمام'}
        </button>
        <OpenInTeamsButton meetingId={meeting.meeting_id} subtle />
      </div>
    )
  }

  // داخل الاجتماع: مشاركة الشاشة (إن وُجدت) تتصدّر تلقائيًا، وإلا البطاقة المثبّتة.
  const sharer = call.participants.find((p) => p.screen)
  const tiles: { key: string; node: (large: boolean) => React.ReactNode }[] = [
    {
      key: 'local',
      node: (large) => (
        <Tile
          key="local"
          name={`${localName} (أنت)`}
          stream={call.cameraOn ? call.localVideo : null}
          mirror
          muted={call.micMuted}
          speaking={false}
          large={large}
          onClick={() => setPinnedKey('local')}
          reactions={call.reactions.filter((r) => r.key === 'local')}
        />
      ),
    },
    ...call.participants.map((p: EmbeddedParticipant) => ({
      key: p.key,
      node: (large: boolean) => (
        <Tile
          key={p.key}
          name={p.name}
          stream={p.video}
          muted={p.isMuted}
          speaking={p.isSpeaking}
          large={large}
          onClick={() => setPinnedKey(p.key)}
          reactions={call.reactions.filter((r) => r.key === p.key)}
        />
      ),
    })),
  ]
  const featuredKey = tiles.some((t) => t.key === pinnedKey) ? pinnedKey : 'local'

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <LobbyBar call={call} />
      <div className="relative flex min-h-0 flex-1">
        {sharer?.screen ? (
          <div className="relative flex-1 overflow-hidden rounded-lg bg-black ring-1 ring-white/10">
            <StreamView stream={sharer.screen} />
            <span className="absolute right-2 top-2 flex items-center gap-1 rounded-full bg-black/60 px-2.5 py-1 text-[11px] text-white">
              <MonitorUp size={11} />
              {sharer.name} يشارك الشاشة
            </span>
          </div>
        ) : (
          tiles.find((t) => t.key === featuredKey)!.node(true)
        )}
        <div className="absolute left-2 top-2 flex flex-wrap items-center gap-1.5">
          <span className="flex items-center gap-1 rounded-full bg-black/60 px-2.5 py-1 text-[11px] font-medium text-white">
            <Users size={11} />
            {call.participants.length + 1} في الاجتماع
          </span>
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
      <div className="flex gap-2 overflow-x-auto pb-1">
        {tiles.filter((t) => sharer?.screen || t.key !== featuredKey).map((t) => t.node(false))}
      </div>
      <div className="flex justify-center">
        <OpenInTeamsButton meetingId={meeting.meeting_id} subtle />
      </div>
    </div>
  )
}
