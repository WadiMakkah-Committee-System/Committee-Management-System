import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

/** بطاقة موحّدة حسب §12: خلفية بيضاء (أو Surface في الداكن)، حدود خفيفة، Radius 12px، ظل خفيف جدًا فقط. */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'rounded-md border border-border-default bg-bg-surface p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]',
        className,
      )}
      {...props}
    />
  )
}
