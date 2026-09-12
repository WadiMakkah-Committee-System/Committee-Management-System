import { useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  AlertTriangle,
  ArrowRight,
  CalendarRange,
  History,
  ListChecks,
  Pencil,
  RefreshCw,
  Repeat,
  Trash2,
  UserCheck,
  UserPlus,
} from 'lucide-react'
import {
  useDeleteTask,
  useReassignTask,
  useTaskActivity,
  useTaskDetail,
  useUpdateTask,
  useUpdateTaskStatus,
} from '@/hooks/useTasks'
import { useCommitteeDetail } from '@/hooks/useCommittees'
import { useAuthStore } from '@/store/authStore'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { ErrorState } from '@/components/ui/ErrorState'
import { Skeleton, TableSkeleton } from '@/components/ui/Skeleton'
import { Avatar } from '@/components/ui/Avatar'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { ActionMenu } from '@/components/ui/ActionMenu'
import { Modal } from '@/components/ui/Modal'
import {
  TASK_STATUS_META,
  TaskOverdueBadge,
  TaskPriorityBadge,
  TaskStatusBadge,
  isTaskOverdue,
} from '@/components/ui/StatusBadge'
import { useToast } from '@/components/ui/Toast'
import { TaskFormModal, type TaskFormSubmitValues } from './TaskFormModal'
import { TaskPipeline } from './TaskPipeline'
import { cn, extractErrorMessage, formatDate, formatDateTime, getInitials } from '@/lib/utils'
import type { TaskActivityEntry, TaskStatus } from '@/types'

const STATUS_OPTIONS: { value: TaskStatus; label: string }[] = [
  { value: 'todo', label: 'لم تبدأ' },
  { value: 'in_progress', label: 'قيد التنفيذ' },
  { value: 'on_hold', label: 'معلّقة' },
  { value: 'completed', label: 'مكتملة' },
]

/** أيقونة/لون كل نوع سطر بمسار المهمة الموحَّد — راجعي TaskActivityEntry (types/index.ts). */
const ACTIVITY_ENTRY_META: Record<
  TaskActivityEntry['entry_type'],
  { icon: ReactNode; tone: string }
> = {
  reassigned: { icon: <UserPlus size={15} />, tone: 'bg-info' },
  status_changed: { icon: <RefreshCw size={15} />, tone: 'bg-brand-primary' },
  priority_changed: { icon: <AlertTriangle size={15} />, tone: 'bg-warning' },
  details_updated: { icon: <Pencil size={15} />, tone: 'bg-neutral' },
}

/**
 * تفاصيل مهمة واحدة + تحديث الحالة وإعادة الإسناد ومسار المهمة (Task
 * Trail). راجعي رأس task_service.py بالباك-إند للاجتهادات الموثّقة —
 * أهمها: القفل الكامل بعد status=completed (تعديل/حذف/إعادة إسناد/تحديث
 * حالة كلها ممنوعة)، وأن تحديث الحالة مقيَّد بالكائن نفسه (رئيس اللجنة
 * يحدّث أي مهمة بلجنته، العضو العادي يحدّث مهامه المسندة له فقط).
 */
export function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { showToast } = useToast()

  const { data: task, isLoading, isError, refetch } = useTaskDetail(taskId)
  const { data: committee } = useCommitteeDetail(task?.committee_id)
  const { data: activity } = useTaskActivity(taskId)

  const updateMutation = useUpdateTask()
  const deleteMutation = useDeleteTask()
  const statusMutation = useUpdateTaskStatus()
  const reassignMutation = useReassignTask()

  const [editOpen, setEditOpen] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [reassignOpen, setReassignOpen] = useState(false)
  const [reassignTarget, setReassignTarget] = useState<string | null>(null)
  const [reassignError, setReassignError] = useState<string | null>(null)
  const [completeConfirmOpen, setCompleteConfirmOpen] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const isChair = !!committee && committee.chair_user_id === user?.user_id
  const isAssignee = !!task && task.assignee.user_id === user?.user_id

  // بطلب صريح من Lujain: سوبر أدمن يشوف كل المهام (tasks.view نطاقه all)
  // لكن ما يقدر يدير/يعدّل/يحذف/يعيد إسناد أي مهمة إلا لو كان هو نفسه
  // رئيس تلك اللجنة فعليًا — عمدًا بدون استثناء لعلامة is_super_admin،
  // بالضبط زي الموثَّق برأس Role.scope_for بالباك-إند ("لا يُستخدم
  // للتجاوز التلقائي للصلاحيات — قرار 2026-08-27").
  const canManage = isChair
  // تحديث الحالة مقيَّد بالكائن نفسه — رئيس اللجنة لأي مهمة بلجنته، أو
  // المسؤول الحالي عن المهمة لمهمته هو تحديدًا فقط (نفس المبدأ أعلاه).
  const canUpdateStatus = isChair || isAssignee

  const isLocked = task?.status === 'completed'

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-8 w-56" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <div className="overflow-hidden rounded-md border border-border-default bg-bg-surface">
          <TableSkeleton />
        </div>
      </div>
    )
  }

  if (isError || !task) {
    return <ErrorState onRetry={() => refetch()} />
  }

  function handleUpdate(values: TaskFormSubmitValues) {
    if (!taskId) return
    setEditError(null)
    updateMutation.mutate(
      { taskId, payload: { title: values.title, start_date: values.start_date, end_date: values.end_date } },
      {
        onSuccess: () => {
          setEditOpen(false)
          showToast('تم حفظ التعديلات', 'success')
        },
        onError: (err) => setEditError(extractErrorMessage(err)),
      },
    )
  }

  function handleDelete() {
    if (!taskId) return
    setDeleteError(null)
    deleteMutation.mutate(taskId, {
      onSuccess: () => {
        showToast('تم حذف المهمة', 'success')
        navigate('/tasks')
      },
      onError: (err) => setDeleteError(extractErrorMessage(err)),
    })
  }

  function applyStatus(status: TaskStatus) {
    if (!taskId) return
    setActionError(null)
    statusMutation.mutate(
      { taskId, status },
      {
        onSuccess: () => showToast('تم تحديث حالة المهمة', 'success'),
        onError: (err) => setActionError(extractErrorMessage(err)),
      },
    )
  }

  function handleStatusClick(status: TaskStatus) {
    if (status === 'completed') {
      setCompleteConfirmOpen(true)
      return
    }
    applyStatus(status)
  }

  function handleReassignConfirm() {
    if (!taskId || !reassignTarget) return
    setReassignError(null)
    reassignMutation.mutate(
      { taskId, assigneeUserId: reassignTarget },
      {
        onSuccess: () => {
          setReassignOpen(false)
          setReassignTarget(null)
          showToast('تم إعادة إسناد المهمة', 'success')
        },
        onError: (err) => setReassignError(extractErrorMessage(err)),
      },
    )
  }

  const reassignCandidates = committee
    ? [
        ...(committee.chair ? [committee.chair] : []),
        ...committee.members.filter((m) => m.user_id !== committee.chair?.user_id),
      ]
    : []

  const statusTone = TASK_STATUS_META[task.status].tone
  const overdue = isTaskOverdue(task)
  const accentTone = overdue ? 'danger' : statusTone

  return (
    <motion.div
      initial={{ opacity: 0, x: 14 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className="flex flex-col gap-6"
    >
      <Card className="relative p-0">
        <span
          className="absolute inset-y-0 right-0 w-1 rounded-tr-md rounded-br-md"
          style={{ backgroundColor: `var(--status-${accentTone}-main)` }}
          aria-hidden
        />
        <div className="flex flex-col items-start justify-between gap-4 px-5 py-4 pr-6 sm:flex-row sm:items-center">
          <div className="flex items-start gap-3">
            <button
              onClick={() => navigate('/tasks')}
              className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              aria-label="العودة إلى المهام"
            >
              <ArrowRight size={18} />
            </button>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-xl font-bold text-text-primary">{task.title}</h1>
                <TaskStatusBadge status={task.status} />
                <TaskPriorityBadge priority={task.priority} />
                {overdue && <TaskOverdueBadge />}
              </div>
              {committee && <p className="mt-1 text-sm text-text-muted">لجنة: {committee.name}</p>}
            </div>
          </div>
          {canManage && !isLocked && (
            <ActionMenu
              items={[
                {
                  label: 'تعديل المهمة',
                  icon: <Pencil size={14} />,
                  onClick: () => {
                    setEditError(null)
                    setEditOpen(true)
                  },
                },
                {
                  label: 'إعادة إسناد',
                  icon: <Repeat size={14} />,
                  onClick: () => {
                    setReassignError(null)
                    setReassignTarget(null)
                    setReassignOpen(true)
                  },
                },
                {
                  label: 'حذف المهمة',
                  icon: <Trash2 size={14} />,
                  tone: 'danger',
                  onClick: () => {
                    setDeleteError(null)
                    setDeleteOpen(true)
                  },
                },
              ]}
            />
          )}
        </div>
      </Card>

      <TaskPipeline status={task.status} />

      <Card className="grid grid-cols-1 divide-y divide-border-default p-0 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        {[
          {
            icon: <CalendarRange size={20} />,
            tone: overdue ? 'bg-danger-bg text-danger' : 'bg-brand-teal/10 text-brand-teal',
            value: `${formatDate(task.start_date)} — ${formatDate(task.end_date)}`,
            label: overdue ? 'فترة التنفيذ (متأخرة)' : 'فترة التنفيذ',
          },
          {
            icon: <UserCheck size={20} />,
            tone: 'bg-brand-purple/10 text-brand-purple',
            value: `${task.assignee.first_name} ${task.assignee.last_name}`,
            label: 'المسؤول عن المهمة',
          },
          {
            icon: <ListChecks size={20} />,
            tone: 'bg-brand-primary/10 text-brand-primary',
            value: `${task.creator.first_name} ${task.creator.last_name}`,
            label: 'أُنشئت بواسطة',
          },
        ].map((item, i) => (
          <motion.div
            key={item.label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: i * 0.05, ease: 'easeOut' }}
            className="flex items-center gap-4 px-5 py-4"
          >
            <div className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-full', item.tone)}>
              {item.icon}
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-text-primary">{item.value}</p>
              <p className="mt-1 text-xs text-text-muted">{item.label}</p>
            </div>
          </motion.div>
        ))}
      </Card>

      {canUpdateStatus && (
        <Card>
          <h2 className="text-sm font-semibold text-text-primary">تحديث حالة المهمة</h2>
          <p className="mt-1 text-xs text-text-muted">
            {isLocked
              ? 'المهمة مكتملة — لا يمكن تغيير حالتها بعد الآن'
              : 'اختاري الحالة الجديدة للمهمة'}
          </p>
          {!isLocked && (
            <div className="mt-3 flex flex-wrap gap-2">
              {STATUS_OPTIONS.filter((opt) => opt.value !== task.status).map((opt) => (
                <Button
                  key={opt.value}
                  size="sm"
                  variant={opt.value === 'completed' ? 'primary' : 'secondary'}
                  onClick={() => handleStatusClick(opt.value)}
                  loading={statusMutation.isPending}
                >
                  {opt.label}
                </Button>
              ))}
            </div>
          )}
        </Card>
      )}

      {actionError && (
        <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
          {actionError}
        </p>
      )}

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <History size={15} />
            مسار المهمة
          </h2>
        </div>
        {!activity || activity.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-text-muted">لا توجد أي أحداث على هذه المهمة بعد</p>
        ) : (
          <div className="flex flex-col p-4">
            {(() => {
              const sorted = [...activity].sort(
                (a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime(),
              )
              return sorted.map((entry, i) => {
                const { icon, tone } = ACTIVITY_ENTRY_META[entry.entry_type]
                return (
                  <motion.div
                    key={`${entry.entry_type}-${entry.occurred_at}-${i}`}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.2, delay: Math.min(i * 0.03, 0.25) }}
                    className="relative flex gap-3"
                  >
                    {i < sorted.length - 1 && (
                      <span
                        className="absolute right-[15px] top-8 bottom-0 w-px bg-border-default"
                        aria-hidden
                      />
                    )}
                    <div
                      className={cn(
                        'relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white ring-4 ring-bg-surface',
                        tone,
                      )}
                    >
                      {icon}
                    </div>
                    <div className="flex min-w-0 flex-1 items-start justify-between gap-3 pb-6">
                      <div className="flex min-w-0 flex-col gap-0.5">
                        <p className="text-sm text-text-primary">{entry.label}</p>
                        <p className="text-xs font-medium text-text-muted">
                          {entry.actor ? `بواسطة ${entry.actor.first_name} ${entry.actor.last_name}` : 'تلقائي بواسطة النظام'} · {formatDateTime(entry.occurred_at)}
                        </p>
                      </div>
                      {entry.actor && (
                        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-info-bg text-[10px] font-bold text-info">
                          {getInitials(entry.actor.first_name, entry.actor.last_name)}
                        </div>
                      )}
                    </div>
                  </motion.div>
                )
              })
            })()}
          </div>
        )}
      </Card>

      <p className="text-xs text-text-muted">أُنشئت المهمة في {formatDateTime(task.created_at)}</p>

      {canManage && (
        <>
          <TaskFormModal
            open={editOpen}
            onClose={() => setEditOpen(false)}
            committees={committee ? [committee] : []}
            task={task}
            onSubmit={handleUpdate}
            loading={updateMutation.isPending}
            serverError={editError}
          />
          <ConfirmDialog
            open={deleteOpen}
            onClose={() => setDeleteOpen(false)}
            onConfirm={handleDelete}
            title="حذف المهمة"
            description={`سيتم حذف مهمة "${task.title}" نهائيًا. هل أنتِ متأكدة؟`}
            confirmLabel="حذف"
            loading={deleteMutation.isPending}
            errorMessage={deleteError}
          />

          <Modal
            open={reassignOpen}
            onClose={() => setReassignOpen(false)}
            title="إعادة إسناد المهمة"
            description="اختاري المسؤول الجديد — يُسجَّل تلقائيًا بمسار المهمة"
            footer={
              <>
                <Button variant="ghost" onClick={() => setReassignOpen(false)} disabled={reassignMutation.isPending}>
                  إلغاء
                </Button>
                <Button
                  onClick={handleReassignConfirm}
                  loading={reassignMutation.isPending}
                  disabled={!reassignTarget || reassignTarget === task.assignee.user_id}
                  icon={<Repeat size={16} />}
                >
                  تأكيد إعادة الإسناد
                </Button>
              </>
            }
          >
            <div className="flex flex-col gap-1 rounded-sm border border-border-default p-1">
              {reassignCandidates.map((u) => {
                const isCurrent = u.user_id === task.assignee.user_id
                const isChecked = reassignTarget === u.user_id
                return (
                  <label
                    key={u.user_id}
                    className={cn(
                      'flex cursor-pointer items-center gap-2.5 rounded-xs px-2 py-2 text-sm transition-colors hover:bg-bg-elevated',
                      isChecked && 'bg-brand-primary/5',
                    )}
                  >
                    <input
                      type="radio"
                      checked={isChecked}
                      onChange={() => setReassignTarget(u.user_id)}
                      className="h-4 w-4 shrink-0 border-border-default text-brand-primary focus:ring-brand-accent/40"
                    />
                    <Avatar firstName={u.first_name} lastName={u.last_name} size={28} />
                    <span className="font-medium text-text-primary">
                      {u.first_name} {u.last_name}
                    </span>
                    {isCurrent && <span className="text-xs text-text-muted">(المسؤول الحالي)</span>}
                  </label>
                )
              })}
            </div>
            {reassignError && (
              <p className="mt-3 rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
                {reassignError}
              </p>
            )}
          </Modal>
        </>
      )}

      <ConfirmDialog
        open={completeConfirmOpen}
        onClose={() => setCompleteConfirmOpen(false)}
        onConfirm={() => {
          setCompleteConfirmOpen(false)
          applyStatus('completed')
        }}
        title="إكمال المهمة"
        description="بعد تحديد المهمة كمكتملة، لن يمكن تعديلها أو حذفها أو إعادة إسنادها أو تغيير حالتها مجددًا. هل أنتِ متأكدة؟"
        confirmLabel="تأكيد الإكمال"
        loading={statusMutation.isPending}
      />
    </motion.div>
  )
}
