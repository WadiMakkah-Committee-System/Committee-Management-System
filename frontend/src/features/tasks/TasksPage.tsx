import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  CheckCircle2,
  Eye,
  ListChecks,
  ListTodo,
  PauseCircle,
  Pencil,
  Plus,
  PlayCircle,
  Trash2,
  type LucideIcon,
} from 'lucide-react'
import { useCommittees } from '@/hooks/useCommittees'
import { useCreateTask, useDeleteTask, useTasks, useUpdateTask } from '@/hooks/useTasks'
import { useAuthStore } from '@/store/authStore'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { SearchInput } from '@/components/ui/SearchInput'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { CardSkeleton } from '@/components/ui/Skeleton'
import { StatCard } from '@/components/ui/StatCard'
import { TASK_STATUS_META } from '@/components/ui/StatusBadge'
import { ActionMenu } from '@/components/ui/ActionMenu'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/components/ui/Toast'
import { TaskFormModal, type TaskFormSubmitValues } from './TaskFormModal'
import { extractErrorMessage, formatDate } from '@/lib/utils'
import type { Task, TaskStatus } from '@/types'

/** أيقونة أكبر لكل حالة (شارة الحالة الصغيرة بـ StatusBadge.tsx بحجم 13px فقط، غير قابلة لإعادة التحجيم). */
const TASK_STATUS_ICON: Record<TaskStatus, LucideIcon> = {
  todo: ListTodo,
  in_progress: PlayCircle,
  on_hold: PauseCircle,
  completed: CheckCircle2,
}

/** نص الحالة الملوّن أسفل عنوان البطاقة — Tailwind يحتاج أسماء classes حرفية (لا يدعم `text-${tone}` الديناميكي). */
const TASK_STATUS_TEXT_CLASS: Record<TaskStatus, string> = {
  todo: 'text-neutral',
  in_progress: 'text-info',
  on_hold: 'text-warning',
  completed: 'text-success',
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
 * القديم). قائمة "⋮" (ActionMenu) تظهر فقط لمن يملك صلاحية إدارة المهمة
 * فعليًا (رئيسة اللجنة الفعلية لتلك اللجنة تحديدًا، أو سوبر أدمن) — نفس
 * منطق chairableCommittees أدناه المستخدم أصلًا لإنشاء المهام، لأن
 * create/update/delete غير مقيَّدة بالكائن نفسه بالباك-إند وتُمنح فعليًا
 * لدور الرئيس فقط (راجعي رأس task_service.py). العضو المكلَّف بمهمة
 * بلجنة لا يرأسها يشوف بطاقة للعرض فقط، بدون القائمة.
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
  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [editTarget, setEditTarget] = useState<Task | null>(null)
  const [editError, setEditError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Task | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const chairableCommittees = useMemo(() => {
    if (!committees || !user) return []
    if (user.role?.is_super_admin) return committees
    return committees.filter((c) => c.chair_user_id === user.user_id)
  }, [committees, user])

  const canCreateAnyTask = chairableCommittees.length > 0

  const manageableCommitteeIds = useMemo(
    () => new Set(chairableCommittees.map((c) => c.committee_id)),
    [chairableCommittees],
  )

  const filtered = useMemo(() => {
    if (!tasks) return []
    const q = search.trim().toLowerCase()
    if (!q) return tasks
    return tasks.filter((t) => t.title.toLowerCase().includes(q))
  }, [tasks, search])

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
            transition={{ duration: 0.25, delay: i * 0.05, ease: 'easeOut' }}
          >
            <StatCard label={stat.label} value={stat.value} icon={stat.icon} tone={stat.tone} />
          </motion.div>
        ))}
      </div>

      <SearchInput value={search} onChange={setSearch} placeholder="ابحث باسم المهمة..." />

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
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((task, i) => {
            const meta = TASK_STATUS_META[task.status]
            const StatusIcon = TASK_STATUS_ICON[task.status]
            const canManageTask = manageableCommitteeIds.has(task.committee_id)
            const isCompleted = task.status === 'completed'

            return (
              <motion.div
                key={task.task_id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2, delay: Math.min(i * 0.03, 0.3) }}
              >
                <Card
                  interactive
                  onClick={() => navigate(`/tasks/${task.task_id}`)}
                  style={{ backgroundColor: `var(--status-${meta.tone}-bg)` }}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm text-white"
                      style={{ backgroundColor: `var(--status-${meta.tone}-main)` }}
                    >
                      <StatusIcon size={17} />
                    </div>
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
                  <h3 className="mt-3 text-sm font-semibold text-text-primary">{task.title}</h3>
                  <p className={`mt-0.5 text-xs font-semibold ${TASK_STATUS_TEXT_CLASS[task.status]}`}>
                    {meta.label}
                  </p>
                  <p className="mt-3 text-xs text-text-secondary">
                    المسؤول: {task.assignee.first_name} {task.assignee.last_name}
                  </p>
                  <p className="mt-1 text-xs text-text-secondary">
                    التنفيذ: {formatDate(task.start_date)} — {formatDate(task.end_date)}
                  </p>
                </Card>
              </motion.div>
            )
          })}
        </div>
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
