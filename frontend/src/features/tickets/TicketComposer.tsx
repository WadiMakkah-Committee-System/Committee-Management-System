import { useRef, useState, type ReactNode } from 'react'
import { Info, Lock, MessageSquare, Paperclip, Send } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import { TicketEditor, type TicketEditorHandle } from './ticketEditor'
import { DropOverlay, SelectedFilesList } from './TicketAttachments'
import { useTicketFilePicker } from './useTicketFilePicker'
import { ACCEPTED_FILES_HINT, BODY_MAX, countChars, ticketPlainText } from './ticketContent'
import { STATUS_AFTER_REPLY_OPTIONS } from './ticketLabels'
import type { OutgoingMessage } from './useTicketOutbox'
import type { Ticket, TicketDoc, TicketSupportSettableStatus } from '@/types/tickets'

type ComposerMode = 'public' | 'internal'

interface TicketComposerProps {
  ticket: Pick<Ticket, 'status' | 'viewer' | 'actions'>
  /** يُستدعى فورًا بدون انتظار — الرسالة تظهر بالمحادثة بحالة "جاري الإرسال". */
  onSend: (message: OutgoingMessage) => void
}

/**
 * الهدف:
 * صندوق كتابة الرد (TKT-FR-004 وTKT-FR-013 وTKT-FR-014).
 *
 * المسؤولية:
 * - محرر TipTap + مرفقات (سحب وإفلات أو زر) حتى 5 ملفات.
 * - للدعم: اختيار "رد عام" أو "ملاحظة داخلية" (الملاحظة بلون مختلف وواضح عشان
 *   ما تنرسل بالغلط كرد عام — القسم 7)، والحالة بعد الرد العام (الافتراضي:
 *   بانتظار رد المستخدم). التذكرة "تم الحل" تبقى محلولة مع رد الدعم.
 * - الإرسال ما ينتظر الخادم: المحتوى ينتقل للمحادثة ويتفرّغ الصندوق فورًا،
 *   وما ينقفل (TKT-FR-025). Ctrl/⌘ + Enter للإرسال.
 * - حالة الكتابة داخل هذا المكوّن فقط، فالكتابة ما تعيد رسم المحادثة.
 *
 * المدخلات: ticket (الحالة وصفة المشاهد والأزرار المتاحة من الباك-إند)، onSend.
 * الصلاحيات: يظهر فقط لو can_reply أو can_add_internal_note (من الباك-إند).
 */
export function TicketComposer({ ticket, onSend }: TicketComposerProps) {
  const { can_reply: canReply, can_add_internal_note: canNote } = ticket.actions
  const isSupport = ticket.viewer === 'support'
  const editorRef = useRef<TicketEditorHandle>(null)
  const [doc, setDoc] = useState<TicketDoc | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [mode, setMode] = useState<ComposerMode>(canReply ? 'public' : 'internal')
  const [statusAfter, setStatusAfter] = useState<TicketSupportSettableStatus>('waiting_on_requester')
  const [error, setError] = useState<string | null>(null)
  const picker = useTicketFilePicker(files, setFiles)

  // لو تغيّرت الصلاحيات (أو الحالة) والوضع الحالي ما عاد متاح.
  const activeMode: ComposerMode = mode === 'public' && !canReply ? 'internal' : mode === 'internal' && !canNote ? 'public' : mode
  const internal = activeMode === 'internal'
  const resolved = ticket.status === 'resolved'
  const showStatusAfter = isSupport && !internal && !resolved
  const length = countChars(ticketPlainText(doc))

  function send() {
    if (length > BODY_MAX) {
      setError(`النص أطول من الحد المسموح (${BODY_MAX} حرف)`)
      return
    }
    if (length === 0 && files.length === 0) {
      setError('اكتب رسالة أو أرفق ملفًا')
      return
    }
    onSend({
      doc: length > 0 ? doc : null,
      files,
      isInternal: internal,
      statusAfter: showStatusAfter ? statusAfter : null,
    })
    editorRef.current?.clear()
    setDoc(null)
    setFiles([])
    setError(null)
    picker.clearError()
    setStatusAfter('waiting_on_requester')
    editorRef.current?.focus()
  }

  return (
    <section
      aria-label={internal ? 'كتابة ملاحظة داخلية' : 'كتابة رد'}
      {...picker.getRootProps({
        className: cn(
          'relative flex flex-col gap-3 rounded-md border p-3 transition-colors sm:p-4',
          internal ? 'border-warning-border/50 bg-warning-bg' : 'border-border-default bg-bg-surface',
        ),
      })}
    >
      <input {...picker.getInputProps()} aria-label="اختيار مرفقات" />
      <DropOverlay active={picker.isDragActive} />

      {isSupport && canReply && canNote && (
        <div role="tablist" aria-label="نوع الرسالة" className="inline-flex w-fit items-center gap-0.5 rounded-sm border border-border-default bg-bg-surface p-0.5">
          <ModeTab active={!internal} onClick={() => setMode('public')} icon={<MessageSquare size={14} />}>
            رد عام
          </ModeTab>
          <ModeTab active={internal} onClick={() => setMode('internal')} icon={<Lock size={14} />} warning>
            ملاحظة داخلية
          </ModeTab>
        </div>
      )}

      {internal && (
        <p className="flex items-center gap-1.5 text-xs font-semibold text-warning">
          <Lock size={13} />
          ملاحظة داخلية — يشوفها فريق الدعم فقط، وما يوصل عنها إشعار لمقدّم الطلب
        </p>
      )}
      {!isSupport && ticket.status === 'resolved' && (
        <p className="flex items-center gap-1.5 text-xs text-text-secondary">
          <Info size={13} className="text-info" />
          التذكرة محلولة. إذا ما انحلت مشكلتك، ردّك يعيد فتحها.
        </p>
      )}
      {!isSupport && ticket.status === 'waiting_on_requester' && (
        <p className="flex items-center gap-1.5 text-xs font-semibold text-warning">
          <Info size={13} />
          الدعم الفني بانتظار ردك
        </p>
      )}

      <TicketEditor
        ref={editorRef}
        ariaLabel={internal ? 'نص الملاحظة الداخلية' : 'نص الرد'}
        placeholder={internal ? 'اكتب ملاحظة لفريق الدعم...' : 'اكتب ردك...'}
        invalid={!!error && length > BODY_MAX}
        onChange={(next) => {
          setDoc(next)
          if (error) setError(null)
        }}
        onSubmitShortcut={send}
        toolbarEnd={
          <button
            type="button"
            onClick={picker.open}
            title={`إرفاق ملفات: ${ACCEPTED_FILES_HINT}`}
            aria-label="إرفاق ملفات"
            className="flex h-7 items-center gap-1 rounded-xs px-1.5 text-xs font-medium text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <Paperclip size={15} />
            <span className="hidden sm:inline">إرفاق</span>
          </button>
        }
      />

      <SelectedFilesList files={files} onRemove={(index) => setFiles(files.filter((_, i) => i !== index))} />
      {(error || picker.error) && <p className="text-xs font-medium text-danger">{error ?? picker.error}</p>}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-text-muted">
          <span className={cn('tabular-nums', length > BODY_MAX && 'font-semibold text-danger')}>
            {length} / {BODY_MAX}
          </span>
          <span className="hidden md:inline"> · Ctrl + Enter للإرسال</span>
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {showStatusAfter && (
            <label className="flex items-center gap-2 text-xs text-text-secondary">
              <span className="shrink-0">الحالة بعد الرد</span>
              <select
                value={statusAfter}
                onChange={(e) => setStatusAfter(e.target.value as TicketSupportSettableStatus)}
                className="h-8 rounded-sm border border-border-default bg-bg-surface px-2 text-xs text-text-primary focus:border-brand-primary focus:outline-none focus:ring-2 focus:ring-brand-accent/40"
              >
                {STATUS_AFTER_REPLY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <Button size="sm" icon={internal ? <Lock size={14} /> : <Send size={14} />} onClick={send}>
            {internal ? 'إضافة الملاحظة' : 'إرسال'}
          </Button>
        </div>
      </div>
    </section>
  )
}

/** زر تبويب "رد عام / ملاحظة داخلية". */
function ModeTab({
  active,
  onClick,
  icon,
  warning,
  children,
}: {
  active: boolean
  onClick: () => void
  icon: ReactNode
  warning?: boolean
  children: ReactNode
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        'flex items-center gap-1.5 rounded-xs px-3 py-1.5 text-xs font-semibold transition-colors',
        active
          ? warning
            ? 'bg-warning-bg text-warning ring-1 ring-inset ring-warning-border/60'
            : 'bg-brand-primary text-white'
          : 'text-text-muted hover:text-text-primary',
      )}
    >
      {icon}
      {children}
    </button>
  )
}
