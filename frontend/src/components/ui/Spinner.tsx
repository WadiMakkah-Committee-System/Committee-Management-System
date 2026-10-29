import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

export function Spinner({ className, size = 24 }: { className?: string; size?: number }) {
  return <Loader2 size={size} className={cn('animate-spin text-brand-primary', className)} />
}

/**
 * مؤشر تحميل الصفحات — ثلاث نقاط بألوان الهوية تتموّج بالتتابع + شريط
 * طيف رفيع يعبر أعلى المساحة. CSS فقط (بلا JS) ليبقى خفيفًا جدًا أثناء
 * تحميل حزم الصفحات الكسولة (Lazy chunks).
 */
export function PageSpinner() {
  return (
    <div role="status" aria-label="جارٍ التحميل" className="relative flex min-h-[40vh] w-full items-center justify-center">
      <div className="absolute inset-x-0 top-0 h-[3px] overflow-hidden">
        <div className="brand-stripe animate-loader-bar h-full w-1/2 rounded-full" />
      </div>
      <div className="flex items-end gap-1.5">
        {['var(--wm-blue)', 'var(--wm-teal)', 'var(--wm-gold)'].map((c, i) => (
          <span
            key={c}
            className="h-2.5 w-2.5 rounded-full"
            style={{
              backgroundColor: c,
              animation: `float-soft 0.9s ${i * 0.12}s var(--ease-in-out-soft) infinite`,
            }}
          />
        ))}
      </div>
    </div>
  )
}
