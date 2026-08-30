import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Building2, Globe2, Layers, Pencil, Plus, Trash2 } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import {
  useCreateDocumentCategory,
  useDeleteDocumentCategory,
  useDocumentCategories,
  useUpdateDocumentCategory,
} from '@/hooks/useDocumentCategories'
import { useDepartments } from '@/hooks/useDepartments'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { TableSkeleton } from '@/components/ui/Skeleton'
import { ActionMenu } from '@/components/ui/ActionMenu'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/components/ui/Toast'
import {
  DocumentCategoryFormModal,
  type DocumentCategoryFormSubmitValues,
} from './DocumentCategoryFormModal'
import { extractErrorMessage } from '@/lib/utils'
import type { DocumentCategory } from '@/types'

/**
 * الهدف:
 * إدارة تصنيفات الوثائق (عامة/خاصة بإدارة) — صفحة منفصلة عن قائمة الوثائق
 * نفسها لأن صلاحياتها مختلفة تمامًا: كل عملية (إنشاء/تعديل/حذف) تُفحص حسب
 * نطاق التصنيف الفعلي (عام أو إدارة)لا صلاحية واحدة ثابتة — تماميًا مثل
 * _require_category_permission في الباك-إند (documents.py)، بما في ذلك
 * تجاوز super_admin التلقائي الموجود هناك تحديدًُا (بخلاف بقية صلاحيات
 * الوثائق الأخرى التي لا تُجاوَز تلقائيًا — راجعي التوثيق في
 * DocumentsPage.tsx للفرق).
 */
export function DocumentCategoriesPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { showToast } = useToast()

  const { data: categories, isLoading, isError, refetch } = useDocumentCategories()
  const { data: departments } = useDepartments()
  const createMutation = useCreateDocumentCategory()
  const updateMutation = useUpdateDocumentCategory()
  const deleteMutation = useDeleteDocumentCategory()

  const [formOpen, setFormOpen] = useState(false)
  const [editingCategory, setEditingCategory] = useState<DocumentCategory | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<DocumentCategory | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const isSuperAdmin = !!user?.role.is_super_admin
  const permissions = user?.permissions ?? []

  function hasScopePermission(action: 'create' | 'update' | 'delete', scope: 'global' | 'department') {
    return isSuperAdmin || permissions.includes(`document_categories.${action}_${scope}`)
  }

  const allowCreateGlobal = hasScopePermission('create', 'global')
  const allowCreateDepartment = hasScopePermission('create', 'department')
  const canCreate = allowCreateGlobal || allowCreateDepartment

  const grouped = useMemo(() => {
    const global = (categories ?? []).filter((c) => c.scope === 'global')
    const department = (categories ?? []).filter((c) => c.scope === 'department')
    return { global, department }
  }, [categories])

  function openCreateForm() {
    setEditingCategory(null)
    setFormError(null)
    setFormOpen(true)
  }

  function openEditForm(category: DocumentCategory) {
    setEditingCategory(category)
    setFormError(null)
    setFormOpen(true)
  }

  function handleSubmit(values: DocumentCategoryFormSubmitValues) {
    setFormError(null)
    if (editingCategory) {
      updateMutation.mutate(
        { categoryId: editingCategory.category_id, payload: { name: values.name } },
        {
          onSuccess: () => {
            setFormOpen(false)
            showToast('تم تحديث التصنيف بنجاح', 'success')
          },
          onError: (err) => setFormError(extractErrorMessage(err)),
        },
      )
    } else {
      createMutation.mutate(values, {
        onSuccess: () => {
          setFormOpen(false)
          showToast('تمت إضافة التصنيف بنجاح', 'success')
        },
        onError: (err) => setFormError(extractErrorMessage(err)),
      })
    }
  }

  function handleDelete() {
    if (!deleteTarget) return
    setDeleteError(null)
    deleteMutation.mutate(deleteTarget.category_id, {
      onSuccess: () => {
        setDeleteTarget(null)
        showToast('تم حذف التصنيف بنجاح', 'success')
      },
      onError: (err) => setDeleteError(extractErrorMessage(err)),
    })
  }

  function renderRow(category: DocumentCategory) {
    const canUpdateRow = hasScopePermission('update', category.scope)
    const canDeleteRow = hasScopePermission('delete', category.scope)
    const menuItems = [
      ...(canUpdateRow
        ? [{ label: 'تعديل', icon: <Pencil size={14} />, onClick: () => openEditForm(category) }]
        : []),
      ...(canDeleteRow
        ? [
            {
              label: 'حذف',
              icon: <Trash2 size={14} />,
              tone: 'danger' as const,
              onClick: () => {
                setDeleteError(null)
                setDeleteTarget(category)
              },
            },
          ]
        : []),
    ]
    return (
      <tr key={category.category_id} className="border-b border-border-default last:border-0">
        <td className="px-4 py-3 text-sm font-medium text-text-primary">{category.name}</td>
        <td className="px-4 py-3 text-sm text-text-muted">
          {category.scope === 'department'
            ? departments?.find((d) => d.dep_id === category.department_id)?.name ?? '—'
            : '—'}
        </td>
        <td className="w-12 px-4 py-3">{menuItems.length > 0 && <ActionMenu items={menuItems} />}</td>
      </tr>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-start gap-3">
          <button
            onClick={() => navigate('/documents')}
            className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="العودة إلى الوثائق"
          >
            <ArrowRight size={18} />
          </button>
          <div>
            <h1 className="text-xl font-bold text-text-primary">تصنيفات الوثائق</h1>
            <p className="mt-1 text-sm text-text-muted">تصنيفات عامة لكل الشركة أو خاصة بإدارة معيّنة</p>
          </div>
        </div>
        {canCreate && (
          <Button icon={<Plus size={16} />} onClick={openCreateForm}>
            إضافة تصنيف
          </Button>
        )}
      </div>

      {isLoading ? (
        <Card className="p-0">
          <TableSkeleton rows={5} cols={3} />
        </Card>
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : !categories || categories.length === 0 ? (
        <EmptyState
          icon={<Layers size={26} />}
          title="لا توجد تصنيفات بعد"
          description="ابدأ بإضافة أول تصنيف لتنظيم الوثائق"
          action={
            canCreate && (
              <Button size="sm" icon={<Plus size={14} />} onClick={openCreateForm}>
                إضافة تصنيف
              </Button>
            )
          }
        />
      ) : (
        <div className="flex flex-col gap-6">
          <Card className="p-0">
            <div className="flex items-center gap-2 border-b border-border-default px-4 py-3">
              <Globe2 size={15} className="text-brand-primary" />
              <h2 className="text-sm font-semibold text-text-primary">تصنيفات عامة</h2>
            </div>
            {grouped.global.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-text-muted">لا توجد تصنيفات عامة</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[480px] text-right text-sm">
                  <tbody>{grouped.global.map(renderRow)}</tbody>
                </table>
              </div>
            )}
          </Card>

          <Card className="p-0">
            <div className="flex items-center gap-2 border-b border-border-default px-4 py-3">
              <Building2 size={15} className="text-brand-primary" />
              <h2 className="text-sm font-semibold text-text-primary">تصنيفات خاصة بإدارة</h2>
            </div>
            {grouped.department.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-text-muted">لا توجد تصنيفات خاصة بإدارة</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[480px] text-right text-sm">
                  <thead>
                    <tr className="border-b border-border-default bg-table-header">
                      <th className="px-4 py-3 font-semibold text-text-secondary">الاسم</th>
                      <th className="px-4 py-3 font-semibold text-text-secondary">الإدارة</th>
                      <th className="w-12 px-4 py-3" />
                    </tr>
                  </thead>
                  <tbody>{grouped.department.map(renderRow)}</tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}

      <DocumentCategoryFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        category={editingCategory}
        departments={departments ?? []}
        allowGlobal={allowCreateGlobal}
        allowDepartment={allowCreateDepartment}
        onSubmit={handleSubmit}
        loading={createMutation.isPending || updateMutation.isPending}
        serverError={formError}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title="حذف التصنيف"
        description={`هل أنت متأكد من حذف "${deleteTarget?.name}"؟ لا يمكن حذف تصنيف لا تزال هناك وثائق مرتبطة به — يجب نقل أو حذف تلك الوثائق أولًا.`}
        confirmLabel="حذف التصنيف"
        loading={deleteMutation.isPending}
        errorMessage={deleteError}
      />
    </div>
  )
}
