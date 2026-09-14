import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, Search, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface MultiCheckPickerProps<T> {
  items: T[]
  getId: (item: T) => string
  getLabel: (item: T) => string
  getSublabel?: (item: T) => string | null | undefined
  /**
   * تجميع اختياري قابل للطي (Accordion) — بلاغ من صاحبة المشروع
   * 2026-09-14 (تعديل على تصميم أول كان يعرض المجموعات كلها مفتوحة دفعة
   * وحدة): "خلي اللي ظاهر أسامي الإدارات، وإذا ضغطت على اسم الإدارة يطلع
   * لي أعضاءها، بيكون أرتب". الآن: بدون بحث نشط، تظهر أسماء المجموعات
   * فقط (بعدد أعضائها)، وتُفتَح كل مجموعة بالضغط عليها لعرض أعضائها.
   * بمجرد كتابة أي نص بالبحث، تُفتَح المجموعات المطابقة تلقائيًا (بحث
   * فعّال لا معنى لإخفاء نتائجه خلف طي).
   *
   * بلا هذا الخيار: قائمة مسطّحة كالسابق تمامًا (توافقًا خلفيًا مع بقية
   * الاستخدامات الحالية لهذا المكوّن — إدارات/لجان بنفس نموذج الوثيقة).
   */
  getGroupLabel?: (item: T) => string | null | undefined
  selected: string[]
  onChange: (next: string[]) => void
  searchPlaceholder?: string
  emptyText?: string
  error?: string
}

/**
 * الهدف:
 * منتقي عام قابل لإعادة الاستخدام (Generic) لاختيار عدة عناصر من قائمة
 * طويلة عبر Checkboxes قابلة للبحث، مع تجميع اختياري قابل للطي (Accordion)
 * — نفس فكرة MemberPicker في وحدة اللجان (features/committees/MemberPicker.tsx)
 * لكن مُجرَّدة من أي منطق خاص باللجان (رئيس اللجنة) لتصلح لأي نوع عناصر:
 * هنا تُستخدم 3 مرات في نموذج رفع/تعديل الوثيقة (إدارات/لجان/مستخدمون
 * محددون لنطاق الرؤية المركّب).
 *
 * المسؤولية:
 * تعرض حقل بحث نصي يفلتر items حسب getLabel/getSublabel، وقائمة
 * Checkboxes قابلة للتمرير (مجمَّعة وقابلة للطي إن مُرِّر getGroupLabel)،
 * مع شارات (Chips) قابلة للإزالة لما هو مُختار حاليًا أعلى القائمة.
 *
 * المدخلات:
 * - items: كل العناصر المتاحة للاختيار من بينها.
 * - getId/getLabel/getSublabel: كيف تُستخرج المعرّف والتسمية من كل عنصر.
 * - getGroupLabel: تجميع اختياري قابل للطي — راجعي التعليق أعلى الخاصية.
 * - selected: قائمة المعرّفات المختارة حاليًا (Controlled).
 * - onChange: يُستدعى بالقائمة الجديدة الكاملة بعد أي إضافة/إزالة.
 *
 * المخرجات: لا تُرجع شيئًا — عنصر واجهة بصري بالكامل (Controlled Component).
 *
 * التأثيرات الجانبية: لا تعدّل قاعدة بيانات ولا تستدعي API — عرض واختيار محلي فقط.
 */
export function MultiCheckPicker<T>({
  items,
  getId,
  getLabel,
  getSublabel,
  getGroupLabel,
  selected,
  onChange,
  searchPlaceholder = 'ابحث...',
  emptyText = 'لا توجد عناصر مطابقة',
  error,
}: MultiCheckPickerProps<T>) {
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const selectedSet = useMemo(() => new Set(selected), [selected])
  const isSearching = search.trim().length > 0

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return items
    return items.filter((item) => {
      const sub = getSublabel?.(item)
      return getLabel(item).toLowerCase().includes(q) || (sub ? sub.toLowerCase().includes(q) : false)
    })
  }, [items, search, getLabel, getSublabel])

  /** بدون getGroupLabel: مجموعة واحدة بعنوان فارغ — قائمة مسطّحة، لا طي. */
  const groups = useMemo(() => {
    if (!getGroupLabel) return [{ label: null as string | null, items: filtered }]
    const map = new Map<string, T[]>()
    for (const item of filtered) {
      const label = getGroupLabel(item)?.trim() || 'بدون إدارة'
      if (!map.has(label)) map.set(label, [])
      map.get(label)!.push(item)
    }
    return [...map.entries()]
      .sort(([a], [b]) => a.localeCompare(b, 'ar'))
      .map(([label, groupItems]) => ({ label, items: groupItems }))
  }, [filtered, getGroupLabel])

  function toggle(id: string) {
    if (selectedSet.has(id)) onChange(selected.filter((s) => s !== id))
    else onChange([...selected, id])
  }

  function toggleGroup(label: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(label)) next.delete(label)
      else next.add(label)
      return next
    })
  }

  const selectedItems = items.filter((item) => selectedSet.has(getId(item)))

  return (
    <div className="flex flex-col gap-2">
      <AnimatePresence initial={false}>
        {selectedItems.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18 }}
            className="flex flex-wrap gap-1.5 overflow-hidden"
          >
            {selectedItems.map((item) => (
              <motion.span
                key={getId(item)}
                layout
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ duration: 0.15 }}
                className="flex items-center gap-1.5 rounded-xs bg-brand-primary/10 py-1 pl-1 pr-2 text-xs font-medium text-brand-primary"
              >
                {getLabel(item)}
                <button
                  type="button"
                  onClick={() => toggle(getId(item))}
                  className="rounded-full p-0.5 transition-colors hover:bg-brand-primary/15"
                  aria-label={`إزالة ${getLabel(item)}`}
                >
                  <X size={12} />
                </button>
              </motion.span>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="relative">
        <Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-text-muted" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={searchPlaceholder}
          className="h-9 w-full rounded-sm border border-border-default bg-bg-surface pr-9 pl-3 text-sm text-text-primary placeholder:text-text-muted transition-colors focus:border-brand-primary focus:outline-none focus:ring-2 focus:ring-brand-accent/40"
        />
      </div>

      <div
        className={cn(
          'max-h-56 overflow-y-auto rounded-sm border transition-colors',
          error ? 'border-danger' : 'border-border-default',
        )}
      >
        {filtered.length === 0 ? (
          <p className="px-3 py-6 text-center text-xs text-text-muted">{emptyText}</p>
        ) : (
          groups.map((group) => {
            // بدون تجميع (label === null): قائمة مسطّحة مباشرة، بلا عنوان قابل للطي.
            if (group.label === null) {
              return group.items.map((item) => (
                <PickerRow
                  key={getId(item)}
                  item={item}
                  isChecked={selectedSet.has(getId(item))}
                  onToggle={() => toggle(getId(item))}
                  getLabel={getLabel}
                  getSublabel={getSublabel}
                />
              ))
            }

            const isOpen = isSearching || expanded.has(group.label)
            const selectedCount = group.items.filter((item) => selectedSet.has(getId(item))).length

            return (
              <div key={group.label} className="border-b border-border-default last:border-0">
                <button
                  type="button"
                  onClick={() => toggleGroup(group.label!)}
                  className="flex w-full items-center justify-between gap-2 bg-bg-elevated px-3 py-2 text-right transition-colors hover:bg-bg-app"
                >
                  <span className="flex items-center gap-2 text-xs font-bold text-text-primary">
                    {group.label}
                    <span className="rounded-full bg-bg-surface px-1.5 py-0.5 text-[10px] font-medium text-text-muted">
                      {group.items.length}
                    </span>
                    {selectedCount > 0 && (
                      <span className="rounded-full bg-brand-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-brand-primary">
                        {selectedCount} محدَّد
                      </span>
                    )}
                  </span>
                  <ChevronDown
                    size={14}
                    className={cn('shrink-0 text-text-muted transition-transform', isOpen && 'rotate-180')}
                  />
                </button>
                <AnimatePresence initial={false}>
                  {isOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.15 }}
                      className="overflow-hidden"
                    >
                      {group.items.map((item) => (
                        <PickerRow
                          key={getId(item)}
                          item={item}
                          isChecked={selectedSet.has(getId(item))}
                          onToggle={() => toggle(getId(item))}
                          getLabel={getLabel}
                          getSublabel={getSublabel}
                        />
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )
          })
        )}
      </div>
      {error && <p className="text-xs font-medium text-danger">{error}</p>}
    </div>
  )
}

function PickerRow<T>({
  item,
  isChecked,
  onToggle,
  getLabel,
  getSublabel,
}: {
  item: T
  isChecked: boolean
  onToggle: () => void
  getLabel: (item: T) => string
  getSublabel?: (item: T) => string | null | undefined
}) {
  const sub = getSublabel?.(item)
  return (
    <label
      className={cn(
        'flex cursor-pointer items-center gap-2.5 border-b border-border-default px-3 py-2 text-sm transition-colors last:border-0',
        'focus-within:bg-bg-elevated hover:bg-bg-elevated',
        isChecked && 'bg-brand-primary/5',
      )}
    >
      <input
        type="checkbox"
        checked={isChecked}
        onChange={onToggle}
        className="h-4 w-4 shrink-0 rounded-xs border-border-default text-brand-primary focus:ring-brand-accent/40"
      />
      <div className="min-w-0">
        <p className="truncate font-medium text-text-primary">{getLabel(item)}</p>
        {sub && <p className="truncate text-xs text-text-muted">{sub}</p>}
      </div>
    </label>
  )
}
