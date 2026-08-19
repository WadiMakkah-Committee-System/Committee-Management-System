import type { ReactNode } from 'react'
import { Card } from './Card'
import { cn } from '@/lib/utils'

export function StatCard({
  label,
  value,
  icon,
  tone = 'brand',
}: {
  label: string
  value: number | string
  icon: ReactNode
  tone?: 'brand' | 'success' | 'warning' | 'danger'
}) {
  const toneClasses: Record<string, string> = {
    brand: 'bg-brand-primary/10 text-brand-primary',
    success: 'bg-success-bg text-success',
    warning: 'bg-warning-bg text-warning',
    danger: 'bg-danger-bg text-danger',
  }

  return (
    <Card className="flex items-center gap-4">
      <div className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-sm', toneClasses[tone])}>
        {icon}
      </div>
      <div>
        <p className="text-2xl font-bold leading-none text-text-primary">{value}</p>
        <p className="mt-1 text-sm text-text-muted">{label}</p>
      </div>
    </Card>
  )
}
