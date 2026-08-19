import { AlertTriangle } from 'lucide-react'
import { Modal } from './Modal'
import { Button } from './Button'

interface ConfirmDialogProps {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  title: string
  description: string
  confirmLabel?: string
  variant?: 'danger' | 'primary'
  loading?: boolean
  errorMessage?: string | null
}

/**
 * نافذة تأكيد موحّدة للعمليات الحسّاسة (حذف/إيقاف) — §10: "يجب أن تظهر
 * نافذة Confirmation قبل العمليات الحساسة". تعرض أيضًا رسالة خطأ الباك-إند
 * حرفيًا (مثل حماية آخر super_admin) عند فشل العملية.
 */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = 'تأكيد',
  variant = 'danger',
  loading,
  errorMessage,
}: ConfirmDialogProps) {
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
          <Button variant={variant} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-danger-bg text-danger">
          <AlertTriangle size={20} />
        </div>
        <div className="flex flex-col gap-2">
          <p className="text-sm leading-relaxed text-text-secondary">{description}</p>
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
