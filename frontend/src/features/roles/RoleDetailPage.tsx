import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowRight, KeySquare, Pencil, ShieldQuestion, Trash2, Users2 } from 'lucide-react'
import { useDeleteRole, useRoles, useUpdateRole, useCreateRole } from '@/hooks/useRoles'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { StatCard } from '@/components/ui/StatCard'
import { ErrorState } from '@/components/ui/ErrorState'
import { Skeleton } from '@/components/ui/Skeleton'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/components/ui/Toast'
import { RoleFormModal } from './RoleFormModal'
import {
  PERMISSION_CATEGORY_LABELS,
  PERMISSION_CATEGORY_ORDER,
  extractErrorMessage,
  roleLabel,
} from '@/lib/utils'
import type { RoleCreatePayload, RoleUpdatePayload } from '@/types'

/**
 * صفحة تفاصيل دور واحد — تُفتح بالنقر على بطاقة الدور بتبويب "الأدوار
 * والصلاحيات" (نمط DepartmentDetailPage تمامًا). قائمة "..." على البطاقة
 * تبقى مسارًا ثانيًا مستقلًا للتعديل/الحذف السريع دون فتح هذه الصفحة —
 * كلا المسارين يعملان بالتوازي (قرار عمل موثّق: لا إزالة لأي مسار قديم).
 *
 * قرار عمل موثّق: الحماية عن الأدوار النظامية الخمسة فُكّت بالكامل —
 * زرّا "تعديل" و"حذف" هنا يعملان بلا أي استثناء لـ is_system؛ الحارس
 * الوحيد المتبقي (عدم وجود مستخدمين مرتبطين بالدور) مفروض بالباك-إند
 * ويظهر كخطأ عادي هنا إن انتُهك.
 */
export function RoleDetailPage() {
  const { roleId } = useParams<{ roleId: string }>()
  const navigate = useNavigate()
  const { data: roles, isLoading, isError, refetch } = useRoles()
  const createMutation = useCreateRole()
  const updateMutation = useUpdateRole()
  const deleteMutation = useDeleteRole()
  const { showToast } = useToast()

  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const role = useMemo(() => roles?.find((r) => r.role_id === roleId) ?? null, [roles, roleId])

  const grouped = useMemo(() => {
    if (!role) return []
    const byCategory = new Map<string, typeof role.permissions>()
    for (const p of role.permissions) {
      const list = byCategory.get(p.category) ?? []
      list.push(p)
      byCategory.set(p.category, list)
    }
    return PERMISSION_CATEGORY_ORDER.filter((c) => byCategory.has(c)).map((category) => ({
      category,
      items: (byCategory.get(category) ?? []).sort((a, b) => a.sort_order - b.sort_order),
    }))
  }, [role])

  function handleEdit(values: RoleUpdatePayload | RoleCreatePayload) {
    if (!role) return
    setFormError(null)
    updateMutation.mutate(
      { roleId: role.role_id, payload: values as RoleUpdatePayload },
      {
        onSuccess: () => {
          setFormOpen(false)
          showToast('تم تحديث الدور بنجاح', 'success')
        },
        onError: (err) => setFormError(extractErrorMessage(err)),
      },
    )
  }

  function handleDelete() {
    if (!role) return
    setDeleteError(null)
    deleteMutation.mutate(role.role_id, {
      onSuccess: () => {
        setDeleteOpen(false)
        showToast('تم حذف الدور بنجاح', 'success')
        navigate('/users/roles')
      },
      onError: (err) => setDeleteError(extractErrorMessage(err)),
    })
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <Skeleton className="h-64" />
      </div>
    )
  }

  if (isError || !role) {
    return <ErrorState onRetry={() => refetch()} />
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-start gap-3">
          <button
            onClick={() => navigate('/users/roles')}
            className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="العودة إلى الأدوار والصلاحيات"
          >
            <ArrowRight size={18} />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-text-primary">{roleLabel(role)}</h1>
              {role.is_system && (
                <span className="rounded-xs bg-neutral-bg px-1.5 py-0.5 text-[10px] font-semibold text-neutral">
                  نظامي
                </span>
              )}
            </div>
            <p className="mt-1 text-sm text-text-muted">{role.description || 'لا يوجد وصف'}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            icon={<Pencil size={16} />}
            onClick={() => {
              setFormError(null)
              setFormOpen(true)
            }}
          >
            تعديل
          </Button>
          <Button
            variant="danger"
            icon={<Trash2 size={16} />}
            onClick={() => {
              setDeleteError(null)
              setDeleteOpen(true)
            }}
          >
            حذف
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <StatCard label="عدد الصلاحيات" value={role.permission_count} icon={<KeySquare size={20} />} tone="brand" />
        <StatCard label="عدد المستخدمين المرتبطين" value={role.user_count} icon={<Users2 size={20} />} tone="purple" />
      </div>

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <ShieldQuestion size={15} />
            الصلاحيات الممنوحة لهذا الدور
          </h2>
        </div>
        <div className="flex flex-col gap-4 p-4">
          {grouped.length === 0 ? (
            <p className="py-6 text-center text-sm text-text-muted">لا توجد صلاحيات ممنوحة لهذا الدور</p>
          ) : (
            grouped.map((g) => (
              <div key={g.category} className="flex flex-col gap-2">
                <p className="text-xs font-bold uppercase tracking-wide text-text-secondary">
                  {PERMISSION_CATEGORY_LABELS[g.category] ?? g.category}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {g.items.map((p) => (
                    <span
                      key={p.permission_id}
                      className="rounded-xs bg-brand-primary/10 px-2 py-1 text-xs font-medium text-brand-primary"
                    >
                      {p.label_ar}
                    </span>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </Card>

      <RoleFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        role={role}
        onSubmitCreate={handleEdit}
        onSubmitEdit={handleEdit}
        loading={createMutation.isPending || updateMutation.isPending}
        serverError={formError}
      />

      <ConfirmDialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onConfirm={handleDelete}
        title="حذف الدور"
        description={`هل أنت متأكد من حذف دور "${roleLabel(role)}"؟ لا يمكن التراجع عن هذا الإجراء.`}
        confirmLabel="حذف الدور"
        loading={deleteMutation.isPending}
        errorMessage={deleteError}
      />
    </div>
  )
}
