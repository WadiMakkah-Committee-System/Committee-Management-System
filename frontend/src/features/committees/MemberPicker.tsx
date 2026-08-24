import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Search, Users as UsersIcon, X } from 'lucide-react'
import { Avatar } from '@/components/ui/Avatar'
import { cn } from '@/lib/utils'
import type { User } from '@/types'

interface MemberPickerProps {
  users: User[]
  selected: string[]
  onChange: (next: string[]) => void
  error?: string
}

/**
 * منتقي الأعضاء المقترحين لطلب تشكيل اللجنة — قائمة قابلة للبحث مع
 * Checkboxes، بدل Select عادي، لأن proposed_member_ids قائمة متعددة
 * (min_length=1 حسب CommitteeFormationRequestCreate بالباك-إند). لا تعرض
 * Label خاص بها — يوفّره FormSection بصفحة النموذج المستدعية لتجنّب
 * تكرار العنوان.
 */
export function MemberPicker({ users, selected, onChange, error }: MemberPickerProps) {
  const [search, setSearch] = useState('')
  const selectedSet = useMemo(() => new Set(selected), [selected])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return users
    return users.filter(
      (u) =>
        `${u.first_name} ${u.last_name}`.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q),
    )
  }, [users, search])

  function toggle(userId: string) {
    if (selectedSet.has(userId)) {
      onChange(selected.filter((id) => id !== userId))
    } else {
      onChange([...selected, userId])
    }
  }

  const selectedUsers = users.filter((u) => selectedSet.has(u.user_id))

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <p className="text-xs text-text-muted">اختاري عضوًا واحدًا على الأقل من القائمة أدناه</p>
        <span
          className={cn(
            'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold transition-colors',
            selectedUsers.length > 0 ? 'bg-brand-primary/10 text-brand-primary' : 'bg-neutral-bg text-text-muted',
          )}
        >
          {selectedUsers.length} محدد
        </span>
      </div>

      <AnimatePresence initial={false}>
        {selectedUsers.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18 }}
            className="flex flex-wrap gap-1.5 overflow-hidden"
          >
            {selectedUsers.map((u) => (
              <motion.span
                key={u.user_id}
                layout
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ duration: 0.15 }}
                className="flex items-center gap-1.5 rounded-xs bg-brand-primary/10 py-1 pl-1 pr-2 text-xs font-medium text-brand-primary"
              >
                {u.first_name} {u.last_name}
                <button
                  type="button"
                  onClick={() => toggle(u.user_id)}
                  className="rounded-full p-0.5 transition-colors hover:bg-brand-primary/15"
                  aria-label={`إزالة ${u.first_name} ${u.last_name}`}
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
          placeholder="ابحث بالاسم أو البريد الإلكتروني..."
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
          <div className="flex flex-col items-center gap-2 py-8 text-text-muted">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-bg-elevated">
              <UsersIcon size={18} />
            </div>
            <p className="text-xs">لا يوجد مستخدمون مطابقون</p>
          </div>
        ) : (
          filtered.map((u) => {
            const isChecked = selectedSet.has(u.user_id)
            return (
              <label
                key={u.user_id}
                className={cn(
                  'flex cursor-pointer items-center gap-2.5 border-b border-border-default px-3 py-2 text-sm transition-colors last:border-0',
                  'focus-within:bg-bg-elevated hover:bg-bg-elevated',
                  isChecked && 'bg-brand-primary/5',
                )}
              >
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => toggle(u.user_id)}
                  className="h-4 w-4 shrink-0 rounded-xs border-border-default text-brand-primary focus:ring-brand-accent/40"
                />
                <Avatar firstName={u.first_name} lastName={u.last_name} />
                <div className="min-w-0">
                  <p className="truncate font-medium text-text-primary">
                    {u.first_name} {u.last_name}
                  </p>
                  <p className="truncate text-xs text-text-muted">{u.email}</p>
                </div>
              </label>
            )
          })
        )}
      </div>
      {error && <p className="text-xs font-medium text-danger">{error}</p>}
    </div>
  )
}
