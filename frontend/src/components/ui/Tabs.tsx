import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'

export interface TabItem {
  key: string
  label: string
  icon?: ReactNode
}

interface TabsProps {
  items: TabItem[]
  value: string
  onChange: (key: string) => void
}

/** تبويبات موحّدة — مؤشر نشط متحرك تحت التبويب الحالي، تدعم RTL بشكل طبيعي. */
export function Tabs({ items, value, onChange }: TabsProps) {
  return (
    <div role="tablist" className="flex items-center gap-1 border-b border-border-default">
      {items.map((item) => {
        const isActive = item.key === value
        return (
          <button
            key={item.key}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(item.key)}
            className={cn(
              'relative flex items-center gap-2 px-4 py-3 text-sm font-semibold transition-colors',
              isActive ? 'text-brand-primary' : 'text-text-muted hover:text-text-primary',
            )}
          >
            {item.icon}
            {item.label}
            {isActive && (
              <motion.div
                layoutId="tabs-active-indicator"
                className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-brand-primary"
                transition={{ duration: 0.2, ease: 'easeOut' }}
              />
            )}
          </button>
        )
      })}
    </div>
  )
}
