import type { HTMLAttributes, KeyboardEvent } from 'react'
import { cn } from '@/lib/utils'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /**
   * فعّليها عند استخدام البطاقة كعنصر قابل للنقر (onClick) — تضيف
   * تلقائيًا role="button" + tabIndex + تفعيل عبر لوحة المفاتيح
   * (Enter/Space) + حلقة تركيز (focus-visible ring) + ظل عند hover، بدل
   * تكرار هذا المنطق يدويًا في كل صفحة تستخدم بطاقات قابلة للنقر. بطاقة
   * onClick بدون هذا العنصر لا يقدر مستخدم لوحة المفاتيح يفعّلها — فجوة
   * وصولية (Accessibility) كانت موجودة قبل هذا التعديل.
   */
  interactive?: boolean
}

/** بطاقة موحّدة حسب §12: خلفية بيضاء (أو Surface في الداكن)، حدود خفيفة، Radius 12px، ظل خفيف جدًا فقط. */
export function Card({ className, interactive, onClick, onKeyDown, ...props }: CardProps) {
  function handleKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    onKeyDown?.(e)
    if (!interactive || !onClick || e.defaultPrevented) return
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      // نُحاكي نقرة فأرة فعلية بدل استدعاء onClick مباشرة، لأن توقيعه
      // MouseEventHandler ولا يقبل KeyboardEvent — click() يمرّ عبر نفس
      // مستمع onClick بدون Type Hack.
      e.currentTarget.click()
    }
  }

  return (
    <div
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={onClick}
      onKeyDown={interactive ? handleKeyDown : onKeyDown}
      className={cn(
        'rounded-md border border-border-default bg-bg-surface p-4 shadow-xs',
        interactive &&
          'cursor-pointer transition-[transform,box-shadow,border-color] duration-300 ease-out-expo hover:-translate-y-0.5 hover:border-brand-primary/25 hover:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app',
        className,
      )}
      {...props}
    />
  )
}
