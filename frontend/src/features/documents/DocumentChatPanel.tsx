import { useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, FileText, Lock, Send, Sparkles } from 'lucide-react'
import { useAskDocument, useAskDocuments } from '@/hooks/useDocumentChat'
import { useAuthStore } from '@/store/authStore'
import { Avatar } from '@/components/ui/Avatar'
import { Spinner } from '@/components/ui/Spinner'
import { cn, extractErrorMessage } from '@/lib/utils'
import type { DocumentChatSource } from '@/types'

interface ChatTurn {
  id: string
  question: string
  answer?: string
  sources?: DocumentChatSource[]
  status: 'pending' | 'done' | 'error'
  errorMessage?: string
}

/**
 * الهدف:
 * لوحة "البحث الذكي" داخل الوثائق — نفس المكوّن يُستخدم بشكلين حسب
 * documentId: مقيَّد بوثيقة واحدة (Docked ضمن DocumentDetailPage، الإجابة
 * من محتوى تلك الوثيقة فقط) أو عام عبر كل الوثائق (صفحة كاملة
 * DocumentsSmartSearchPage). راجعي api/documentChat.ts وrouter الباك-إند
 * المطابق POST /documents/{document_id}/ask وPOST /documents/ask.
 *
 * كل سؤال مستقل (بلا تاريخ محادثة محفوظ بالخادم — قرار مقصود لمرحلة أولى
 * بسيطة، راجعي answer_question بـdocument_search_service.py) — سجل
 * الأسئلة/الأجوبة هنا محلي فقط بحالة المكوّن (turns)، يُفقَد عند مغادرة
 * الصفحة.
 */
export function DocumentChatPanel({ documentId, className }: { documentId?: string; className?: string }) {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const askDocument = useAskDocument()
  const askDocuments = useAskDocuments()

  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLDivElement | null>(null)

  function scrollToBottom() {
    requestAnimationFrame(() => {
      listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
    })
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const question = draft.trim()
    if (!question) return

    const turnId = crypto.randomUUID()
    setTurns((prev) => [...prev, { id: turnId, question, status: 'pending' }])
    setDraft('')
    scrollToBottom()

    const mutation = documentId
      ? askDocument.mutateAsync({ documentId, question })
      : askDocuments.mutateAsync(question)

    mutation
      .then((res) => {
        setTurns((prev) =>
          prev.map((t) =>
            t.id === turnId ? { ...t, status: 'done' as const, answer: res.answer, sources: res.sources } : t,
          ),
        )
        scrollToBottom()
      })
      .catch((err: unknown) => {
        setTurns((prev) =>
          prev.map((t) =>
            t.id === turnId ? { ...t, status: 'error' as const, errorMessage: extractErrorMessage(err) } : t,
          ),
        )
        scrollToBottom()
      })
  }

  const isSending = askDocument.isPending || askDocuments.isPending

  return (
    <div className={cn('flex flex-col overflow-hidden rounded-md border border-border-default bg-bg-surface', className)}>
      <div className="flex items-center gap-2.5 border-b border-border-default px-4 py-3.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-brand-primary to-brand-purple">
          <Sparkles size={15} className="text-white" />
        </div>
        <div>
          <p className="text-[13px] font-bold text-text-primary">
            {documentId ? 'اسأل عن هذه الوثيقة' : 'البحث الذكي'}
          </p>
          <p className="text-[11px] text-text-muted">
            {documentId ? 'الإجابات من محتوى هذه الوثيقة فقط' : 'اسأل عن أي وثيقة مصرَّح لك برؤيتها'}
          </p>
        </div>
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
