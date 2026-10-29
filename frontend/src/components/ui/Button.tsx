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
    'btn-shine bg-brand-primary bg-[linear-gradient(135deg,var(--brand-primary),var(--brand-primary-hover))] text-white shadow-[0_1px_0_rgba(255,255,255,0.18)_inset,0_6px_16px_-6px_color-mix(in_srgb,var(--brand-primary)_70%,transparent)] hover:-translate-y-px hover:shadow-[0_1px_0_rgba(255,255,255,0.18)_inset,0_10px_22px_-8px_color-mix(in_srgb,var(--brand-primary)_80%,transparent)] active:translate-y-0 active:scale-[0.98] disabled:hover:translate-y-0',
  secondary:
    'bg-bg-surface text-brand-primary border border-brand-primary/40 hover:border-brand-primary hover:bg-brand-primary/[0.06] active:scale-[0.98]',
  danger:
    'bg-danger text-white shadow-[0_6px_16px_-8px_var(--status-error-main)] hover:-translate-y-px hover:brightness-105 active:translate-y-0 active:scale-[0.98] disabled:hover:translate-y-0',
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
          'inline-flex select-none items-center justify-center rounded-sm font-semibold transition-[transform,box-shadow,background-color,border-color,color,filter] duration-200 ease-out-quart',
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
