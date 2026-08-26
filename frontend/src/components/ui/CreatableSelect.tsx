import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Loader2, Plus, Search, X } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface CreatableSelectOption {
  value: string
  label: string
}

interface CreatableSelectProps {
  label?: string
  required?: boolean
  error?: string
  /** نص العنصر الظاهر عند عدم وجود اختيار — لا Placeholder داخل القائمة نفسها. */
  placeholder?: string
  options: CreatableSelectOption[]
  /** القيمة الحالية (value من options)، أو '' لعدم وجود اختيار. */
  value: string
  onChange: (value: string) => void
  /**
   * تُستدعى عند اختيار "+ إضافة {نص البحث}" — يجب أن تُنشئ العنصر عبر الـ
   * API وترجع {value, label} الخاص به، ليُختار تلقائيًا فور إنشائه (بدون
   * مغادرة القائمة المنسدلة أو النموذج).
   */
  onCreate?: (name: string) => Promise<CreatableSelectOption>
  /** نص خيار "بدون" الاختياري في أعلى القائمة — لا يظهر إذا لم يُمرَّر (حقل إلزامي). */
  clearLabel?: string
  disabled?: boolean
}

/**
 * الهدف:
 * قائمة منسدلة بحث + إضافة مباشرة — أول استخدام لها: حقل "المسمى
 * الوظيفي" بنموذج المستخدم (إضافة مسمى جديد دون مغادرة النموذج، يُحفظ
 * فورًا بقائمة النظام ويُختار تلقائيًا للمستخدم الحالي). مصمَّمة لإعادة
 * الاستخدام لأي حقل مشابه مستقبلًا (بحث + إنشاء عنصر جديد بنفس النمط).
 *
 * المسؤولية:
 * عرض الخيارات الموجودة قابلة للبحث، وإتاحة إنشاء خيار جديد مباشرة من
 * نص البحث نفسه إذا لم يطابق أي خيار موجود تمامًا.
 *
 * التأثيرات الجانبية:
 * تستدعي onCreate (التي غالبًا تُنشئ صفًا جديدًا بقاعدة البيانات عبر الـ
 * API) عند اختيار خيار الإضافة — وليس عند مجرد الكتابة بحقل البحث.
 */
export function CreatableSelect({
  label,
  required,
  error,
  placeholder = 'اختر...',
  options,
  value,
  onChange,
  onCreate,
  clearLabel,
  disabled,
}: CreatableSelectProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const generatedId = useId()

  const selected = options.find((o) => o.value === value) ?? null

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return options
    return options.filter((o) => o.label.toLowerCase().includes(q))
  }, [options, search])

  const trimmedSearch = search.trim()
  const hasExactMatch = options.some((o) => o.label.toLowerCase() === trimmedSearch.toLowerCase())
  const canOfferCreate = !!onCreate && trimmedSearch.length > 0 && !hasExactMatch

  useEffect(() => {
    if (!open) return
    function onClickOutside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [open])

  async function handleCreate() {
    if (!onCreate || !trimmedSearch) return
    setCreating(true)
    setCreateError(null)
    try {
      const created = await onCreate(trimmedSearch)
      onChange(created.value)
      setOpen(false)
      setSearch('')
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'تعذّر الإضافة، حاول مرة أخرى')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="flex flex-col gap-1.5" ref={rootRef}>
      {label && (
        <label htmlFor={generatedId} className="text-sm font-medium text-text-primary">
          {label}
          {required && <span className="text-danger"> *</span>}
        </label>
      )}
      <div className="relative">
        <button
          id={generatedId}
          type="button"
          disabled={disabled}
          aria-haspopup="listbox"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          className={cn(
            'flex h-10 w-full items-center justify-between gap-2 rounded-sm border bg-bg-surface px-3 text-sm transition-colors',
            'focus:outline-none focus:ring-2 focus:ring-brand-accent/40',
            error ? 'border-danger focus:border-danger' : 'border-border-default focus:border-brand-primary',
            disabled && 'cursor-not-allowed opacity-60',
          )}
        >
          <span className={cn('truncate', selected ? 'text-text-primary' : 'text-text-muted')}>
            {selected ? selected.label : placeholder}
          </span>
          <span className="flex shrink-0 items-center gap-1">
            {selected && clearLabel !== undefined && !disabled && (
              <span
                role="button"
                tabIndex={-1}
                onClick={(e) => {
                  e.stopPropagation()
                  onChange('')
                }}
                className="rounded-full p-0.5 text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
                aria-label="إزالة الاختيار"
              >
                <X size={13} />
              </span>
            )}
            <ChevronDown size={15} className="text-text-muted" />
          </span>
        </button>

        {open && !disabled && (
          <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-sm border border-border-default bg-bg-elevated shadow-lg">
            <div className="relative border-b border-border-default">
              <Search size={14} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-text-muted" />
              <input
                autoFocus
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value)
                  setCreateError(null)
                }}
                placeholder="ابحث أو اكتب لإضافة جديد..."
                className="h-9 w-full bg-transparent pr-9 pl-3 text-sm text-text-primary placeholder:text-text-muted focus:outline-none"
              />
            </div>
            <div className="max-h-52 overflow-y-auto py-1">
              {clearLabel !== undefined && !search && (
                <button
                  type="button"
                  onClick={() => {
                    onChange('')
                    setOpen(false)
                  }}
                  className="flex w-full items-center justify-between px-3 py-2 text-right text-sm text-text-muted transition-colors hover:bg-bg-surface"
                >
                  {clearLabel}
                  {value === '' && <Check size={14} className="text-brand-primary" />}
                </button>
              )}
              {filtered.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => {
                    onChange(opt.value)
                    setOpen(false)
                    setSearch('')
                  }}
                  className="flex w-full items-center justify-between px-3 py-2 text-right text-sm text-text-primary transition-colors hover:bg-bg-surface"
                >
                  {opt.label}
                  {opt.value === value && <Check size={14} className="text-brand-primary" />}
                </button>
              ))}
              {filtered.length === 0 && !canOfferCreate && (
                <p className="px-3 py-3 text-center text-xs text-text-muted">لا توجد نتائج</p>
              )}
              {canOfferCreate && (
                <button
                  type="button"
                  disabled={creating}
                  onClick={handleCreate}
                  className="flex w-full items-center gap-2 border-t border-border-default px-3 py-2 text-right text-sm font-medium text-brand-primary transition-colors hover:bg-brand-primary/5 disabled:opacity-60"
                >
                  {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                  إضافة "{trimmedSearch}"
                </button>
              )}
              {createError && <p className="px-3 pb-2 text-xs font-medium text-danger">{createError}</p>}
            </div>
          </div>
        )}
      </div>
      {error && <p className="text-xs font-medium text-danger">{error}</p>}
    </div>
  )
}
