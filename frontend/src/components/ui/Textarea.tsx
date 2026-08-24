import { forwardRef, useId, type TextareaHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string
  error?: string
  hint?: string
}

/** حقل نص متعدد الأسطر — نفس أسلوب Input (§11: Label إلزامي، Error/Focus State). */
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, label, error, hint, id, required, rows = 4, ...props }, ref) => {
    const generatedId = useId()
    const textareaId = id ?? generatedId

    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label htmlFor={textareaId} className="text-sm font-medium text-text-primary">
            {label}
            {required && <span className="text-danger"> *</span>}
          </label>
        )}
        <textarea
          ref={ref}
          id={textareaId}
          rows={rows}
          aria-invalid={!!error}
          className={cn(
            'w-full resize-y rounded-sm border bg-bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-muted',
            'transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-brand-accent/40',
            error
              ? 'border-danger focus:border-danger'
              : 'border-border-default focus:border-brand-primary',
            props.disabled && 'cursor-not-allowed opacity-60',
            className,
          )}
          {...props}
        />
        {error ? (
          <p className="text-xs font-medium text-danger">{error}</p>
        ) : hint ? (
          <p className="text-xs text-text-muted">{hint}</p>
        ) : null}
      </div>
    )
  },
)
Textarea.displayName = 'Textarea'
