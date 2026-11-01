import { useMemo, useState } from 'react'
import { Search, Users as UsersIcon } from 'lucide-react'
import { Avatar } from '@/components/ui/Avatar'
import { cn } from '@/lib/utils'
import type { User } from '@/types'

/** مجموعة عرض واحدة بالقائمة — "بدون إدارة" (name=null) أو إدارة محددة. */
interface CandidateGroup {
  name: string | null
  users: User[]
}

/**
 * تُقسّم قائمة المرشّحين إلى مجموعات للعرض: "بدون إدارة" أولًا (الأسهل
 * إضافة مباشرة، بلا نقل)، ثم كل إدارة أخرى كمجموعة منفصلة تحتها بترتيب
 * أبجدي — طلب صريح من المستخدمة 2026-09-22 لتسهيل تمييز "إضافة" عن
 * "نقل" بصريًا قبل حتى فتح أي محدد. الفرز نفسه لا يغيّر مين يظهر
 * بالقائمة (نفس candidates/filtered بالخارج) — عرضي بحت.
 */
function groupCandidates(users: User[]): CandidateGroup[] {
  const withoutDepartment: User[] = []
  const byDepartment = new Map<string, { name: string; users: User[] }>()

  for (const u of users) {
    if (!u.department) {
      withoutDepartment.push(u)
      continue
    }
    const existing = byDepartment.get(u.department.dep_id)
    if (existing) {
      existing.users.push(u)
    } else {
      byDepartment.set(u.department.dep_id, { name: u.department.name, users: [u] })
    }
  }

  const departmentGroups = Array.from(byDepartment.values())
    .sort((a, b) => a.name.localeCompare(b.name, 'ar'))
    .map((g) => ({ name: g.name, users: g.users }))

  const groups: CandidateGroup[] = []
  if (withoutDepartment.length > 0) {
    groups.push({ name: null, users: withoutDepartment })
  }
  groups.push(...departmentGroups)
  return groups
}

interface DepartmentUserPickerProps {
  /** المستخدمون المتاحون للاختيار (المستدعي يستبعد من لا يصح اختياره). */
  candidates: User[]
  /** التحديد الحالي — مُتحكَّم به من المستدعي. */
  selectedIds: string[]
  onSelectedIdsChange: (ids: string[]) => void
}

/**
 * الهدف: قائمة اختيار متعدد لمستخدمي النظام عند إسنادهم لإدارة — بحث،
 * و"تحديد الكل"، وتجميع حسب الإدارة الحالية ("بدون إدارة" أولًا).
 *
 * المسؤولية: العرض والتحديد فقط — بلا أي استدعاء API ولا تأكيد نقل؛
 * المستدعي يتولى الحفظ وتأكيد نقل من هو بإدارة أخرى.
 *
 * المستخدِمون: AssignExistingUserModal (إضافة أعضاء لإدارة قائمة) وDepartmentFormModal
 * (تحديد الأعضاء من نفس نموذج إنشاء الإدارة — طلب صاحبة المشروع 2026-10-29).
 * استُخرجت من AssignExistingUserModal كما هي بلا تغيير سلوك، تفاديًا لتكرارها.
 *
 * حالة البحث داخلية، وتُصفَّر تلقائيًا لأن النافذة الحاوية تُزيل محتواها عند الإغلاق.
 */
export function DepartmentUserPicker({ candidates, selectedIds, onSelectedIdsChange }: DepartmentUserPickerProps) {
  const [search, setSearch] = useState('')
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return candidates
    return candidates.filter(
      (u) =>
        `${u.first_name} ${u.last_name}`.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q) ||
        (u.department?.name.toLowerCase().includes(q) ?? false),
    )
  }, [candidates, search])

  const groups = useMemo(() => groupCandidates(filtered), [filtered])

  const allFilteredSelected = filtered.length > 0 && filtered.every((u) => selectedSet.has(u.user_id))

  function toggle(userId: string) {
    onSelectedIdsChange(
      selectedIds.includes(userId) ? selectedIds.filter((id) => id !== userId) : [...selectedIds, userId],
    )
  }

  function toggleSelectAllFiltered() {
    if (allFilteredSelected) {
      const filteredIds = new Set(filtered.map((u) => u.user_id))
      onSelectedIdsChange(selectedIds.filter((id) => !filteredIds.has(id)))
    } else {
      onSelectedIdsChange(Array.from(new Set([...selectedIds, ...filtered.map((u) => u.user_id)])))
    }
  }

  return (
    <>
    <div className="relative">
      <Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-text-muted" />
      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="ابحث بالاسم أو البريد الإلكتروني أو الإدارة الحالية..."
        className="h-9 w-full rounded-sm border border-border-default bg-bg-surface pr-9 pl-3 text-sm text-text-primary placeholder:text-text-muted transition-colors focus:border-brand-primary focus:outline-none focus:ring-2 focus:ring-brand-accent/40"
      />
    </div>

    {filtered.length > 0 && (
      <div className="flex items-center justify-between">
        <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-text-secondary">
          <input
            type="checkbox"
            checked={allFilteredSelected}
            onChange={toggleSelectAllFiltered}
            className="h-3.5 w-3.5 shrink-0 rounded-xs border-border-default text-brand-primary focus:ring-brand-accent/40"
          />
          تحديد الكل{search.trim() ? ' (نتائج البحث)' : ''}
        </label>
        <span
          className={cn(
            'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold transition-colors',
            selectedIds.length > 0 ? 'bg-brand-primary/10 text-brand-primary' : 'bg-neutral-bg text-text-muted',
          )}
        >
          {selectedIds.length} محدد
        </span>
      </div>
    )}

    <div className="max-h-72 overflow-y-auto rounded-sm border border-border-default">
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-8 text-text-muted">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-bg-elevated">
            <UsersIcon size={18} />
          </div>
          <p className="text-xs">لا يوجد مستخدمون مطابقون</p>
        </div>
      ) : (
        groups.map((group) => (
          <div key={group.name ?? '__no_department__'}>
            <p className="sticky top-0 border-b border-border-default bg-bg-elevated px-3 py-1.5 text-[11px] font-semibold text-text-secondary">
              {group.name ?? 'بدون إدارة'} ({group.users.length})
            </p>
            {group.users.map((u) => {
              const isSelected = selectedSet.has(u.user_id)
              return (
                <label
                  key={u.user_id}
                  className={cn(
                    'flex cursor-pointer items-center gap-2.5 border-b border-border-default px-3 py-2.5 text-sm transition-colors last:border-0',
                    'hover:bg-bg-elevated',
                    isSelected && 'bg-brand-primary/5',
                  )}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggle(u.user_id)}
                    className="h-4 w-4 shrink-0 rounded-xs border-border-default text-brand-primary focus:ring-brand-accent/40"
                  />
                  <Avatar firstName={u.first_name} lastName={u.last_name} />
                  <div className="min-w-0">
                    <p className="truncate font-medium text-text-primary">
                      {u.first_name} {u.last_name}
                    </p>
                    <p className="truncate text-xs text-text-muted">
                      {u.email}
                      {u.department?.name ? ` · ${u.department.name} حاليًا` : ' · بدون إدارة حاليًا'}
                    </p>
                  </div>
                </label>
              )
            })}
          </div>
        ))
      )}
    </div>
    </>
  )
}
