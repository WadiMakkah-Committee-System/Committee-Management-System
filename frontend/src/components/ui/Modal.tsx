import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children: ReactNode
  footer?: ReactNode
  size?: 'sm' | 'md' | 'lg'
}

const SIZE_CLASSES = {
  sm: 'max-w-md',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
}

export function Modal({ open, onClose, title, description, children, footer, size = 'md' }: ModalProps) {
  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="absolute inset-0 bg-[#0a1430]/45 backdrop-blur-[3px]"
            onClick={onClose}
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-title"
            initial={{ opacity: 0, scale: 0.97, y: 18 }}
            animate={{ opacity: 1, scale: 1, y: 0, transition: { type: 'spring', stiffness: 380, damping: 32, mass: 0.8 } }}
            exit={{ opacity: 0, scale: 0.98, y: 10, transition: { duration: 0.16, ease: 'easeIn' } }}
            className={cn(
              'relative flex max-h-[90vh] w-full flex-col overflow-hidden rounded-lg border border-border-default bg-bg-surface shadow-2xl',
              SIZE_CLASSES[size],
            )}
          >
            <div aria-hidden className="brand-stripe h-[3px] w-full shrink-0 opacity-90" />
            <div className="flex items-start justify-between gap-4 border-b border-border-default px-6 py-4">
              <div>
                <h2 id="modal-title" className="text-lg font-semibold text-text-primary">
                  {title}
                </h2>
                {description && <p className="mt-0.5 text-sm text-text-muted">{description}</p>}
              </div>
              <button
                onClick={onClose}
                className="shrink-0 rounded-sm p-1.5 text-text-muted transition-[color,background-color,transform] duration-200 hover:rotate-90 hover:bg-bg-elevated hover:text-text-primary"
                aria-label="إغلاق"
              >
                <X size={18} />
              </button>
            </div>
            <div className="overflow-y-auto px-6 py-5">{children}</div>
            {footer && (
              <div className="flex items-center justify-end gap-2 border-t border-border-default bg-bg-elevated/60 px-6 py-4">
                {footer}
              </div>
            )}
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  )
}
