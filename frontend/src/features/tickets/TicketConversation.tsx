import { memo, useEffect, useMemo, useRef, useSyncExternalStore, type ReactNode } from 'react'
import { onlineManager } from '@tanstack/react-query'
import { AlertCircle, Clock3, Headset, Lock, RotateCw, Trash2, WifiOff } from 'lucide-react'
import { Avatar } from '@/components/ui/Avatar'
import { cn, formatDateTime, formatRelativeTime } from '@/lib/utils'
import { TicketRichText } from './ticketEditor'
import { FileTypeIcon, TicketAttachmentLink } from './TicketAttachments'
import { isEmptyTicketDoc } from './ticketContent'
import type { OutboxEntry } from './useTicketOutbox'
import type { TicketMessage, TicketViewer } from '@/types/tickets'

interface ConversationProps {
  ticketId: string
  messages: TicketMessage[]
  outbox: OutboxEntry[]
  currentUser: { user_id: string; first_name: string; last_name: string }
  viewer: TicketViewer
  onRetry: (clientId: string) => void
  onDiscard: (clientId: string) => void
}

/**
 * الهدف:
 * محادثة التذكرة (القسم 7): الوصف أول رسالة، ثم الردود العامة، وللدعم الملاحظات
 * الداخلية بلون مختلف وواضح، ثم الرسائل اللي بانتظار الحفظ أو فشل إرسالها.
 *
 * المسؤولية:
 * - عرض فقط — بدون أي حالة كتابة، فالكتابة بصندوق الرد ما تعيد رسم الرسائل
 *   (memo على المكوّن وعلى كل رسالة).
 * - الرسائل المرسلة من هنا تظهر بالجهة المقابلة (مثل محادثة الاجتماع).
 * - رسالة بالصادر انحفظت فعلًا (وصلت بإعادة جلب قبل رد الإرسال) ما تتكرر:
 *   تُخفى بمطابقة client_message_id.
 * - تمرير تلقائي لآخر رسالة عند الإرسال، أو عند وصول رسالة والمستخدم قريب من الأسفل.
 *
 * الأمان: الملاحظات الداخلية ما توصل أصلًا لغير الدعم (فلترة بالباك-إند)؛
 * التلوين هنا لمنع الخلط بين الرد العام والملاحظة عند الدعم فقط.
 */
export const TicketConversation = memo(function TicketConversation({
  ticketId,
  messages,
  outbox,
  currentUser,
  viewer,
  onRetry,
  onDiscard,
}: ConversationProps) {
  const endRef = useRef<HTMLLIElement>(null)
  const pending = useMemo(() => {
    const saved = new Set(messages.map((m) => m.client_message_id).filter(Boolean))
    return outbox.filter((entry) => !saved.has(entry.clientId))
  }, [messages, outbox])

  const count = messages.length + pending.length
  const previousCount = useRef(count)
  const previousPending = useRef(pending.length)
  useEffect(() => {
    const grew = count > previousCount.current
    const sentNow = pending.length > previousPending.current
    previousCount.current = count
    previousPending.current = pending.length
    if (!grew) return
    const nearBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 320
    if (sentNow || nearBottom) endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [count, pending.length])

  return (
    <ol className="flex flex-col gap-4" aria-label="محادثة التذكرة">
      {messages.map((message) => (
        <li key={message.message_id}>
          <MessageBubble
            ticketId={ticketId}
            message={message}
            isMine={message.author.user_id === currentUser.user_id}
            viewer={viewer}
          />
        </li>
      ))}
      {pending.map((entry) => (
        <li key={entry.clientId}>
          <PendingBubble entry={entry} currentUser={currentUser} onRetry={onRetry} onDiscard={onDiscard} />
        </li>
      ))}
      <li ref={endRef} aria-hidden className="h-0" />
    </ol>
  )
})

/** سطر الكاتب والوقت فوق الفقاعة. */
function AuthorLine({
  name,
  isMine,
  supportSide,
  time,
  extra,
}: {
  name: string
  isMine: boolean
  supportSide: boolean
  time: string
  extra?: ReactNode
}) {
  return (
    <div className={cn('mb-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs', isMine && 'flex-row-reverse')}>
      <span className="font-semibold text-text-primary">{isMine ? 'أنت' : name}</span>
      {supportSide && !isMine && (
        <span className="inline-flex items-center gap-1 rounded-xs bg-brand-primary/10 px-1.5 py-0.5 text-[11px] font-semibold text-brand-primary">
          <Headset size={11} />
          الدعم الفني
        </span>
      )}
      {extra}
      <time className="text-text-muted" dateTime={time} title={formatDateTime(time)}>
        {formatRelativeTime(time)}
      </time>
    </div>
  )
}

/**
 * رسالة محفوظة. الوصف والملاحظة الداخلية بعرض كامل (بطاقة)، والردود فقاعات:
 * رسائلي بلون الهوية بالجهة المقابلة، ورسائل الطرف الآخر بخلفية محايدة.
 */
const MessageBubble = memo(function MessageBubble({
  ticketId,
  message,
  isMine,
  viewer,
}: {
  ticketId: string
  message: TicketMessage
  isMine: boolean
  viewer: TicketViewer
}) {
  const name = `${message.author.first_name} ${message.author.last_name}`
  const hasBody = !isEmptyTicketDoc(message.body_json)

  if (message.is_internal) {
    return (
      <article className="rounded-md border border-warning-border/40 bg-warning-bg px-4 py-3">
        <AuthorLine
          name={name}
          isMine={false}
          supportSide={false}
          time={message.created_at}
          extra={
            <span className="inline-flex items-center gap-1 font-semibold text-warning">
              <Lock size={12} />
              ملاحظة داخلية — ما يشوفها مقدّم الطلب
            </span>
          }
        />
        {hasBody && <TicketRichText doc={message.body_json} className="text-text-primary" />}
        <Attachments ticketId={ticketId} message={message} />
      </article>
    )
  }

  if (message.is_description) {
    return (
      <article className="rounded-md border border-border-default bg-bg-surface px-4 py-3 shadow-xs">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Avatar firstName={message.author.first_name} lastName={message.author.last_name} size={28} />
          <span className="text-sm font-semibold text-text-primary">{isMine ? 'أنت' : name}</span>
          <span className="rounded-xs bg-bg-elevated px-1.5 py-0.5 text-[11px] font-semibold text-text-muted">
            وصف التذكرة
          </span>
          <time className="text-xs text-text-muted" dateTime={message.created_at} title={formatDateTime(message.created_at)}>
            {formatRelativeTime(message.created_at)}
          </time>
        </div>
        <TicketRichText doc={message.body_json} className="text-text-primary" />
        <Attachments ticketId={ticketId} message={message} />
      </article>
    )
  }

  const supportSide = message.author_side === 'support'
  return (
    <article className={cn('flex items-start gap-2.5', isMine && 'flex-row-reverse')}>
      <Avatar firstName={message.author.first_name} lastName={message.author.last_name} size={30} />
      <div className={cn('flex min-w-0 max-w-[85%] flex-col sm:max-w-[75%]', isMine && 'items-end')}>
        <AuthorLine
          name={name}
          isMine={isMine}
          supportSide={supportSide && viewer === 'requester'}
          time={message.created_at}
        />
        <div
          className={cn(
            'min-w-0 max-w-full px-3.5 py-2.5',
            isMine
              ? 'rounded-[14px_14px_4px_14px] bg-brand-primary text-white'
              : 'rounded-[14px_14px_14px_4px] border border-border-default bg-bg-surface text-text-primary',
          )}
        >
          {hasBody && <TicketRichText doc={message.body_json} />}
          <Attachments ticketId={ticketId} message={message} onDark={isMine} />
        </div>
      </div>
    </article>
  )
})

/** مرفقات رسالة محفوظة (تنزيل عبر المسار المحمي). */
function Attachments({ ticketId, message, onDark }: { ticketId: string; message: TicketMessage; onDark?: boolean }) {
  if (message.attachments.length === 0) return null
  const spaced = !isEmptyTicketDoc(message.body_json)
  return (
    <div className={cn('flex flex-wrap gap-2', spaced && 'mt-2.5')}>
      {message.attachments.map((attachment) => (
        <TicketAttachmentLink key={attachment.attachment_id} ticketId={ticketId} attachment={attachment} onDark={onDark} />
      ))}
    </div>
  )
}

/**
 * حالة الاتصال كما يراها TanStack Query: بدون إنترنت يوقف الإرسال مؤقتًا
 * (networkMode الافتراضي) ويكمله تلقائيًا عند الرجوع — فنعرض "بانتظار الاتصال"
 * بدل "جاري الإرسال" عشان المستخدم يعرف وش يصير.
 */
function useIsOnline(): boolean {
  return useSyncExternalStore(
    (onChange) => onlineManager.subscribe(onChange),
    () => onlineManager.isOnline(),
  )
}

/**
 * رسالة بالصادر: "جاري الإرسال" ثم تختفي عند الحفظ (وتظهر مكانها المحفوظة)، أو
 * "فشل" مع سبب الرفض و"إعادة المحاولة" و"حذف" (TKT-FR-025).
 */
const PendingBubble = memo(function PendingBubble({
  entry,
  currentUser,
  onRetry,
  onDiscard,
}: {
  entry: OutboxEntry
  currentUser: ConversationProps['currentUser']
  onRetry: (clientId: string) => void
  onDiscard: (clientId: string) => void
}) {
  const failed = entry.status === 'failed'
  const online = useIsOnline()
  const hasBody = !!entry.doc && !isEmptyTicketDoc(entry.doc)
  return (
    <article className="flex flex-row-reverse items-start gap-2.5" aria-live="polite">
      <Avatar firstName={currentUser.first_name} lastName={currentUser.last_name} size={30} />
      <div className="flex min-w-0 max-w-[85%] flex-col items-end sm:max-w-[75%]">
        <div
          className={cn(
            'min-w-0 max-w-full rounded-[14px_14px_4px_14px] px-3.5 py-2.5',
            entry.isInternal
              ? 'border border-warning-border/40 bg-warning-bg text-text-primary'
              : failed
                ? 'border border-danger-border/40 bg-danger-bg text-text-primary'
                : 'bg-brand-primary/75 text-white',
          )}
        >
          {entry.isInternal && (
            <p className="mb-1 flex items-center gap-1 text-xs font-semibold text-warning">
              <Lock size={12} />
              ملاحظة داخلية
            </p>
          )}
          {hasBody && entry.doc && <TicketRichText doc={entry.doc} />}
          {entry.files.length > 0 && (
            <ul className={cn('flex flex-wrap gap-2', hasBody && 'mt-2.5')}>
              {entry.files.map((file, i) => (
                <li
                  key={`${file.name}-${i}`}
                  className="flex items-center gap-1.5 rounded-sm border border-current/20 px-2 py-1 text-xs opacity-90"
                >
                  <FileTypeIcon name={file.name} size={13} />
                  <span className="max-w-44 truncate">{file.name}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        {failed ? (
          <div className="mt-1 flex flex-wrap items-center justify-end gap-x-3 gap-y-1 text-xs">
            <span className="flex items-center gap-1 font-semibold text-danger">
              <AlertCircle size={13} />
              فشل الإرسال{entry.error ? ` — ${entry.error}` : ''}
            </span>
            <button
              type="button"
              onClick={() => onRetry(entry.clientId)}
              className="flex items-center gap-1 font-semibold text-brand-primary hover:underline"
            >
              <RotateCw size={12} />
              إعادة المحاولة
            </button>
            <button
              type="button"
              onClick={() => onDiscard(entry.clientId)}
              className="flex items-center gap-1 text-text-muted hover:text-danger"
            >
              <Trash2 size={12} />
              حذف
            </button>
          </div>
        ) : online ? (
          <span className="mt-1 flex items-center gap-1 text-xs text-text-muted">
            <Clock3 size={12} className="animate-pulse" />
            جاري الإرسال…
          </span>
        ) : (
          <span className="mt-1 flex items-center gap-1 text-xs font-medium text-warning">
            <WifiOff size={12} />
            بانتظار الاتصال — تنرسل تلقائيًا أول ما يرجع الإنترنت
          </span>
        )}
      </div>
    </article>
  )
})
