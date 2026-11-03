import { useState } from 'react'
import { Hand, Mic, MicOff, Megaphone } from 'lucide-react'
import { Avatar } from '@/components/ui/Avatar'
import { SearchInput } from '@/components/ui/SearchInput'
import { cn } from '@/lib/utils'
import type { CommitteeMemberUser } from '@/types'
import type { RaisedHand } from '@/hooks/useMeetingRealtime'

export function ParticipantsPanel({
  participants,
  onlineUserIds,
  raisedHandUserIds,
  currentUserId,
  speakerQueue = [],
  canGiveFloor = false,
  onGiveFloor,
}: {
  participants: CommitteeMemberUser[]
  onlineUserIds: Set<string>
  raisedHandUserIds: Set<string>
  currentUserId: string
  /** طابور المتحدثين (قرار لاما 2026-11-03): الأيدي المرفوعة بترتيب الرفع. */
  speakerQueue?: RaisedHand[]
  /** رئيس اللجنة: زر "أعطه الكلمة" لكل واحد بالطابور. */
  canGiveFloor?: boolean
  onGiveFloor?: (userId: string) => void
}) {
  const [query, setQuery] = useState('')

  const filtered = participants.filter((p) =>
    `${p.first_name} ${p.middle_name} ${p.last_name}`.toLowerCase().includes(query.toLowerCase()),
  )

  // المشاركون اللي رافعين أيديهم يطلعون أول القائمة — يسهّل على رئيس اللجنة يشوفهم بسرعة.
  const sorted = [...filtered].sort((a, b) => {
    const aRaised = raisedHandUserIds.has(a.user_id) ? 0 : 1
    const bRaised = raisedHandUserIds.has(b.user_id) ? 0 : 1
    return aRaised - bRaised
  })

  return (
    <div className="flex h-full flex-col">
      {speakerQueue.length > 0 && (
        <div className="border-b border-border-default bg-warning-bg/60 p-3">
          <p className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold text-warning">
            <Hand size={13} /> طابور المتحدثين ({speakerQueue.length})
          </p>
          <ol className="flex flex-col gap-1.5">
            {speakerQueue.map((hand, index) => (
              <li key={hand.userId} className="flex items-center gap-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-warning text-[10px] font-bold text-white">
                  {index + 1}
                </span>
                <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-text-primary">
                  {hand.fullName}
                  {hand.userId === currentUserId && <span className="font-normal text-text-muted"> (أنت)</span>}
                </span>
                {canGiveFloor && onGiveFloor && (
                  <button
                    type="button"
                    onClick={() => onGiveFloor(hand.userId)}
                    className="flex shrink-0 items-center gap-1 rounded-full bg-brand-primary px-2 py-1 text-[10px] font-semibold text-white transition-all hover:brightness-110"
                  >
                    <Megaphone size={11} /> أعطه الكلمة
                  </button>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
      <div className="border-b border-border-default p-3">
        <SearchInput value={query} onChange={setQuery} placeholder="البحث عن مشارك..." />
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {sorted.map((participant) => {
          const online = onlineUserIds.has(participant.user_id)
          const raised = raisedHandUserIds.has(participant.user_id)
          const isMe = participant.user_id === currentUserId
          return (
            <div
              key={participant.user_id}
              className="flex items-center gap-2.5 rounded-md px-2 py-2 transition-colors hover:bg-bg-elevated"
            >
              <div className="relative shrink-0">
                <Avatar firstName={participant.first_name} lastName={participant.last_name} size={34} />
                <span
                  className={cn(
                    'absolute -bottom-0.5 -left-0.5 h-2.5 w-2.5 rounded-full border-2 border-bg-surface',
                    online ? 'bg-status-success-main' : 'bg-text-muted',
                  )}
                />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-semibold text-text-primary">
                  {participant.first_name} {participant.last_name}
                  {isMe && <span className="font-normal text-text-muted"> (أنت)</span>}
                </p>
                <p className="text-[11px] text-text-muted">{online ? 'متصل الآن' : 'غير متصل'}</p>
              </div>
              <div className="flex shrink-0 items-center gap-1.5 text-text-muted">
                {raised && <Hand size={14} className="text-warning" />}
                {online ? <Mic size={14} /> : <MicOff size={14} className="opacity-40" />}
              </div>
            </div>
          )
        })}
        {sorted.length === 0 && (
          <p className="py-8 text-center text-xs text-text-muted">لا يوجد مشاركون مطابقون</p>
        )}
      </div>
    </div>
  )
}
