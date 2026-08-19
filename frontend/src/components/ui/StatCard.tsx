import type { ReactNode } from 'react'
import { Card } from './Card'
import { cn } from '@/lib/utils'

export type StatTone = 'brand' | 'teal' | 'purple' | 'orange' | 'success' | 'warning' | 'danger'

/**
 * بطاقة إحصائية بأسلوب ملوّن (أيقونة دائرية بلون مختلف لكل بطاقة) — حسب
 * الشكل المرجعي الذي اعتمدته الشركة، مع الإبقاء على ألوان هوية وادي مكة
 * فقط (Primary/Teal/Purple/Orange/Success/Warning/Danger) دون اختراع ألوان
 * جديدة خارج الدليل.
 */
export function StatCard({
  label,
  value,
  icon,
  tone = 'brand',
}: {
  label: string
  value: number | string
  icon: ReactNode
  tone?: StatTone
}) {
  const toneClasses: Record<StatTone, string> = {
    brand: 'bg-brand-primary/10 text-brand-primary',
    teal: 'bg-brand-teal/10 text-brand-teal',
    purple: 'bg-brand-purple/10 text-brand-purple',
    orange: 'bg-brand-orange/10 text-brand-orange',
    success: 'bg-success-bg text-success',
    warning: 'bg-warning-bg text-warning',
    danger: 'bg-danger-bg text-danger',
  }

  return (
    <Card className="flex items-center gap-4">
      <div
        className={cn(
          'flex h-12 w-12 shrink-0 items-center justify-center rounded-full',
          toneClasses[tone],
        )}
      >
        {icon}
      </div>
      <div>
        <p className="text-3xl font-bold leading-none text-text-primary">{value}</p>
        <p className="mt-1.5 text-sm text-text-muted">{label}</p>
      </div>
    </Card>
  )
}
