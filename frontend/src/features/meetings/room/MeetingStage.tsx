import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Hand, MicOff, Pin, Square, Users as UsersIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { RemoteParticipant } from './useAgoraConnection'

/**
 * منطقة عرض الفيديو — "متحدث مميَّز" كبير + شريط مصغّرات لبقية
 * المشاركين، بدل الشبكة المتساوية بالتصميم القديم. النقر على أي مصغّرة
 * يجعلها المميَّزة (Pin يدوي) — الإطار المضيء الأخضر على أي بطاقة (كبيرة
 * أو صغيرة) يعتمد على مستوى صوت Agora الحقيقي (audioLevel من
 * useAgoraConnection)، وليس تخمينًا. كل بطاقة تملك حاوية DOM خاصة بها لا
 * تتحرك أو تُعاد بناؤها أبدًا — فقط track.play() يُعاد استدعاؤه بحاوية
 * جديدة عند تغيّر مين هو المميَّز (Agora ينقل الالتصاق تلقائيًا).
 *
 * تعديل لاما 2026-09-06 (مطابقة الواجهة المرجعية): شارة "جاري التسجيل"
 * الحية أعلى يسار البطاقة المميَّزة (بدل ظهورها فقط داخل لوحة الذكاء
 * الاصطناعي الجانبية) + شارة "📌 المتحدث الآن" أعلى يمينها + سهما تمرير
 * لشريط المصغّرات.
 */

const SPEAKING_THRESHOLD = 30

interface LocalTileProps {
  displayTrack: Parameters<typeof playInto>[0]
  name: string
  micEnabled: boolean
  camEnabled: boolean
  sharingScreen: boolean
  audioLevel: number
  large: boolean
  raisedHand: boolean
  onClick: () => void
}

function playInto(
  track: { play: (el: HTMLElement) => void } | null | undefined,
  node: HTMLDivElement | null,
) {
  if (track && node) track.play(node)
}

function LocalTile({
  displayTrack,
  name,
  micEnabled,
  camEnabled,
  sharingScreen,
  audioLevel,
  large,
  raisedHand,
  onClick,
}: LocalTileProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    playInto(displayTrack, containerRef.current)
  }, [displayTrack])

  const speaking = audioLevel > SPEAKING_THRESHOLD && micEnabled

  return (
    <TileShell large={large} speaking={speaking} onClick={onClick}>
      <div ref={containerRef} className="h-full w-full [&>div]:!h-full [&>div]:!w-full" />
      {!camEnabled && !sharingScreen && (
        <div className="absolute inset-0 flex items-center justify-center text-white/30">
          <UsersIcon size={large ? 40 : 20} />
        </div>
      )}
      <TileFooter label={sharingScreen ? `${name} · تشارك الشاشة` : `${name} (أنتِ)`} muted={!micEnabled} />
      {raisedHand && <RaisedHandBadge large={large} />}
    </TileShell>
  )
}

function RemoteTile({
  participant,
  name,
  large,
  raisedHand,
  onClick,
}: {
  participant: RemoteParticipant
  name: string
  large: boolean
  raisedHand: boolean
  onClick: () => void
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    playInto(participant.videoTrack, containerRef.current)
  }, [participant.videoTrack])

  const speaking = participant.audioLevel > SPEAKING_THRESHOLD && participant.hasAudio

  return (
    <TileShell large={large} speaking={speaking} onClick={onClick}>
      <div ref={containerRef} className="h-full w-full [&>div]:!h-full [&>div]:!w-full" />
      {!participant.hasVideo && (
        <div className="absolute inset-0 flex items-center justify-center text-white/30">
          <UsersIcon size={large ? 40 : 20} />
        </div>
      )}
      <TileFooter label={name} muted={!participant.hasAudio} />
      {raisedHand && <RaisedHandBadge large={large} />}
    </TileShell>
  )
}

function TileShell({
  large,
  speaking,
  onClick,
  children,
}: {
  large: boolean
  speaking: boolean
  onClick: () => void
  children: React.ReactNode
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
      {children}
    </button>
  )
}

function TileFooter({ label, muted }: { label: string; muted: boolean }) {
  return (
    <div className="absolute inset-x-2 bottom-2 flex items-center justify-between gap-1">
      <span className="truncate rounded-xs bg-black/60 px-2 py-0.5 text-[11px] text-white">{label}</span>
      {muted && (
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-black/60 text-white">
          <MicOff size={11} />
        </span>
      )}
    </div>
  )
}

function RaisedHandBadge({ large }: { large: boolean }) {
  return (
    <span
      className={cn(
        'absolute right-2 top-2 flex items-center justify-center rounded-full bg-warning text-white shadow-sm',
        large ? 'h-8 w-8' : 'h-6 w-6',
      )}
    >
      <Hand size={large ? 16 : 12} />
    </span>
  )
}

export function MeetingStage({
  localName,
  localDisplayTrack,
  micEnabled,
  camEnabled,
  sharingScreen,
  localAudioLevel,
  remoteParticipants,
  participantNames,
  raisedHandUserIds,
  localUserId,
  isRecording,
  recordingElapsedSeconds,
  onStopRecording,
}: {
  localName: string
  localDisplayTrack: LocalTileProps['displayTrack']
  micEnabled: boolean
  camEnabled: boolean
  sharingScreen: boolean
  localAudioLevel: number
  remoteParticipants: RemoteParticipant[]
  /** اسم كل مشارك بعيد — مصدره meeting.participants (لا تحمله Agora). */
  participantNames: Map<string, string>
  raisedHandUserIds: Set<string>
  localUserId: string
  /** حالة التسجيل الحقيقية (useAudioRecorder بمستوى MeetingRoom.tsx) —
   * تُعرض كشارة حية أعلى يسار البطاقة المميَّزة، مطابقةً للمرجع. */
  isRecording: boolean
  recordingElapsedSeconds: number
  onStopRecording: () => void
}) {
  const [pinnedKey, setPinnedKey] = useState<string>('local')
  const filmstripRef = useRef<HTMLDivElement | null>(null)

  // المفتاح المميَّز الفعلي مُشتَق كل render (بلا useEffect/setState) — لو
  // المشارك المثبَّت (pinnedKey) غادر الاجتماع، نرجع تلقائيًا لعرض المستخدم
  // الحالي بدل بطاقة فارغة، دون الحاجة لمزامنة state إضافية مع حدث خارجي.
  const featuredKey =
    pinnedKey === 'local' || remoteParticipants.some((p) => String(p.uid) === pinnedKey)
      ? pinnedKey
      : 'local'

  const nameFor = (uid: string | number) => participantNames.get(String(uid)) ?? `مشارك #${uid}`

  const localTile = (
    <LocalTile
      key="local"
      displayTrack={localDisplayTrack}
      name={localName}
      micEnabled={micEnabled}
      camEnabled={camEnabled}
      sharingScreen={sharingScreen}
      audioLevel={localAudioLevel}
      large={featuredKey === 'local'}
      raisedHand={raisedHandUserIds.has(localUserId)}
      onClick={() => setPinnedKey('local')}
    />
  )

  const remoteTiles = remoteParticipants.map((participant) => (
    <RemoteTile
      key={participant.uid}
      participant={participant}
      name={nameFor(participant.uid)}
      large={featuredKey === String(participant.uid)}
      raisedHand={raisedHandUserIds.has(String(participant.uid))}
      onClick={() => setPinnedKey(String(participant.uid))}
    />
  ))

  const allTiles = [localTile, ...remoteTiles]
  const featuredTile = allTiles.find((tile) => tile.key === featuredKey) ?? localTile
  const filmstripTiles = allTiles.filter((tile) => tile.key !== featuredKey)

  const recMinutes = String(Math.floor(recordingElapsedSeconds / 60)).padStart(2, '0')
  const recSeconds = String(recordingElapsedSeconds % 60).padStart(2, '0')

  function scrollFilmstrip(direction: 1 | -1) {
    filmstripRef.current?.scrollBy({ left: direction * 240, behavior: 'smooth' })
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="relative flex min-h-0 flex-1">
        {featuredTile}

        {isRecording && (
          <div className="absolute right-2 top-2 flex items-center gap-1.5 rounded-full bg-black/60 py-1 pl-1 pr-2.5 text-[11px] font-medium text-white">
            <span className="h-2 w-2 animate-live-dot-pulse rounded-full bg-danger" />
            <span className="font-mono">
              {recMinutes}:{recSeconds}
            </span>
            <span>جاري التسجيل</span>
            <button
              type="button"
              onClick={onStopRecording}
              aria-label="إيقاف التسجيل"
              title="إيقاف التسجيل"
              className="flex h-5 w-5 items-center justify-center rounded-full text-white/70 transition-colors hover:bg-white/15 hover:text-white"
            >
              <Square size={10} />
            </button>
          </div>
        )}

        <div className="absolute left-2 top-2 flex items-center gap-1 rounded-full bg-black/60 px-2.5 py-1 text-[11px] font-medium text-white">
          <Pin size={11} />
          المتحدث الآن
        </div>
      </div>

      {filmstripTiles.length > 0 && (
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => scrollFilmstrip(-1)}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-white/60 transition-colors hover:bg-white/10 hover:text-white"
            aria-label="السابق"
          >
            <ChevronRight size={15} />
          </button>
          <div ref={filmstripRef} className="flex flex-1 gap-2 overflow-x-auto scroll-smooth pb-1">
            {filmstripTiles}
          </div>
          <button
            type="button"
            onClick={() => scrollFilmstrip(1)}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-white/60 transition-colors hover:bg-white/10 hover:text-white"
            aria-label="التالي"
          >
            <ChevronLeft size={15} />
          </button>
        </div>
      )}
    </div>
  )
}
