import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertCircle, Clock, FileText, Lock, Plus, Send, Sparkles } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import type { DocumentChatSession } from '@/hooks/useDocumentChat'
import { Avatar } from '@/components/ui/Avatar'
import { Spinner } from '@/components/ui/Spinner'
import { cn, formatDateTime } from '@/lib/utils'

/**
 * الهدف:
 * لوحة "البحث الذكي" داخل الوثائق — نفس المكوّن يُستخدم بشكلين حسب
 * session.documentId: مقيَّد بوثيقة واحدة (Docked ضمن DocumentDetailPage،
 * الإجابة من محتوى تلك الوثيقة فقط) أو عام عبر كل الوثائق (صفحة كاملة
 * DocumentsSmartSearchPage). راجعي api/documentChat.ts وrouter الباك-إند
 * المطابق POST /documents/{document_id}/ask وPOST /documents/ask.
 *
 * كل حالة المحادثة (الأسئلة/الأجوبة، قائمة المحادثات المحفوظة، التنقل
 * بينها) تأتي جاهزة عبر useDocumentChatSession — راجعي
 * hooks/useDocumentChat.ts. اللوحة هنا عرض فقط + زر "محادثة جديدة" وقائمة
 * سجل مضغوطة بالهيدر (hideHistoryToggle تخفيها لما تكون قائمة كاملة
 * DocumentChatSidebar معروضة أصلاً بجنبها، راجعي DocumentsSmartSearchPage).
 */
export function DocumentChatPanel({
  session,
  className,
  hideHistoryToggle,
}: {
  session: DocumentChatSession
  className?: string
  hideHistoryToggle?: boolean
}) {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { documentId, turns, isSending, sendQuestion, startNew, loadConversation, conversations } = session

  const [draft, setDraft] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const listRef = useRef<HTMLDivElement | null>(null)
  const historyRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!historyOpen) return
    const onClickOutside = (e: MouseEvent) => {
      if (historyRef.current && !historyRef.current.contains(e.target as Node)) setHistoryOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [historyOpen])

  useEffect(() => {
    requestAnimationFrame(() => {
      listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
    })
  }, [turns])

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!draft.trim()) return
    sendQuestion(draft)
    setDraft('')
  }

  return (
    <div className={cn('flex flex-col overflow-hidden rounded-md border border-border-default bg-bg-surface', className)}>
      <div className="flex items-center gap-2.5 border-b border-border-default px-4 py-3.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-brand-primary to-brand-purple">
          <Sparkles size={15} className="text-white" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-bold text-text-primary">
            {documentId ? 'اسأل عن هذه الوثيقة' : 'البحث الذكي'}
          </p>
          <p className="truncate text-[11px] text-text-muted">
            {documentId ? 'الإجابات من محتوى هذه الوثيقة فقط' : 'اسأل عن أي وثيقة مصرَّح لك برؤيتها'}
          </p>
        </div>

        <button
          type="button"
          onClick={startNew}
          title="محادثة جديدة"
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
        >
          <Plus size={15} />
        </button>

        {!hideHistoryToggle && (
          <div className="relative" ref={historyRef}>
            <button
              type="button"
              onClick={() => setHistoryOpen((o) => !o)}
              title="محادثاتي السابقة"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            >
              <Clock size={15} />
            </button>
            <AnimatePresence>
              {historyOpen && (
                <motion.div
                  initial={{ opacity: 0, scale: 0.95, y: -4 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95, y: -4 }}
                  transition={{ duration: 0.12 }}
                  className="absolute left-0 top-full z-20 mt-1 max-h-80 w-64 overflow-y-auto rounded-sm border border-border-default bg-bg-elevated py-1 shadow-lg"
                >
                  {conversations.length === 0 ? (
                    <p className="px-3 py-3 text-center text-[12px] text-text-muted">لا توجد محادثات سابقة بعد</p>
                  ) : (
                    conversations.map((c) => (
                      <button
                        key={c.conversation_id}
                        onClick={() => {
                          setHistoryOpen(false)
                          loadConversation(c.conversation_id)
                        }}
                        className={cn(
                          'flex w-full flex-col items-start gap-0.5 px-3 py-2 text-right transition-colors hover:bg-bg-surface',
                          c.conversation_id === session.conversationId && 'bg-bg-surface',
                        )}
                      >
                        <span className="w-full truncate text-[12.5px] font-medium text-text-primary">
                          {c.title ?? 'محادثة بلا عنوان'}
                        </span>
                        <span className="text-[10.5px] text-text-muted">{formatDateTime(c.updated_at)}</span>
                      </button>
                    ))
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>

      <div ref={listRef} className="flex-1 overflow-y-auto px-4 py-4">
        {turns.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 py-10 text-center">
            <Sparkles size={22} className="text-text-muted" />
            <p className="text-[13px] text-text-muted">
              {documentId ? 'اسأل عن أي شيء داخل هذه الوثيقة' : 'اكتب سؤالك عن أي وثيقة'}
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {turns.map((turn) => (
              <div key={turn.id} className="flex flex-col gap-3">
                <div className="flex flex-row-reverse items-start gap-2">
                  <Avatar firstName={user?.first_name ?? ''} lastName={user?.last_name ?? ''} size={26} />
                  <div className="max-w-[80%] rounded-[12px_12px_3px_12px] bg-brand-primary px-3 py-2 text-[13px] text-white">
                    {turn.question}
                  </div>
                </div>

                <div className="flex items-start gap-2">
                  <div className="flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-brand-primary to-brand-purple">
                    <Sparkles size={12} className="text-white" />
                  </div>
                  <div className="flex max-w-[80%] flex-col gap-2">
                    {turn.status === 'pending' && (
                      <div className="flex items-center gap-2 rounded-[12px_12px_12px_3px] border border-border-default bg-bg-elevated px-3 py-2">
                        <Spinner size={14} />
                        <span className="text-[12px] text-text-muted">جاري البحث في الوثائق...</span>
                      </div>
                    )}
                    {turn.status === 'error' && (
                      <div className="flex items-center gap-2 rounded-[12px_12px_12px_3px] border border-danger-border/30 bg-danger-bg px-3 py-2 text-[12px] text-danger">
                        <AlertCircle size={14} className="shrink-0" />
                        {turn.errorMessage}
                      </div>
                    )}
                    {turn.status === 'done' && (
                      <>
                        <div className="rounded-[12px_12px_12px_3px] border border-border-default bg-bg-elevated px-3 py-2 text-[13px] leading-relaxed text-text-primary">
                          {turn.answer}
                        </div>
                        {turn.sources && turn.sources.length > 0 && (
                          <div className="flex flex-wrap gap-1.5">
                            {turn.sources.map((source) => (
                              <button
                                key={source.document_id}
                                type="button"
                                onClick={() => navigate(`/documents/${source.document_id}`)}
                                className="flex items-center gap-1.5 rounded-sm border border-border-default bg-bg-surface px-2.5 py-1 text-[11px] font-medium text-text-primary transition-colors hover:border-brand-primary hover:text-brand-primary"
                              >
                                <FileText size={11} />
                                {source.title}
                              </button>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="border-t border-border-default p-3">
        <div className="flex items-center gap-2 rounded-sm border border-border-default bg-bg-app px-2 py-1 focus-within:border-brand-primary focus-within:ring-2 focus-within:ring-brand-accent/40">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={documentId ? 'اسأل عن محتوى هذه الوثيقة...' : 'اكتب سؤالك عن أي وثيقة...'}
            className="h-9 flex-1 bg-transparent text-[13px] text-text-primary placeholder:text-text-muted focus:outline-none"
          />
          <button
            type="submit"
            disabled={!draft.trim() || isSending}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm bg-brand-primary text-white transition-colors hover:bg-brand-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="إرسال"
          >
            <Send size={14} />
          </button>
        </div>
        {!documentId && (
          <p className="mt-2 flex items-center gap-1.5 text-[10.5px] text-text-muted">
            <Lock size={11} />
            يشمل البحث فقط الوثائق المصرَّح لك برؤيتها — قد تحتوي الإجابات على أخطاء، راجع الوثيقة الأصلية دائمًا
          </p>
        )}
      </form>
    </div>
  )
}
