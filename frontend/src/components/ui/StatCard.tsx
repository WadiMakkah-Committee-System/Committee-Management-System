import type { ReactNode } from 'react'
import { Card } from './Card'
import { CountUp } from '@/components/motion/primitives'
import { cn } from '@/lib/utils'

export type StatTone = 'brand' | 'teal' | 'purple' | 'orange' | 'success' | 'warning' | 'danger' | 'neutral'

/**
 * بطاقة إحصائية — أيقونة بلون من هوية وادي مكة، رقم يتصاعد عند الظهور،
 * وخط هوية رفيع أعلى البطاقة يكتمل عند المرور. الألوان من الدليل فقط.
 */
export function StatCard({
  label,
  value,
  icon,
  tone = 'brand',
  tintCard = false,
}: {
  label: string
  value: number | string
  icon: ReactNode
  tone?: StatTone
  /**
   * فعّليه لإعطاء خلفية/حدود البطاقة نفسها لونًا من هوية الشركة (لا دائرة
   * الأيقونة فقط) — طلب لاما 2026-09-05 على بطاقات إحصاء الاجتماعات: "خل
   * كل مربع لون من الوان الشركة". افتراضيًا false.
   */
  tintCard?: boolean
}) {
  const toneClasses: Record<StatTone, string> = {
    brand: 'bg-brand-primary/10 text-brand-primary',
    teal: 'bg-brand-teal/10 text-brand-teal',
    purple: 'bg-brand-purple/10 text-brand-purple',
    orange: 'bg-brand-orange/12 text-brand-orange',
    success: 'bg-success-bg text-success',
    warning: 'bg-warning-bg text-warning',
    danger: 'bg-danger-bg text-danger',
    neutral: 'bg-neutral-bg text-neutral',
  }

  const accent: Record<StatTone, string> = {
    brand: 'var(--brand-primary)',
    teal: 'var(--wm-teal)',
    purple: 'var(--wm-purple)',
    orange: 'var(--wm-gold)',
    success: 'var(--status-success-main)',
    warning: 'var(--status-warning-main)',
    danger: 'var(--status-error-main)',
    neutral: 'var(--status-neutral-main)',
  }

  const cardToneClasses: Record<StatTone, string> = {
    brand: '!bg-brand-primary/[0.06] !border-brand-primary/20',
    teal: '!bg-brand-teal/[0.06] !border-brand-teal/20',
    purple: '!bg-brand-purple/[0.06] !border-brand-purple/20',
    orange: '!bg-brand-orange/[0.07] !border-brand-orange/25',
    success: '!bg-success-bg !border-success-border/40',
    warning: '!bg-warning-bg !border-warning-border/40',
    danger: '!bg-danger-bg !border-danger-border/40',
    neutral: '!bg-neutral-bg !border-neutral-border/40',
  }

  return (
    <Card
      className={cn(
        'group relative flex items-center gap-4 overflow-hidden transition-[transform,box-shadow] duration-300 ease-out-expo hover:-translate-y-0.5 hover:shadow-lg',
        tintCard && cardToneClasses[tone],
      )}
      style={{ ['--stat-accent' as string]: accent[tone] }}
    >
      <span
        aria-hidden
        className="absolute inset-x-0 top-0 h-[3px] origin-right scale-x-[0.25] bg-[var(--stat-accent)] opacity-70 transition-transform duration-500 ease-out-expo group-hover:scale-x-100"
      />
      <span
        aria-hidden
        className="pointer-events-none absolute -left-8 -bottom-10 h-28 w-28 rounded-full bg-[var(--stat-accent)] opacity-[0.06] blur-2xl transition-opacity duration-500 group-hover:opacity-[0.14]"
      />
      <div
        className={cn(
          'relative flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl transition-transform duration-500 ease-out-expo group-hover:scale-105 group-hover:-rotate-3',
          toneClasses[tone],
        )}
      >
        {icon}
      </div>
      <div className="relative">
        <p className="text-3xl font-bold leading-none text-text-primary">
          {typeof value === 'number' ? <CountUp value={value} /> : value}
        </p>
        <p className="mt-1.5 text-sm text-text-muted">{label}</p>
      </div>
    </Card>
  )
}
