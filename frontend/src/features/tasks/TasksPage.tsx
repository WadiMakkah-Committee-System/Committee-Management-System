import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Building2,
  CheckCircle2,
  Eye,
  ListChecks,
  ListTodo,
  Pencil,
  Plus,
  PlayCircle,
  Trash2,
} from 'lucide-react'
import { useCommittees } from '@/hooks/useCommittees'
import { useCreateTask, useDeleteTask, useTasks, useUpdateTask } from '@/hooks/useTasks'
import { useAuthStore } from '@/store/authStore'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Select'
import { SearchInput } from '@/components/ui/SearchInput'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { TableSkeleton } from '@/components/ui/Skeleton'
import { StatCard } from '@/components/ui/StatCard'
import { TASK_STATUS_META, TaskStatusBadge } from '@/components/ui/StatusBadge'
import { ActionMenu } from '@/components/ui/ActionMenu'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { Avatar } from '@/components/ui/Avatar'
import { useToast } from '@/components/ui/Toast'
import { TaskFormModal, type TaskFormSubmitValues } from './TaskFormModal'
import { cn, extractErrorMessage, formatDate } from '@/lib/utils'
import type { Task, TaskStatus } from '@/types'

/**
 * نسبة تقدّم تقريبية لكل حالة — لعرضها كشريط تقدّم بصفوف قائمة المهام
 * فقط (لا حقل progress فعلي بالباك-إند، Task.status هو مصدر الحقيقة
 * الوحيد). "معلّقة" تبقى عند نفس نسبة "قيد التنفيذ" لأنها تفريع مؤقت
 * عنها، بنفس مبدأ تبسيط TaskPipeline.tsx لأربع الحالات لثلاث محطات.
 */
const TASK_STATUS_PROGRESS: Record<TaskStatus, number> = {
  todo: 0,
  in_progress: 55,
  on_hold: 55,
  completed: 100,
}

/**
 * قائمة المهام — إنشاء مباشر من واجهة المهام فقط (بدون مهام مستخرجة من
 * اجتماع بالذكاء الاصطناعي — تُبنى لاحقًا). رئيس اللجنة يشوف كل مهام
 * لجانه، العضو العادي يشوف مهامه المسندة له فقط (يُحسم بالكامل بالباك-إند
 * — راجعي رأس task_service.list_tasks لعدم تكرار منطق النطاق هنا).
 *
 * تصميم البطاقات (بطلب صريح من Lujain، على غرار بطاقات "الأدوار
 * والصلاحيات"): خلفية البطاقة كاملة بتدرّج لون الحالة + أيقونة الحالة
 * بمربّع ملوّن بالزاوية، بدل خط علوي رفيع أو تلوين عشوائي (cardToneClass
 * القديم). قائمة "⋮" (ActionMenu) تظهر فقط لرئيسة اللجنة الفعلية لتلك
 * اللجنة تحديدًا (chair_user_id) — عمدًا بدون استثناء لسوبر أدمن: هذا
 * تحديدًا الفرق الموثَّق برأس Role.scope_for بالباك-إند ("لا يُستخدم
 * للتجاوز التلقائي للصلاحيات — قرار 2026-08-27")، فسوبر أدمن يشوف كل
 * المهام (tasks.view نطاقه all فعليًا) لكن ما يقدر يدير/ينشئ مهمة لأي
 * لجنة إلا لو كان رئيسها هو شخصيًا فعليًا (بطلب صريح من Lujain). العضو
 * المكلَّف بمهمة بلجنة لا يرأسها يشوف بطاقة للعرض فقط، بدون القائمة.
 *
 * اسم اللجنة يظهر على كل بطاقة (بطلب صريح من Lujain 2026-09-06) — يفيد
 * أي مستخدم عضو/رئيس في أكثر من لجنة واحدة (مثال: عضو بلجنة المشتريات
 * ولجنة الميزانية معًا). فلتر اللجنة وتبديل "الكل/مهامي" كلاهما يظهر
 * فقط عندما يكون فعليًا مفيدًا (تعدد لجان ظاهرة، أو وجود مهام غير مسندة
 * للمستخدم الحالي شخصيًا) — بيانات المهام الظاهرة فعليًا هي ما يقرر هذا،
 * لا الدور، لأن نفس الشرط ينطبق على رئيس اللجنة والأدمن والعضو متعدد
 * اللجان على حد سواء.
 */
export function TasksPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { data: tasks, isLoading, isError, refetch } = useTasks()
  const { data: committees } = useCommittees()
  const createMutation = useCreateTask()
  const updateMutation = useUpdateTask()
  const deleteMutation = useDeleteTask()
  const { showToast } = useToast()

  const [search, setSearch] = useState('')
  const [selectedCommitteeId, setSelectedCommitteeId] = useState('all')
  const [viewMode, setViewMode] = useState<'all' | 'mine'>('all')
  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [editTarget, setEditTarget] = useState<Task | null>(null)
  const [editError, setEditError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Task | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const chairableCommittees = useMemo(() => {
    if (!committees || !user) return []
    return committees.filter((c) => c.chair_user_id === user.user_id)
  }, [committees, user])

  const canCreateAnyTask = chairableCommittees.length > 0

  const manageableCommitteeIds = useMemo(
    () => new Set(chairableCommittees.map((c) => c.committee_id)),
    [chairableCommittees],
  )

  /** اسم اللجنة لكل معرّف — لعرضه على البطاقة، بغض النظر عن دور المستخدم فيها. */
  const committeeNameById = useMemo(() => {
    const map = new Map<string, string>()
    committees?.forEach((c) => map.set(c.committee_id, c.name))
    return map
  }, [committees])

  /** خيارات فلتر اللجنة — مبنية من اللجان الظاهرة فعليًا بمهام المستخدم، لا من كل لجان النظام. */
  const visibleCommitteeOptions = useMemo(() => {
    if (!tasks) return []
    const ids = Array.from(new Set(tasks.map((t) => t.committee_id)))
    return ids.map((id) => ({ value: id, label: committeeNameById.get(id) ?? 'لجنة غير معروفة' }))
  }, [tasks, committeeNameById])

  /** الفلتر يظهر فقط لو مهام المستخدم الظاهرة فعليًا موزّعة على أكثر من لجنة (رئيس/عضو/أدمن متعدد اللجان). */
  const showCommitteeFilter = visibleCommitteeOptions.length > 1

  /** تبديل "الكل/مهامي" مفيد فقط لو فيه مهام ظاهرة غير مسندة للمستخدم شخصيًا (رئيس لجنة أو أدمن). */
  const showViewToggle = useMemo(() => {
    if (!tasks || !user) return false
    return tasks.some((t) => t.assignee.user_id !== user.user_id)
  }, [tasks, user])

  const filtered = useMemo(() => {
    if (!tasks) return []
    let list = tasks
    if (selectedCommitteeId !== 'all') {
      list = list.filter((t) => t.committee_id === selectedCommitteeId)
    }
    if (viewMode === 'mine' && user) {
      list = list.filter((t) => t.assignee.user_id === user.user_id)
    }
    const q = search.trim().toLowerCase()
    if (q) {
      list = list.filter((t) => t.title.toLowerCase().includes(q))
    }
    return list
  }, [tasks, search, selectedCommitteeId, viewMode, user])

  const stats = useMemo(() => {
    const all = tasks ?? []
    return {
      total: all.length,
      todo: all.filter((t) => t.status === 'todo').length,
      inProgress: all.filter((t) => t.status === 'in_progress').length,
      completed: all.filter((t) => t.status === 'completed').length,
    }
  }, [tasks])

  function handleCreate(values: TaskFormSubmitValues) {
    setFormError(null)
    createMutation.mutate(values, {
      onSuccess: (created) => {
        setFormOpen(false)
        showToast('تم إنشاء المهمة بنجاح', 'success')
        navigate(`/tasks/${created.task_id}`)
      },
      onError: (err) => setFormError(extractErrorMessage(err)),
    })
  }

  function handleUpdate(values: TaskFormSubmitValues) {
    if (!editTarget) return
    setEditError(null)
    updateMutation.mutate(
      {
        taskId: editTarget.task_id,
        payload: { title: values.title, start_date: values.start_date, end_date: values.end_date },
      },
      {
        onSuccess: () => {
          setEditTarget(null)
          showToast('تم حفظ التعديلات', 'success')
        },
        onError: (err) => setEditError(extractErrorMessage(err)),
      },
    )
  }

  function handleDeleteConfirm() {
    if (!deleteTarget) return
    setDeleteError(null)
    deleteMutation.mutate(deleteTarget.task_id, {
      onSuccess: () => {
        setDeleteTarget(null)
        showToast('تم حذف المهمة', 'success')
      },
      onError: (err) => setDeleteError(extractErrorMessage(err)),
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-xl font-bold text-text-primary">المهام</h1>
          <p className="mt-1 text-sm text-text-muted">
            {canCreateAnyTask
              ? 'إسناد ومتابعة مهام اللجان التي ترأسها'
              : 'متابعة المهام المسندة إليك'}
          </p>
        </div>
        {canCreateAnyTask && (
          <Button
            icon={<Plus size={16} />}
            onClick={() => {
              setFormError(null)
              setFormOpen(true)
            }}
          >
            مهمة جديدة
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: 'إجمالي المهام', value: stats.total, icon: <ListChecks size={20} />, tone: 'brand' as const },
          { label: 'لم تبدأ', value: stats.todo, icon: <ListTodo size={20} />, tone: 'orange' as const },
          { label: 'قيد التنفيذ', value: stats.inProgress, icon: <PlayCircle size={20} />, tone: 'teal' as const },
          { label: 'مكتملة', value: stats.completed, icon: <CheckCircle2 size={20} />, tone: 'success' as const },
        ].map((stat, i) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            whileHover={{ y: -3 }}
            transition={{ duration: 0.25, delay: i * 0.05, ease: 'easeOut' }}
            className="transition-shadow duration-200 hover:shadow-md rounded-md"
          >
            <StatCard label={stat.label} value={stat.value} icon={stat.icon} tone={stat.tone} />
          </motion.div>
        ))}
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="w-full sm:max-w-sm">
          <SearchInput value={search} onChange={setSearch} placeholder="ابحث باسم المهمة..." />
        </div>
        {(showCommitteeFilter || showViewToggle) && (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            {showCommitteeFilter && (
              <div className="w-full sm:w-56">
                <Select
                  aria-label="فلتر اللجنة"
                  value={selectedCommitteeId}
                  onChange={(e) => setSelectedCommitteeId(e.target.value)}
                  options={[{ value: 'all', label: 'كل اللجان' }, ...visibleCommitteeOptions]}
                />
              </div>
            )}
            {showViewToggle && (
              <div
                role="tablist"
                aria-label="عرض المهام"
                className="inline-flex shrink-0 items-center gap-0.5 self-start rounded-sm border border-border-default bg-bg-surface p-0.5 sm:self-auto"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={viewMode === 'all'}
                  onClick={() => setViewMode('all')}
                  className={cn(
                    'rounded-xs px-3 py-1.5 text-xs font-semibold transition-colors',
                    viewMode === 'all'
                      ? 'bg-brand-primary text-white'
                      : 'text-text-muted hover:text-text-primary',
                  )}
                >
                  الكل
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={viewMode === 'mine'}
                  onClick={() => setViewMode('mine')}
                  className={cn(
                    'rounded-xs px-3 py-1.5 text-xs font-semibold transition-colors',
                    viewMode === 'mine'
                      ? 'bg-brand-primary text-white'
                      : 'text-text-muted hover:text-text-primary',
                  )}
                >
                  مهامي
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {isLoading ? (
        <Card className="overflow-hidden p-0">
          <TableSkeleton rows={6} cols={4} />
        </Card>
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<ListChecks size={26} />}
          title={search ? 'لا توجد نتائج مطابقة' : 'لا توجد مهام بعد'}
          description={
            search
              ? 'جرّب كلمات بحث مختلفة'
              : canCreateAnyTask
                ? 'ابدأ بإسناد أول مهمة للجنتك'
                : 'تظهر مهامك هنا فور إسنادها من رئيس اللجنة'
          }
          action={
            !search &&
            canCreateAnyTask && (
              <Button size="sm" icon={<Plus size={14} />} onClick={() => setFormOpen(true)}>
                مهمة جديدة
              </Button>
            )
          }
        />
      ) : (
        <Card className="p-0">
          <div className="hidden items-center gap-4 rounded-t-md border-b border-border-default bg-table-header-bg px-4 py-2.5 text-xs font-semibold text-text-muted sm:flex">
            <span className="flex-1">المهمة</span>
            <span className="w-36 shrink-0">المسؤول</span>
            <span className="w-32 shrink-0">التقدّم</span>
            <span className="w-28 shrink-0">الحالة</span>
          </div>
          <div className="divide-y divide-border-default">
            {filtered.map((task, i) => {
              const meta = TASK_STATUS_META[task.status]
              const canManageTask = manageableCommitteeIds.has(task.committee_id)
              const isCompleted = task.status === 'completed'
              const progress = TASK_STATUS_PROGRESS[task.status]

              return (
                <motion.div
                  key={task.task_id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2, delay: Math.min(i * 0.02, 0.3) }}
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(`/tasks/${task.task_id}`)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      navigate(`/tasks/${task.task_id}`)
                    }
                  }}
                  className="flex cursor-pointer flex-col gap-3 border-r-[3px] px-4 py-3.5 transition-colors hover:bg-table-hover-bg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-accent sm:flex-row sm:items-center sm:gap-4"
                  style={{ borderRightColor: `color-mix(in srgb, var(--status-${meta.tone}-main) 55%, transparent)` }}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-text-primary">{task.title}</p>
                    <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-secondary">
                      <span className="flex items-center gap-1.5">
                        <Building2 size={12} />
                        {committeeNameById.get(task.committee_id) ?? 'لجنة غير معروفة'}
                      </span>
                      <span className="text-text-muted">
                        {formatDate(task.start_date)} — {formatDate(task.end_date)}
                      </span>
                    </p>
                  </div>

                  <div className="flex shrink-0 items-center gap-2 sm:w-36">
                    <Avatar firstName={task.assignee.first_name} lastName={task.assignee.last_name} size={26} />
                    <span className="truncate text-xs font-medium text-text-secondary">
                      {task.assignee.first_name} {task.assignee.last_name}
                    </span>
                  </div>

                  <div className="flex shrink-0 items-center gap-2 sm:w-32">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-bg-elevated">
                      <motion.div
                        className="h-full rounded-full"
                        initial={{ width: 0 }}
                        animate={{ width: `${progress}%` }}
                        transition={{ duration: 0.6, delay: Math.min(i * 0.02, 0.3) + 0.1, ease: 'easeOut' }}
                        style={{ backgroundColor: `var(--status-${meta.tone}-main)` }}
                      />
                    </div>
                    <span className="w-8 shrink-0 text-left text-[11px] font-semibold tabular-nums text-text-muted">
                      {progress}%
                    </span>
                  </div>

                  <div className="flex shrink-0 items-center justify-between gap-2 sm:w-28 sm:justify-start">
                    <TaskStatusBadge status={task.status} />
                    {canManageTask && (
                      <div onClick={(e) => e.stopPropagation()}>
                        <ActionMenu
                          items={[
                            {
                              label: 'عرض التفاصيل',
                              icon: <Eye size={14} />,
                              onClick: () => navigate(`/tasks/${task.task_id}`),
                            },
                            {
                              label: 'تعديل',
                              icon: <Pencil size={14} />,
                              disabled: isCompleted,
                              onClick: () => {
                                setEditError(null)
                                setEditTarget(task)
                              },
                            },
                            {
                              label: 'حذف',
                              icon: <Trash2 size={14} />,
                              tone: 'danger',
                              disabled: isCompleted,
                              onClick: () => {
                                setDeleteError(null)
                                setDeleteTarget(task)
                              },
                            },
                          ]}
                        />
                      </div>
                    )}
                  </div>
                </motion.div>
              )
            })}
          </div>
        </Card>
      )}

      <TaskFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        committees={chairableCommittees}
        onSubmit={handleCreate}
        loading={createMutation.isPending}
        serverError={formError}
      />

      <TaskFormModal
        open={!!editTarget}
        onClose={() => setEditTarget(null)}
        committees={
          editTarget ? chairableCommittees.filter((c) => c.committee_id === editTarget.committee_id) : []
        }
        task={editTarget}
        onSubmit={handleUpdate}
        loading={updateMutation.isPending}
        serverError={editError}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDeleteConfirm}
        title="حذف المهمة"
        description={`سيتم حذف مهمة "${deleteTarget?.title}" نهائيًا. هل أنتِ متأكدة؟`}
        confirmLabel="حذف"
        loading={deleteMutation.isPending}
        errorMessage={deleteError}
      />
    </div>
  )
}
