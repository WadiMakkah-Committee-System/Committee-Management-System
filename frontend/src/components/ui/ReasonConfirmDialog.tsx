import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Modal } from './Modal'
import { Button } from './Button'
import { Textarea } from './Textarea'

interface ReasonConfirmDialogProps {
  open: boolean
  onClose: () => void
  onConfirm: (reason: string) => void
  title: string
  description: string
  reasonLabel?: string
  confirmLabel?: string
  variant?: 'danger' | 'primary'
  loading?: boolean
  errorMessage?: string | null
}

const MIN_REASON_LENGTH = 3

/**
 * نافذة تأكيد بسبب إلزامي — نفس أسلوب ConfirmDialog، لكن لإجراءات تتطلب
 * توثيق سبب (إرجاع الطلب لمقدّمه أو للمكتب التنفيذي، رفض الطلب) حسب
 * CommitteeRejectRequest/CommitteeReturnRequest بالباك-إند
 * (min_length=3). التحقق هنا للتجربة الفورية فقط — التحقق الفعلي دائمًا
 * بالباك-إند.
 */
export function ReasonConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  reasonLabel = 'السبب',
  confirmLabel = 'تأكيد',
  variant = 'danger',
  loading,
  errorMessage,
}: ReasonConfirmDialogProps) {
  const [reason, setReason] = useState('')
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    if (open) {
      setReason('')
      setTouched(false)
    }
  }, [open])

  const trimmed = reason.trim()
  const validationError =
    touched && trimmed.length < MIN_REASON_LENGTH ? `السبب يجب أن يكون ${MIN_REASON_LENGTH} أحرف على الأقل` : undefined

  function handleConfirm() {
    setTouched(true)
    if (trimmed.length < MIN_REASON_LENGTH) return
    onConfirm(trimmed)
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button variant={variant} onClick={handleConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-warning-bg text-warning">
          <AlertTriangle size={20} />
        </div>
        <div className="flex flex-1 flex-col gap-3">
          <p className="text-sm leading-relaxed text-text-secondary">{description}</p>
          <Textarea
            label={reasonLabel}
            required
            placeholder="اكتبي السبب هنا..."
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            onBlur={() => setTouched(true)}
            error={validationError}
            rows={3}
          />
          {errorMessage && (
            <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
              {errorMessage}
            </p>
          )}
        </div>
      </div>
    </Modal>
  )
}
