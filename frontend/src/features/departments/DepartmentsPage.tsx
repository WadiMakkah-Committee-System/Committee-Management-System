import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Building2, FileText, Pencil, Plus, Trash2, UserRound } from 'lucide-react'
import {
  useCreateDepartment,
  useDeleteDepartment,
  useDepartments,
  useUpdateDepartment,
} from '@/hooks/useDepartments'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { SearchInput } from '@/components/ui/SearchInput'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { CardSkeleton } from '@/components/ui/Skeleton'
import { ActionMenu } from '@/components/ui/ActionMenu'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { StatCard } from '@/components/ui/StatCard'
import { useToast } from '@/components/ui/Toast'
import { DepartmentFormModal } from './DepartmentFormModal'
import { cardToneClass, cn, extractErrorMessage, formatDate } from '@/lib/utils'
import type { Department } from '@/types'

export function DepartmentsPage() {
  const navigate = useNavigate()
  const { data: departments, isLoading, isError, refetch } = useDepartments()
  const createMutation = useCreateDepartment()
  const updateMutation = useUpdateDepartment()
  const deleteMutation = useDeleteDepartment()
  const { showToast } = useToast()

  const [search, setSearch] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editingDept, setEditingDept] = useState<Department | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Department | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const filtered = useMemo(() => {
    if (!departments) return []
    const q = search.trim().toLowerCase()
    if (!q) return departments
    return departments.filter(
      (d) => d.name.toLowerCase().includes(q) || d.description?.toLowerCase().includes(q),
    )
  }, [departments, search])

  function openCreateForm() {
    setEditingDept(null)
    setFormError(null)
    setFormOpen(true)
  }

  function openEditForm(dept: Department) {
    setEditingDept(dept)
    setFormError(null)
    setFormOpen(true)
  }

  function handleSubmit(values: { name: string; code: string; description: string | null; manager_user_id: string }) {
    setFormError(null)
    if (editingDept) {
      updateMutation.mutate(
        { depId: editingDept.dep_id, payload: values },
        {
          onSuccess: () => {
            setFormOpen(false)
            showToast('تم تحديث بيانات الإدارة بنجاح', 'success')
          },
          onError: (err) => setFormError(extractErrorMessage(err)),
        },
      )
    } else {
      createMutation.mutate(values, {
        onSuccess: () => {
          setFormOpen(false)
          showToast('تم إضافة الإدارة بنجاح', 'success')
        },
        onError: (err) => setFormError(extractErrorMessage(err)),
      })
    }
  }

  function handleDelete() {
    if (!deleteTarget) return
    setDeleteError(null)
    deleteMutation.mutate(deleteTarget.dep_id, {
      onSuccess: () => {
        setDeleteTarget(null)
        showToast('تم حذف الإدارة بنجاح', 'success')
      },
      onError: (err) => setDeleteError(extractErrorMessage(err)),
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-xl font-bold text-text-primary">الإدارات</h1>
          <p className="mt-1 text-sm text-text-muted">إدارة الوحدات التنظيمية في الشركة</p>
        </div>
        <Button icon={<Plus size={16} />} onClick={openCreateForm}>
          إضافة إدارة
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="إجمالي الإدارات" value={departments?.length ?? 0} icon={<Building2 size={20} />} tone="purple" />
        <StatCard
          label="إدارات بوصف مكتمل"
          value={departments?.filter((d) => !!d.description).length ?? 0}
          icon={<FileText size={20} />}
          tone="teal"
        />
      </div>

      <SearchInput value={search} onChange={setSearch} placeholder="ابحث باسم الإدارة أو الوصف..." />

      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Building2 size={26} />}
          title={search ? 'لا توجد نتائج مطابقة' : 'لا توجد إدارات بعد'}
          description={search ? 'جرّب كلمات بحث مختلفة' : 'ابدأ بإضافة أول إدارة في النظام'}
          action={
            !search && (
              <Button size="sm" icon={<Plus size={14} />} onClick={openCreateForm}>
                إضافة إدارة
              </Button>
            )
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((dept, i) => (
            <motion.div
              key={dept.dep_id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: Math.min(i * 0.03, 0.3) }}
            >
              <Card
                onClick={() => navigate(`/departments/${dept.dep_id}`)}
                className={cn(
                  'flex h-full cursor-pointer flex-col gap-3 transition-shadow hover:shadow-md',
                  cardToneClass(i),
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-sm bg-brand-primary/10 text-brand-primary">
                    <Building2 size={18} />
                  </div>
                  <div onClick={(e) => e.stopPropagation()}>
                    <ActionMenu
                      items={[
                        { label: 'تعديل', icon: <Pencil size={14} />, onClick: () => openEditForm(dept) },
                        {
                          label: 'حذف',
                          icon: <Trash2 size={14} />,
                          tone: 'danger',
                          onClick: () => {
                            setDeleteError(null)
                            setDeleteTarget(dept)
                          },
                        },
                      ]}
                    />
                  </div>
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold text-text-primary">{dept.name}</h3>
                    {dept.code && (
                      <span className="rounded-xs bg-bg-elevated px-1.5 py-0.5 text-[10px] font-semibold text-text-muted">
                        {dept.code}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 line-clamp-2 text-sm text-text-muted">
                    {dept.description || 'لا يوجد وصف'}
                  </p>
                </div>
                {dept.manager && (
                  <p className="flex items-center gap-1.5 text-xs text-text-secondary">
                    <UserRound size={12} />
                    {dept.manager.first_name} {dept.manager.last_name}
                  </p>
                )}
                <p className="mt-auto text-xs text-text-muted">أُنشئت في {formatDate(dept.created_at)}</p>
              </Card>
            </motion.div>
          ))}
        </div>
      )}

      <DepartmentFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        department={editingDept}
        onSubmit={handleSubmit}
        loading={createMutation.isPending || updateMutation.isPending}
        serverError={formError}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title="حذف الإدارة"
        description={`هل أنت متأكد من حذف "${deleteTarget?.name}"؟ لا يمكن التراجع عن هذا الإجراء.`}
        confirmLabel="حذف الإدارة"
        loading={deleteMutation.isPending}
        errorMessage={deleteError}
      />
    </div>
  )
}
