import { useEffect, useMemo, useRef, useState } from 'react'
import { Send } from 'lucide-react'
import { Avatar } from '@/components/ui/Avatar'
import { Spinner } from '@/components/ui/Spinner'
import { useMeetingChatHistory } from '@/hooks/useMeetings'
import { formatTime } from '@/lib/utils'
import type { MeetingChatMessage } from '@/types'
import type { MeetingConnectionStatus } from '@/hooks/useMeetingRealtime'

/** يدمج تاريخ المحادثة (REST، مرة واحدة) مع الرسائل اللحظية (WebSocket)، بإزالة التكرار حسب message_id. */
function mergeMessages(history: MeetingChatMessage[], live: MeetingChatMessage[]): MeetingChatMessage[] {
  const seen = new Set<string>()
  const merged: MeetingChatMessage[] = []
  for (const message of [...history, ...live]) {
    if (seen.has(message.message_id)) continue
    seen.add(message.message_id)
    merged.push(message)
  }
  return merged
}

export function ChatPanel({
  meetingId,
  liveMessages,
  currentUserId,
  onSend,
  connectionStatus,
}: {
  meetingId: string
  liveMessages: MeetingChatMessage[]
  currentUserId: string
  onSend: (body: string) => void
  /** تعديل لاما 2026-09-06: "لما اكتب بالدردشة ما تظهر ولا تحفظ" — بلا أي
   * مؤشر مرئي سابقًا لحالة اتصال WebSocket، فرسالة لم تُرسَل فعليًا (الاتصال
   * ما زال يحاول الاتصال، أو انقطع) كانت تبدو تمامًا كصمت الواجهة العادي.
   * هذا المؤشر يفضح حالة الاتصال الحقيقية بدل الصمت. */
  connectionStatus: MeetingConnectionStatus
}) {
  const historyQuery = useMeetingChatHistory(meetingId)
  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLDivElement | null>(null)

  const messages = useMemo(
    () => mergeMessages(historyQuery.data ?? [], liveMessages),
    [historyQuery.data, liveMessages],
  )

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
  }, [messages.length])

  function handleSend() {
    const trimmed = draft.trim()
    if (!trimmed) return
    onSend(trimmed)
    setDraft('')
  }

  return (
    <div className="flex h-full flex-col">
      {connectionStatus !== 'open' && (
        <div className="flex items-center gap-1.5 border-b border-border-default bg-warning-bg px-3 py-1.5 text-[11px] font-medium text-warning">
          <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-warning" />
          {connectionStatus === 'connecting'
            ? 'جاري الاتصال بقناة المحادثة...'
            : 'انقطع الاتصال بقناة المحادثة — تتم إعادة المحاولة تلقائيًا...'}
        </div>
      )}
      <div ref={listRef} className="flex-1 overflow-y-auto p-3">
        {historyQuery.isLoading ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : messages.length === 0 ? (
          <p className="py-8 text-center text-xs text-text-muted">لا توجد رسائل بعد — ابدئي المحادثة</p>
        ) : (
          <div className="flex flex-col gap-3">
            {messages.map((message) => {
              const isMe = message.sender.user_id === currentUserId
              return (
                <div key={message.message_id} className={`flex items-start gap-2 ${isMe ? 'flex-row-reverse' : ''}`}>
                  <Avatar
                    firstName={message.sender.first_name}
                    lastName={message.sender.last_name}
                    size={26}
                  />
                  <div className={`flex max-w-[78%] flex-col gap-0.5 ${isMe ? 'items-end' : 'items-start'}`}>
                    {!isMe && (
                      <span className="text-[10px] text-text-muted">
                        {message.sender.first_name} {message.sender.last_name}
                      </span>
                    )}
                    <div
                      className={
                        isMe
                          ? 'rounded-[10px_10px_3px_10px] bg-brand-primary px-2.5 py-1.5 text-[12px] text-white'
                          : 'rounded-[10px_10px_10px_3px] border border-border-default bg-bg-elevated px-2.5 py-1.5 text-[12px] text-text-primary'
                      }
                    >
                      {message.body}
                    </div>
                    <span className="text-[9px] text-text-muted">{formatTime(message.created_at)}</span>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
      <div className="flex items-center gap-2 border-t border-border-default p-2.5">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleSend()
          }}
          placeholder="اكتبي رسالة..."
          className="h-9 flex-1 rounded-sm border border-border-default bg-bg-surface px-3 text-[12px] text-text-primary placeholder:text-text-muted focus:border-brand-primary focus:outline-none focus:ring-2 focus:ring-brand-accent/40"
        />
        <button
          type="button"
          onClick={handleSend}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-sm bg-brand-primary text-white transition-colors hover:bg-brand-primary-hover"
          aria-label="إرسال"
        >
          <Send size={15} />
        </button>
      </div>
    </div>
  )
}
