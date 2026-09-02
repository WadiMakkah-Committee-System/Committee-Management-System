import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Calendar as CalendarIcon, ChevronLeft, ChevronRight, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface DateFieldProps {
  label?: string
  required?: boolean
  error?: string
  hint?: string
  /** القيمة الحالية بصيغة ISO (yyyy-mm-dd)، أو '' لعدم التحديد. */
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}

const MONTH_NAMES = [
  'يناير',
  'فبراير',
  'مارس',
  'أبريل',
  'مايو',
  'يونيو',
  'يوليو',
  'أغسطس',
  'سبتمبر',
  'أكتوبر',
  'نوفمبر',
  'ديسمبر',
]

const WEEKDAY_LABELS = ['أحد', 'اثنين', 'ثلاثاء', 'أربعاء', 'خميس', 'جمعة', 'سبت']

/** أول يوم أحد قبل (أو يساوي) اليوم الأول من الشهر — لبناء شبكة أسابيع كاملة (٦×٧). */
function gridStart(year: number, month: number): Date {
  const first = new Date(year, month, 1)
  first.setDate(first.getDate() - first.getDay())
  return first
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

function toIso(d: Date): string {
  const y = String(d.getFullYear()).padStart(4, '0')
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function fromIso(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return null
  const d = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  return Number.isNaN(d.getTime()) ? null : d
}

function formatDisplay(d: Date): string {
  const day = String(d.getDate()).padStart(2, '0')
  const month = String(d.getMonth() + 1).padStart(2, '0')
  return `${day}/${month}/${d.getFullYear()}`
}

/**
 * الهدف:
 * حقل تاريخ يُختار من تقويم منبثق (Popover) بدل الكتابة اليدوية —
 * سابقًا كان هذا الحقل عبارة عن ثلاثة صناديق أرقام (يوم/شهر/سنة) تُكتب
 * يدويًا لتفادي مشكلة ترتيب <input type="date"> الأصلي (كان يظهر أحيانًا
 * بترتيب معكوس لأنه يتبع إعدادات نظام تشغيل المتصفح لا اتجاه الصفحة)، لكن
 * الكتابة اليدوية غير مريحة وحقل السنة كان ضيقًا جدًا (مراجعة لاما
 * 2026-08-31). الحل هنا يحتفظ بحل مشكلة الترتيب (تقويم مبني يدويًا بترتيب
 * وتسميات عربية ثابتة، لا يعتمد على تنسيق المتصفح) لكن بواجهة اختيار
 * (Selection) بدل الكتابة (Typing).
 *
 * المسؤولية:
 * عرض/تعديل تاريخ واحد عبر تقويم شهري (تنقّل بالأسهم + قوائم شهر/سنة
 * سريعة)، وتحويله لصيغة ISO (yyyy-mm-dd) عبر onChange — نفس العقد
 * (Contract) بالضبط الذي كان عليه سابقًا، فلا حاجة لتعديل أي منطق
 * إرسال/تحقق (Zod) بالنماذج المستخدمة فيه.
 */
export function DateField({ label, required, error, hint, value, onChange, disabled }: DateFieldProps) {
  const [open, setOpen] = useState(false)
  const selected = fromIso(value)
  const today = new Date()
  const [viewYear, setViewYear] = useState(selected?.getFullYear() ?? today.getFullYear())
  const [viewMonth, setViewMonth] = useState(selected?.getMonth() ?? today.getMonth())
  const containerRef = useRef<HTMLDivElement>(null)

  // عند فتح التقويم، اعرض شهر التاريخ المحدَّد حاليًا (أو الشهر الحالي إن لم يوجد تحديد).
  useEffect(() => {
    if (!open) return
    setViewYear(selected?.getFullYear() ?? today.getFullYear())
    setViewMonth(selected?.getMonth() ?? today.getMonth())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (!open) return
    const onClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onClickOutside)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  function goPrevMonth() {
    if (viewMonth === 0) {
      setViewMonth(11)
      setViewYear((y) => y - 1)
    } else {
      setViewMonth((m) => m - 1)
    }
  }

  function goNextMonth() {
    if (viewMonth === 11) {
      setViewMonth(0)
      setViewYear((y) => y + 1)
    } else {
      setViewMonth((m) => m + 1)
    }
  }

  function pickDay(d: Date) {
    onChange(toIso(d))
    setOpen(false)
  }

  const currentRealYear = today.getFullYear()
  const yearOptions: number[] = []
  for (let y = currentRealYear + 20; y >= currentRealYear - 80; y--) yearOptions.push(y)

  const start = gridStart(viewYear, viewMonth)
  const cells: Date[] = []
  for (let i = 0; i < 42; i++) {
    const d = new Date(start)
    d.setDate(start.getDate() + i)
    cells.push(d)
  }

  return (
    <div className="flex flex-col gap-1.5" ref={containerRef}>
      {label && (
        <label className="text-sm font-medium text-text-primary">
          {label}
          {required && <span className="text-danger"> *</span>}
        </label>
      )}
      <div className="relative">
        <button
          type="button"
          disabled={disabled}
          onClick={() => setOpen((o) => !o)}
          aria-haspopup="dialog"
          aria-expanded={open}
          className={cn(
            'flex h-10 w-full items-center justify-between gap-2 rounded-sm border bg-bg-surface px-3 text-sm',
            'transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-brand-accent/40',
            error ? 'border-danger focus:border-danger' : 'border-border-default focus:border-brand-primary',
            disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:border-brand-primary/60',
          )}
        >
          <span className={selected ? 'text-text-primary' : 'text-text-muted'}>
            {selected ? formatDisplay(selected) : 'اختر التاريخ'}
          </span>
          <span className="flex items-center gap-1">
            {selected && !disabled && (
              <span
                role="button"
                tabIndex={-1}
                aria-label="مسح التاريخ"
                onClick={(e) => {
                  e.stopPropagation()
                  onChange('')
                }}
                className="rounded-sm p-0.5 text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              >
                <X size={14} />
              </span>
            )}
            <CalendarIcon size={16} className="text-text-muted" />
          </span>
        </button>

        <AnimatePresence>
          {open && (
            <motion.div
              initial={{ opacity: 0, scale: 0.97, y: -4 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.97, y: -4 }}
              transition={{ duration: 0.12 }}
              className="absolute start-0 top-full z-30 mt-1 w-72 max-w-[calc(100vw-2rem)] rounded-sm border border-border-default bg-bg-elevated p-3 shadow-lg"
            >
              <div className="mb-2 flex items-center justify-between gap-1">
                <button
                  type="button"
                  onClick={goPrevMonth}
                  aria-label="الشهر السابق"
                  className="rounded-sm p-1 text-text-muted transition-colors hover:bg-bg-surface hover:text-text-primary"
                >
                  <ChevronRight size={16} />
                </button>
                <div className="flex items-center gap-1">
                  <select
                    value={viewMonth}
                    onChange={(e) => setViewMonth(Number(e.target.value))}
                    className="rounded-sm border border-border-default bg-bg-surface px-1.5 py-1 text-xs text-text-primary focus:outline-none focus:ring-2 focus:ring-brand-accent/40"
                  >
                    {MONTH_NAMES.map((name, i) => (
                      <option key={i} value={i}>
                        {name}
                      </option>
                    ))}
                  </select>
                  <select
                    value={viewYear}
                    onChange={(e) => setViewYear(Number(e.target.value))}
                    className="rounded-sm border border-border-default bg-bg-surface px-1.5 py-1 text-xs text-text-primary focus:outline-none focus:ring-2 focus:ring-brand-accent/40"
                  >
                    {yearOptions.map((y) => (
                      <option key={y} value={y}>
                        {y}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  type="button"
                  onClick={goNextMonth}
                  aria-label="الشهر التالي"
                  className="rounded-sm p-1 text-text-muted transition-colors hover:bg-bg-surface hover:text-text-primary"
                >
                  <ChevronLeft size={16} />
                </button>
              </div>

              <div className="grid grid-cols-7 gap-y-1 text-center">
                {WEEKDAY_LABELS.map((w) => (
                  <span key={w} className="text-[11px] font-medium text-text-muted">
                    {w.slice(0, 2)}
                  </span>
                ))}
                {cells.map((d, i) => {
                  const inMonth = d.getMonth() === viewMonth
                  const isSelected = selected ? sameDay(d, selected) : false
                  const isToday = sameDay(d, today)
                  return (
                    <button
                      key={i}
                      type="button"
                      onClick={() => pickDay(d)}
                      className={cn(
                        'mx-auto flex h-8 w-8 items-center justify-center rounded-full text-xs transition-colors',
                        isSelected
                          ? 'bg-brand-primary font-semibold text-white'
                          : inMonth
                            ? 'text-text-primary hover:bg-bg-surface'
                            : 'text-text-muted/50 hover:bg-bg-surface',
                        !isSelected && isToday && 'ring-1 ring-brand-primary/60',
                      )}
                    >
                      {d.getDate()}
                    </button>
                  )
                })}
              </div>

              <div className="mt-2 flex items-center justify-between border-t border-border-default pt-2">
                <button
                  type="button"
                  onClick={() => {
                    onChange('')
                    setOpen(false)
                  }}
                  className="text-xs font-medium text-text-muted transition-colors hover:text-text-primary"
                >
                  مسح
                </button>
                <button
                  type="button"
                  onClick={() => pickDay(today)}
                  className="text-xs font-medium text-brand-primary transition-colors hover:text-brand-primary/80"
                >
                  اليوم
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      {error ? (
        <p className="text-xs font-medium text-danger">{error}</p>
      ) : hint ? (
        <p className="text-xs text-text-muted">{hint}</p>
      ) : null}
    </div>
  )
}
