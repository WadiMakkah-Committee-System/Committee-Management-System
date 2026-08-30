import { useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, Clock3 } from 'lucide-react'
import { cn, PERMISSION_CATEGORY_LABELS, PERMISSION_CATEGORY_ORDER } from '@/lib/utils'
import type { Permission, PermissionScope } from '@/types'

/** تسميات نطاقات الوصول — راجعي db/migrations/0014 لتعريفها الكامل. */
const SCOPE_LABELS: Record<PermissionScope, string> = {
  own: 'بياناتي فقط',
  department: 'إدارتي فقط',
  all: 'كل البيانات',
}
const SCOPE_OPTIONS: PermissionScope[] = ['own', 'department', 'all']

interface PermissionsPickerProps {
  permissions: Permission[]
  selected: Set<string>
  onChange: (next: Set<string>) => void
  /**
   * نطاق الوصول لكل صلاحية محددة — مراجعة لاما 2026-08-30 (فصل الصلاحية
   * عن نطاق الوصول). اختياري: عند غيابه لا يظهر منتقي النطاق إطلاقًا
   * (توافقًا مع أي استخدام مستقبلي لا يحتاج نطاقًا).
   */
  scopes?: Record<string, PermissionScope>
  onScopeChange?: (code: string, scope: PermissionScope) => void
}

/**
 * منتقي الصلاحيات — 9 أقسام قابلة للطي/الفتح، كل قسم فيه Checkboxes مستقلة.
 * يمكن فتح أكثر من قسم في نفس الوقت واختيار صلاحيات من أكثر من قسم — لا
 * يوجد قيد "قسم واحد فقط مفتوح" إطلاقًا (متطلب صريح).
 */
export function PermissionsPicker({
  permissions,
  selected,
  onChange,
  scopes,
  onScopeChange,
}: PermissionsPickerProps) {
  const grouped = useMemo(() => {
    const byCategory = new Map<string, Permission[]>()
    for (const p of permissions) {
      const list = byCategory.get(p.category) ?? []
      list.push(p)
      byCategory.set(p.category, list)
    }
    return PERMISSION_CATEGORY_ORDER.filter((c) => byCategory.has(c)).map((category) => ({
      category,
      items: (byCategory.get(category) ?? []).sort((a, b) => a.sort_order - b.sort_order),
    }))
  }, [permissions])

  // الأقسام المفعّلة فعليًا (الإدارات/المستخدمون) مفتوحة افتراضيًا — الباقي مطوي.
  const [openCategories, setOpenCategories] = useState<Set<string>>(
    () => new Set(grouped.filter((g) => g.items[0]?.is_enforced).map((g) => g.category)),
  )

  function toggleCategoryOpen(category: string) {
    setOpenCategories((prev) => {
      const next = new Set(prev)
      if (next.has(category)) next.delete(category)
      else next.add(category)
      return next
    })
  }

  function togglePermission(code: string) {
    const next = new Set(selected)
    if (next.has(code)) next.delete(code)
    else next.add(code)
    onChange(next)
  }

  function toggleCategoryAll(items: Permission[]) {
    const allSelected = items.every((p) => selected.has(p.code))
    const next = new Set(selected)
    for (const p of items) {
      if (allSelected) next.delete(p.code)
      else next.add(p.code)
    }
    onChange(next)
  }

  return (
    <div className="flex flex-col gap-2">
      {grouped.map(({ category, items }) => {
        const isOpen = openCategories.has(category)
        const isEnforced = items[0]?.is_enforced ?? false
        const selectedCount = items.filter((p) => selected.has(p.code)).length
        const allSelected = selectedCount === items.length && items.length > 0

        return (
          <div key={category} className="overflow-hidden rounded-sm border border-border-default">
            <button
              type="button"
              onClick={() => toggleCategoryOpen(category)}
              className="flex w-full items-center justify-between gap-3 bg-bg-elevated px-4 py-3 text-right transition-colors hover:bg-table-hover"
            >
              <span className="flex items-center gap-2">
                <motion.span animate={{ rotate: isOpen ? 0 : -90 }} transition={{ duration: 0.15 }}>
                  <ChevronDown size={16} className="text-text-muted" />
                </motion.span>
                <span className="text-sm font-semibold text-text-primary">
                  {PERMISSION_CATEGORY_LABELS[category] ?? category}
                </span>
                {!isEnforced && (
                  <span className="flex items-center gap-1 rounded-xs bg-warning-bg px-1.5 py-0.5 text-[10px] font-semibold text-warning">
                    <Clock3 size={10} />
                    قريبًا
                  </span>
                )}
              </span>
              <span className="flex items-center gap-3">
                <span className="text-xs text-text-muted">
                  {selectedCount} / {items.length}
                </span>
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => {
                    e.stopPropagation()
                    toggleCategoryAll(items)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      e.stopPropagation()
                      toggleCategoryAll(items)
                    }
                  }}
                  className="text-xs font-semibold text-brand-primary hover:underline"
                >
                  {allSelected ? 'إلغاء الكل' : 'تحديد الكل'}
                </span>
              </span>
            </button>

            <AnimatePresence initial={false}>
              {isOpen && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.18, ease: 'easeOut' }}
                  className="overflow-hidden"
                >
                  <div className="grid grid-cols-1 gap-1 border-t border-border-default p-3 sm:grid-cols-2">
                    {items.map((p) => (
                      <label
                        key={p.code}
                        className={cn(
                          'flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm transition-colors hover:bg-bg-elevated',
                          selected.has(p.code) ? 'text-text-primary' : 'text-text-secondary',
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={selected.has(p.code)}
                          onChange={() => togglePermission(p.code)}
                          className="h-4 w-4 shrink-0 rounded-xs border-border-default text-brand-primary focus:ring-brand-accent/40"
                        />
                        <span className="flex-1">{p.label_ar}</span>
                        {scopes && onScopeChange && selected.has(p.code) && (
                          <select
                            value={scopes[p.code] ?? 'all'}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => onScopeChange(p.code, e.target.value as PermissionScope)}
                            className="shrink-0 rounded-xs border border-border-default bg-bg-surface px-1.5 py-0.5 text-xs text-text-secondary"
                          >
                            {SCOPE_OPTIONS.map((s) => (
                              <option key={s} value={s}>
                                {SCOPE_LABELS[s]}
                              </option>
                            ))}
                          </select>
                        )}
                      </label>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )
      })}
    </div>
  )
}
