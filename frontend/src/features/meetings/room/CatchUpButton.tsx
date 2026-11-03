import { useState } from 'react'
import { History, Loader2, X } from 'lucide-react'
import { fetchCatchUp } from '@/api/meetings'
import { cn, extractErrorMessage } from '@/lib/utils'

const OPTIONS = [5, 10, 15]

/**
 * "وش فاتني؟" (قرار لاما 2026-11-03): ملخص Gemini لآخر 5/10/15 دقيقة من
 * الترجمة النصية — للي دخل متأخر أو سرح شوي. يحتاج الترجمة النصية تكون
 * شغّالة (يشغّلها رئيس اللجنة)، وإلا يقول ما فيه كلام محفوظ.
 */
export function CatchUpButton({ meetingId }: { meetingId: string }) {
  const [open, setOpen] = useState(false)
  const [minutes, setMinutes] = useState(10)
  const [loading, setLoading] = useState(false)
  const [summary, setSummary] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function load(m: number) {
    setMinutes(m)
    setLoading(true)
    setSummary(null)
    setMessage(null)
    try {
      const result = await fetchCatchUp(meetingId, m)
      if (result.summary) setSummary(result.summary)
      else setMessage('ما فيه كلام محفوظ بهالفترة — الترجمة النصية لازم تكون شغّالة (يشغّلها رئيس اللجنة).')
    } catch (err) {
      setMessage(extractErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpen(true)
          void load(minutes)
        }}
        aria-label="وش فاتني؟"
        title="وش فاتني؟"
        className="flex h-11 items-center gap-1.5 rounded-full bg-white/10 px-3.5 text-[12px] font-semibold text-white transition-all hover:bg-white/20 active:scale-95"
      >
        <History size={16} />
        وش فاتني؟
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setOpen(false)}>
          <div
            className="w-full max-w-lg rounded-lg bg-bg-surface p-5 shadow-2xl ring-1 ring-border-default"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-base font-semibold text-text-primary">
                <History size={17} className="text-brand-primary" /> وش فاتني؟
              </h3>
              <button type="button" onClick={() => setOpen(false)} className="rounded-sm p-1 text-text-muted hover:bg-bg-elevated">
                <X size={16} />
              </button>
            </div>
            <div className="mb-3 flex gap-1.5">
              {OPTIONS.map((m) => (
                <button
                  key={m}
                  type="button"
                  disabled={loading}
                  onClick={() => void load(m)}
                  className={cn(
                    'rounded-full border px-3 py-1 text-[12px] font-medium transition-colors',
                    m === minutes
                      ? 'border-brand-primary bg-brand-primary text-white'
                      : 'border-border-default text-text-secondary hover:border-brand-primary',
                  )}
                >
                  آخر {m} دقائق
                </button>
              ))}
            </div>
            <div className="min-h-[120px] rounded-md bg-bg-elevated p-3">
              {loading ? (
                <div className="flex h-full min-h-[100px] items-center justify-center gap-2 text-sm text-text-muted">
                  <Loader2 size={16} className="animate-spin" /> جاري التلخيص...
                </div>
              ) : summary ? (
                <p className="whitespace-pre-line text-[14px] leading-7 text-text-primary">{summary}</p>
              ) : (
                <p className="text-[13px] text-text-muted">{message}</p>
              )}
            </div>
            <p className="mt-2 text-[11px] text-text-muted">ملخص آلي من الترجمة النصية — قد لا يكون دقيقًا 100%.</p>
          </div>
        </div>
      )}
    </>
  )
}
