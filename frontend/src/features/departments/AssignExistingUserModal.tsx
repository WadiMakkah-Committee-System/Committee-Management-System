import { useMemo, useState } from 'react'
import { Search, Users as UsersIcon } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { Avatar } from '@/components/ui/Avatar'
import { cn } from '@/lib/utils'
import type { User } from '@/types'

interface AssignExistingUserModalProps {
  open: boolean
  onClose: () => void
  /** كل المستخدمين بالنظام — يُستبعد منها من هو أصلاً بهذه الإدارة (candidates بالخارج). */
  candidates: User[]
  onAssign: (userId: string) => void
  loading?: boolean
  serverError?: string | null
}

/**
 * إضافة مستخدم **موجود مسبقًا** لهذه الإدارة — بديل لفتح نموذج تسجيل
 * مستخدم جديد بالكامل (قرار المستخدمة 2026-09-13: زر "إضافة مستخدم"
 * بصفحة تفاصيل الإدارة كان يفتح UserFormModal دائمًا، حتى لو المستخدم
 * المطلوب إضافته موجود أصلاً بالنظام بإدارة أخرى أو بدون إدارة).
 *
 * التنفيذ الفعلي لعملية النقل هو PATCH /users/{id} بحقل dep_id فقط —
 * نفس الـendpoint المستخدَم أصلاً بتعديل بيانات مستخدم (useUpdateUser)،
 * فلا حاجة لأي إضافة بالباك-إند. القائمة هنا بحث بسيط أحادي الاختيار،
 * وليست Multi-select كـMemberPicker (نضيف عضوًا واحدًا في كل مرة).
 */
export function AssignExistingUserModal({
  open,
  onClose,
  candidates,
  onAssign,
  loading,
  serverError,
}: AssignExistingUserModalProps) {
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

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

  function handleClose() {
    setSearch('')
    setSelectedId(null)
    onClose()
  }

  function handleAssign() {
    if (!selectedId) return
    onAssign(selectedId)
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="إضافة مستخدم موجود إلى الإدارة"
      description="ابحث عن مستخدم مسجَّل بالنظام مسبقًا ثم أضفه لهذه الإدارة — لإنشاء مستخدم جديد بالكامل استخدم صفحة المستخدمين."
      footer={
        <>
          <Button variant="secondary" onClick={handleClose}>
            إلغاء
          </Button>
          <Button onClick={handleAssign} disabled={!selectedId || loading} loading={loading}>
            إضافة إلى الإدارة
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {serverError && (
          <p className="rounded-sm border border-danger/30 bg-danger/5 px-3 py-2 text-xs font-medium text-danger">
            {serverError}
          </p>
        )}

        <div className="relative">
          <Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="ابحث بالاسم أو البريد الإلكتروني أو الإدارة الحالية..."
            className="h-9 w-full rounded-sm border border-border-default bg-bg-surface pr-9 pl-3 text-sm text-text-primary placeholder:text-text-muted transition-colors focus:border-brand-primary focus:outline-none focus:ring-2 focus:ring-brand-accent/40"
          />
        </div>

        <div className="max-h-72 overflow-y-auto rounded-sm border border-border-default">
          {filtered.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-8 text-text-muted">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-bg-elevated">
                <UsersIcon size={18} />
              </div>
              <p className="text-xs">لا يوجد مستخدمون مطابقون</p>
            </div>
          ) : (
            filtered.map((u) => {
              const isSelected = selectedId === u.user_id
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
                    type="radio"
                    name="assign-existing-user"
                    checked={isSelected}
                    onChange={() => setSelectedId(u.user_id)}
                    className="h-4 w-4 shrink-0 border-border-default text-brand-primary focus:ring-brand-accent/40"
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
            })
          )}
        </div>
      </div>
    </Modal>
  )
}
