import { ChevronLeft, ChevronRight, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * شريط رفيع لطيّ/فتح لوحة جانبية بغرفة الاجتماع (طلب لاما 2026-11-09 — "أقدر
 * أقفل الجزء وأفتحه عشان المساحة"). مفتوحة: سهم فقط بحافة اللوحة. مطوية:
 * أيقونة + اسم اللوحة عموديًا، فتبقى قابلة للاكتشاف بدون ما تاخذ مساحة.
 *
 * side = موقع اللوحة على الشاشة (الواجهة RTL): 'right' للوحة الاجتماع بجانب
 * الشريط العام، 'left' للوحة المحضر. اتجاه السهم = اتجاه حركة اللوحة.
 */
export function PanelEdgeToggle({
  open,
  onToggle,
  side,
  label,
  icon: Icon,
}: {
  open: boolean
  onToggle: () => void
  side: 'right' | 'left'
  label: string
  icon: LucideIcon
}) {
  const Arrow = (side === 'right') === open ? ChevronRight : ChevronLeft
  const action = open ? `إخفاء ${label}` : `إظهار ${label}`
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={action}
      aria-expanded={open}
      title={action}
      className={cn(
        'flex w-7 shrink-0 flex-col items-center gap-2 bg-bg-app py-3 text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary',
        side === 'right' ? 'border-l border-border-default' : 'border-r border-border-default',
      )}
    >
      <Arrow size={16} />
      {!open && (
        <>
          <Icon size={15} className="text-brand-primary" />
          <span className="text-[11px] font-semibold [writing-mode:vertical-rl]">{label}</span>
        </>
      )}
    </button>
  )
}
