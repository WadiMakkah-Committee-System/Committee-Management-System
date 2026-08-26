import { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { Briefcase, Pencil, Plus, Trash2 } from 'lucide-react'
import { useCreateJobTitle, useDeleteJobTitle, useJobTitles, useUpdateJobTitle } from '@/hooks/useJobTitles'
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
import { JobTitleFormModal } from './JobTitleFormModal'
import { cardToneClass, cn, extractErrorMessage, formatDate } from '@/lib/utils'
import type { JobTitle } from '@/types'

/**
 * صفحة إدارة المسميات الوظيفية — تبويب ثالث تحت "إدارة المستخدمين" (بعد
 * "المستخدمون" و"الأدوار والصلاحيات"). وحدة مستقلة تمامًا عن الأدوار —
 * قرار عمل موثّق: المسمى الوظيفي ليس إعادة استخدام لاسم الدور، بل يعكس
 * المنصب الفعلي للمستخدم (مثال: "مديرة تقنية المعلومات"). الحذف هنا فعلي
 * (DELETE)، وليس Soft Delete كالإدارات — الباك-إند يمنع حذف مسمى قيد
 * الاستخدام ويُظهر الخطأ هنا كما هو.
 */
export function JobTitlesPage() {
  const { data: jobTitles, isLoading, isError, refetch } = useJobTitles()
  const createMutation = useCreateJobTitle()
  const updateMutation = useUpdateJobTitle()
  const deleteMutation = useDeleteJobTitle()
  const { showToast } = useToast()

  const [search, setSearch] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editingTitle, setEditingTitle] = useState<JobTitle | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<JobTitle | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const filtered = useMemo(() => {
    if (!jobTitles) return []
    const q = search.trim().toLowerCase()
    if (!q) return jobTitles
    return jobTitles.filter((j) => j.name.toLowerCase().includes(q))
  }, [jobTitles, search])

  function openCreateForm() {
    setEditingTitle(null)
    setFormError(null)
    setFormOpen(true)
  }

  function openEditForm(jobTitle: JobTitle) {
    setEditingTitle(jobTitle)
    setFormError(null)
    setFormOpen(true)
  }

  function handleSubmit(values: { name: string }) {
    setFormError(null)
    if (editingTitle) {
      updateMutation.mutate(
        { jobTitleId: editingTitle.job_title_id, payload: values },
        {
          onSuccess: () => {
            setFormOpen(false)
            showToast('تم تحديث المسمى الوظيفي بنجاح', 'success')
          },
          onError: (err) => setFormError(extractErrorMessage(err)),
        },
      )
    } else {
      createMutation.mutate(values, {
        onSuccess: () => {
          setFormOpen(false)
          showToast('تم إضافة المسمى الوظيفي بنجاح', 'success')
        },
        onError: (err) => setFormError(extractErrorMessage(err)),
      })
    }
  }

  function handleDelete() {
    if (!deleteTarget) return
    setDeleteError(null)
    deleteMutation.mutate(deleteTarget.job_title_id, {
      onSuccess: () => {
        setDeleteTarget(null)
        showToast('تم حذف المسمى الوظيفي بنجاح', 'success')
      },
      onError: (err) => setDeleteError(extractErrorMessage(err)),
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-base font-bold text-text-primary">المسميات الوظيفية</h2>
          <p className="mt-1 text-sm text-text-muted">تُستخدم لعرض منصب المستخدم الفعلي بجانب اسمه في النظام</p>
        </div>
        <Button icon={<Plus size={16} />} onClick={openCreateForm}>
          إضافة مسمى وظيفي
        </Button>
      </div>

      <StatCard label="إجمالي المسميات الوظيفية" value={jobTitles?.length ?? 0} icon={<Briefcase size={20} />} tone="teal" />

      <SearchInput value={search} onChange={setSearch} placeholder="ابحث عن مسمى وظيفي..." />

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
          icon={<Briefcase size={26} />}
          title={search ? 'لا توجد نتائج مطابقة' : 'لا توجد مسميات وظيفية بعد'}
          description={search ? 'جرّب كلمات بحث مختلفة' : 'ابدأ بإضافة أول مسمى وظيفي في النظام'}
          action={
            !search && (
              <Button size="sm" icon={<Plus size={14} />} onClick={openCreateForm}>
                إضافة مسمى وظيفي
              </Button>
            )
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((jt, i) => (
            <motion.div
              key={jt.job_title_id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: Math.min(i * 0.03, 0.3) }}
            >
              <Card className={cn('flex h-full flex-col gap-3 transition-shadow hover:shadow-md', cardToneClass(i))}>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-sm bg-brand-primary/10 text-brand-primary">
                    <Briefcase size={18} />
                  </div>
                  <ActionMenu
                    items={[
                      { label: 'تعديل', icon: <Pencil size={14} />, onClick: () => openEditForm(jt) },
                      {
                        label: 'حذف',
                        icon: <Trash2 size={14} />,
                        tone: 'danger',
                        onClick: () => {
                          setDeleteError(null)
                          setDeleteTarget(jt)
                        },
                      },
                    ]}
                  />
                </div>
                <h3 className="text-sm font-semibold text-text-primary">{jt.name}</h3>
                <p className="mt-auto text-xs text-text-muted">أُضيف في {formatDate(jt.created_at)}</p>
              </Card>
            </motion.div>
          ))}
        </div>
      )}

      <JobTitleFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        jobTitle={editingTitle}
        onSubmit={handleSubmit}
        loading={createMutation.isPending || updateMutation.isPending}
        serverError={formError}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title="حذف المسمى الوظيفي"
        description={`هل أنت متأكد من حذف "${deleteTarget?.name}"؟ لا يمكن التراجع عن هذا الإجراء.`}
        confirmLabel="حذف المسمى الوظيفي"
        loading={deleteMutation.isPending}
        errorMessage={deleteError}
      />
    </div>
  )
}
