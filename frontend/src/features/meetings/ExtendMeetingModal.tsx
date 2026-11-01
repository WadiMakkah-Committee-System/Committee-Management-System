import { useMemo, useState } from 'react'
import { Clock } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { cn, formatDateTime } from '@/lib/utils'

/** خيارات التمديد السريعة بالدقائق. */
const QUICK_MINUTES = [15, 30, 60] as const

type Choice = (typeof QUICK_MINUTES)[number] | 'custom'

interface ExtendMeetingModalProps {
  open: boolean
  onClose: () => void
  /** وقت النهاية الحالي (ISO) — أساس حساب التمديد السريع. */
  currentEndAt: string
  onSubmit: (newEndAtIso: string) => void
  loading: boolean
  serverError: string | null
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

/**
 * الهدف:
 * نافذة "تمديد الاجتماع" (طلب لاما 2026-11-01) — قبل الاجتماع أو أثناءه.
 *
 * المسؤولية:
 * - خيارات سريعة (+15/+30/+60 دقيقة على وقت النهاية الحالي) أو وقت مخصص
 *   بنفس يوم النهاية الحالي.
 * - عرض وقت النهاية الجديد قبل التأكيد.
 *
 * المخرجات: onSubmit(newEndAtIso). التحقق النهائي (تمديد فقط، ضمن فترة
 * اللجنة، الاجتماع لم ينتهِ) مفروض بالباك إند (POST /meetings/{id}/extend).
 */
export function ExtendMeetingModal({ open, onClose, currentEndAt, onSubmit, loading, serverError }: ExtendMeetingModalProps) {
  const currentEnd = useMemo(() => new Date(currentEndAt), [currentEndAt])
  // تُركَّب النافذة من جديد مع كل فتح (MeetingDetailPage يعرضها فقط وهي
  // مفتوحة) — فالقيم الابتدائية هنا تكفي بدون إعادة ضبط داخل useEffect.
  const [choice, setChoice] = useState<Choice>(30)
  const [customTime, setCustomTime] = useState(() => `${pad(currentEnd.getHours())}:${pad(currentEnd.getMinutes())}`)
  const [localError, setLocalError] = useState<string | null>(null)

  const newEnd = useMemo(() => {
    if (choice !== 'custom') return new Date(currentEnd.getTime() + choice * 60_000)
    if (!/^\d{2}:\d{2}$/.test(customTime)) return null
    const [h, m] = customTime.split(':').map(Number)
    const d = new Date(currentEnd)
    d.setHours(h, m, 0, 0)
    return d
  }, [choice, customTime, currentEnd])

  const submit = () => {
    if (!newEnd || newEnd.getTime() <= currentEnd.getTime()) {
      setLocalError('وقت النهاية الجديد يجب أن يكون بعد وقت النهاية الحالي')
      return
    }
    setLocalError(null)
    onSubmit(newEnd.toISOString())
  }

  const error = localError ?? serverError

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="تمديد الاجتماع"
      description={`وقت النهاية الحالي: ${formatDateTime(currentEndAt)}`}
      size="sm"
      footer={
        <Button className="w-full" icon={<Clock size={16} />} loading={loading} onClick={submit}>
          تمديد
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" role="radiogroup" aria-label="مدة التمديد">
          {[...QUICK_MINUTES, 'custom' as const].map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={choice === option}
              onClick={() => setChoice(option)}
              className={cn(
                'h-10 rounded-sm border text-sm font-medium transition-colors',
                choice === option
                  ? 'border-brand-primary bg-brand-primary/10 text-brand-primary'
                  : 'border-border-default text-text-secondary hover:border-brand-primary/50',
              )}
            >
              {option === 'custom' ? 'وقت مخصص' : option === 60 ? '+ ساعة' : `+ ${option} دقيقة`}
            </button>
          ))}
        </div>

        {choice === 'custom' && (
          <Input
            label="وقت النهاية الجديد"
            type="time"
            dir="ltr"
            value={customTime}
            onChange={(e) => setCustomTime(e.target.value)}
          />
        )}

        {newEnd && (
          <p className="rounded-sm bg-bg-elevated px-3 py-2 text-sm text-text-secondary">
            ينتهي الاجتماع في:{' '}
            <span className="font-semibold text-text-primary">{formatDateTime(newEnd.toISOString())}</span>
          </p>
        )}
        <p className="text-xs text-text-muted">يُرسل إشعار للمشاركين بموعد النهاية الجديد.</p>

        {error && (
          <p role="alert" className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
            {error}
          </p>
        )}
      </div>
    </Modal>
  )
}
