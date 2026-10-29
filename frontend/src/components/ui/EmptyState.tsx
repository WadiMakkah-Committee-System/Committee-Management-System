import type { ReactNode } from 'react'
import { motion } from 'framer-motion'

interface EmptyStateProps {
  icon: ReactNode
  title: string
  description?: string
  action?: ReactNode
}

/** حالة "لا توجد بيانات" موحّدة حسب §20: أيقونة + رسالة واضحة + إجراء عند الحاجة. */
export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="flex flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border-default bg-bg-surface px-6 py-16 text-center"
    >
      <div className="relative flex h-16 w-16 items-center justify-center">
        <span aria-hidden className="absolute inset-0 rounded-2xl bg-[linear-gradient(135deg,color-mix(in_srgb,var(--wm-cyan)_18%,transparent),color-mix(in_srgb,var(--wm-blue)_14%,transparent))] rotate-6" />
        <span className="relative flex h-14 w-14 items-center justify-center rounded-2xl border border-border-default bg-bg-surface text-brand-primary shadow-sm">
          {icon}
        </span>
      </div>
      <div className="flex flex-col gap-1">
        <p className="text-sm font-semibold text-text-primary">{title}</p>
        {description && <p className="text-sm text-text-muted">{description}</p>}
      </div>
      {action}
    </motion.div>
  )
}
