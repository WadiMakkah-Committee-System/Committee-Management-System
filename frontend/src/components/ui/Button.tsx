import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
type Size = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: React.ReactNode
}

/** أزرار موحّدة حسب §10 من دليل الهوية: Primary / Secondary / Danger. */
const VARIANT_CLASSES: Record<Variant, string> = {
  primary:
    'bg-brand-primary text-white hover:bg-brand-primary-hover active:scale-[0.98] shadow-sm disabled:hover:bg-brand-primary',
  secondary:
    'bg-bg-surface text-brand-primary border border-brand-primary hover:bg-brand-primary/5 active:scale-[0.98]',
  danger:
    'bg-danger text-white hover:brightness-95 active:scale-[0.98] shadow-sm',
  ghost:
    'bg-transparent text-text-secondary hover:bg-bg-elevated hover:text-text-primary active:scale-[0.98]',
}

const SIZE_CLASSES: Record<Size, string> = {
  sm: 'h-8 px-3 text-[13px] gap-1.5',
  md: 'h-10 px-4 text-sm gap-2',
  lg: 'h-12 px-5 text-base gap-2',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', loading, icon, disabled, children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={cn(
          'inline-flex items-center justify-center rounded-sm font-semibold transition-all duration-150',
          'disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg-app',
          VARIANT_CLASSES[variant],
          SIZE_CLASSES[size],
          className,
        )}
        {...props}
      >
        {loading ? <Loader2 size={16} className="animate-spin" /> : icon}
        {children}
      </button>
    )
  },
)
Button.displayName = 'Button'
