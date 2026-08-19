import { AlertTriangle, RefreshCw } from 'lucide-react'
import { Button } from './Button'

interface ErrorStateProps {
  title?: string
  description?: string
  onRetry?: () => void
}

/** حالة خطأ موحّدة حسب §20: رسالة مفهومة + إمكانية إعادة المحاولة. */
export function ErrorState({
  title = 'تعذّر تحميل البيانات',
  description = 'حدث خطأ أثناء الاتصال بالخادم، يمكنك المحاولة مرة أخرى',
  onRetry,
}: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-md border border-danger-border/20 bg-danger-bg px-6 py-16 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-bg-surface text-danger">
        <AlertTriangle size={24} />
      </div>
      <div className="flex flex-col gap-1">
        <p className="text-sm font-semibold text-text-primary">{title}</p>
        <p className="text-sm text-text-secondary">{description}</p>
      </div>
      {onRetry && (
        <Button variant="secondary" size="sm" icon={<RefreshCw size={14} />} onClick={onRetry}>
          إعادة المحاولة
        </Button>
      )}
    </div>
  )
}
