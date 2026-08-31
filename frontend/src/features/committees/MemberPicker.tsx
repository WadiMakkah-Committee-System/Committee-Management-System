import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Crown, Search, Users as UsersIcon, X } from 'lucide-react'
import { Avatar } from '@/components/ui/Avatar'
import { cn } from '@/lib/utils'
import type { User } from '@/types'

/** يُستخدم كمفتاح تجميع لمن لا تتوفر له إدارة (dep_id فارغ) — يُعرض دائمًا كآخر مجموعة. */
const UNASSIGNED_GROUP = 'بدون إدارة'

interface MemberPickerProps {
  users: User[]
  selected: string[]
  onChange: (next: string[]) => void
  /** معرّف العضو المختار ليكون رئيسًا للجنة — null قبل الاختيار. */
  chairId: string | null
  onChairChange: (userId: string) => void
  error?: string
  /** رسالة خطأ خاصة باختيار الرئيس (مستقلة عن خطأ اختيار الأعضاء). */
  chairError?: string
}

/**
 * منتقي الأعضاء المقترحين لطلب تشكيل اللجنة — قائمة قابلة للبحث ومجمّعة
 * حسب الإدارة (Department) مع Checkboxes، بدل Select عادي، لأن
 * proposed_member_ids قائمة متعددة (min_length=1 حسب
 * CommitteeFormationRequestCreate بالباك-إند). لا تعرض Label خاص بها —
 * يوفّره FormSection بصفحة النموذج المستدعية لتجنّب تكرار العنوان.
 *
 * بعد اختيار الأعضاء، يجب اختيار عضو واحد بالضبط ليكون "رئيس اللجنة"
 * (chair_user_id) — الدور هنا مرتبط باللجنة نفسها فقط (Committee Role
 * مؤقت)، وليس دورًا عامًا بالنظام (System Role) كما كان سابقًا بجدول
 * الأدوار العام؛ لهذا لا تُعرض له Checkbox عادية بل قسم منفصل بأزرار
 * Radio تسمح باختيار واحد فقط، ويُمسَح تلقائيًا إن أُزيل ذلك العضو من
 * قائمة الأعضاء المحددين (راجع toggle أدناه) — نفس القيد بالضبط مطبّق
 * بالباك-إند (committee_service._chair_must_be_a_proposed_member).
 */
export function MemberPicker({
  users,
  selected,
  onChange,
  chairId,
  onChairChange,
  error,
  chairError,
}: MemberPickerProps) {
  const [search, setSearch] = useState('')
  const selectedSet = useMemo(() => new Set(selected), [selected])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return users
    return users.filter(
      (u) =>
        `${u.first_name} ${u.last_name}`.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q) ||
        (u.department?.name.toLowerCase().includes(q) ?? false) ||
        (u.job_title?.name.toLowerCase().includes(q) ?? false),
    )
  }, [users, search])

  /** تجميع القائمة المفلترة حسب الإدارة — يحافظ على ترتيب الظهور الأصلي، ويدفع "بدون إدارة" للنهاية دائمًا. */
  const grouped = useMemo(() => {
    const map = new Map<string, User[]>()
    for (const u of filtered) {
      const key = u.department?.name ?? UNASSIGNED_GROUP
      const list = map.get(key)
      if (list) list.push(u)
      else map.set(key, [u])
    }
    return Array.from(map.entries()).sort((a, b) => {
      if (a[0] === UNASSIGNED_GROUP) return 1
      if (b[0] === UNASSIGNED_GROUP) return -1
      return 0
    })
  }, [filtered])

  function toggle(userId: string) {
    if (selectedSet.has(userId)) {
      onChange(selected.filter((id) => id !== userId))
      if (chairId === userId) onChairChange('')
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
                {chairId === u.user_id && <Crown size={11} className="shrink-0" aria-label="رئيس اللجنة" />}
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
          grouped.map(([groupName, groupUsers]) => (
            <div key={groupName}>
              <div className="sticky top-0 z-10 border-b border-border-default bg-bg-elevated px-3 py-1 text-[11px] font-bold text-text-muted">
                {groupName}
              </div>
              {groupUsers.map((u) => {
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
                      <p className="truncate text-xs text-text-muted">{u.job_title?.name || 'غير محدد'}</p>
                    </div>
                  </label>
                )
              })}
            </div>
          ))
        )}
      </div>
      {error && <p className="text-xs font-medium text-danger">{error}</p>}

      <AnimatePresence initial={false}>
        {selectedUsers.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18 }}
            className="overflow-hidden"
          >
            <div
              className={cn(
                'flex flex-col gap-2 rounded-sm border p-3 transition-colors',
                chairError ? 'border-danger' : 'border-border-default',
              )}
            >
              <div className="flex items-center gap-1.5">
                <Crown size={13} className="text-brand-primary" />
                <p className="text-xs font-bold text-text-secondary">
                  رئيس اللجنة<span className="text-danger"> *</span>
                </p>
              </div>
              <p className="text-xs text-text-muted">اختاري عضوًا واحدًا من الأعضاء المحددين أعلاه ليكون رئيسًا للجنة</p>
              <div className="flex flex-col gap-1">
                {selectedUsers.map((u) => (
                  <label
                    key={u.user_id}
                    className="flex cursor-pointer items-center gap-2.5 rounded-xs px-2 py-1.5 text-sm transition-colors hover:bg-bg-elevated"
                  >
                    <input
                      type="radio"
                      name="committee-chair"
                      checked={chairId === u.user_id}
                      onChange={() => onChairChange(u.user_id)}
                      className="h-4 w-4 shrink-0 border-border-default text-brand-primary focus:ring-brand-accent/40"
                    />
                    <span className="font-medium text-text-primary">
                      {u.first_name} {u.last_name}
                    </span>
                    {u.job_title?.name && <span className="text-xs text-text-muted">({u.job_title.name})</span>}
                  </label>
                ))}
              </div>
              {chairError && <p className="text-xs font-medium text-danger">{chairError}</p>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
