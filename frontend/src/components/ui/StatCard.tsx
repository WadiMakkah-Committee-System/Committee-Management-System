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
  tintCard = false,
}: {
  label: string
  value: number | string
  icon: ReactNode
  tone?: StatTone
  /**
   * فعّليه لإعطاء خلفية/حدود البطاقة نفسها لونًا من هوية الشركة (لا دائرة
   * الأيقونة فقط) — طلب لاما 2026-09-05 على بطاقات إحصاء الاجتماعات: "خل
   * كل مربع لون من الوان الشركة". افتراضيًا false فتبقى كل الصفحات الأخرى
   * (الإدارات/اللجان/الأدوار/المستخدمين...) بشكلها الحالي بدون تغيير غير
   * مطلوب — الشفافية منخفضة (8٪ خلفية) فلا تُضعف تباين رقم البطاقة أو
   * تسمّيتها بأي من الوضعين (فاتح/داكن).
   */
  tintCard?: boolean
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

  const cardToneClasses: Record<StatTone, string> = {
    brand: '!bg-brand-primary/8 !border-brand-primary/30',
    teal: '!bg-brand-teal/8 !border-brand-teal/30',
    purple: '!bg-brand-purple/8 !border-brand-purple/30',
    orange: '!bg-brand-orange/8 !border-brand-orange/30',
    success: '!bg-success-bg !border-success-border/60',
    warning: '!bg-warning-bg !border-warning-border/60',
    danger: '!bg-danger-bg !border-danger-border/60',
  }

  return (
    <Card className={cn('flex items-center gap-4', tintCard && cardToneClasses[tone])}>
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
