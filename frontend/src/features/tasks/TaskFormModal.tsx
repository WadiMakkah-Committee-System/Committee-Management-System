import { useEffect, useMemo } from 'react'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { AlertTriangle, Bell, CalendarRange, FileText, Save, UserCheck } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { Avatar } from '@/components/ui/Avatar'
import { cn } from '@/lib/utils'
import type { Committee, Task, TaskPriority } from '@/types'

const PRIORITY_OPTIONS: { value: TaskPriority; label: string }[] = [
  { value: 'low', label: 'منخفضة' },
  { value: 'medium', label: 'متوسطة' },
  { value: 'high', label: 'عالية' },
]

const schema = z
  .object({
    committee_id: z.string().min(1, 'يجب اختيار اللجنة'),
    title: z.string().min(2, 'اسم المهمة يجب أن يكون حرفين على الأقل').max(255),
    start_date: z.string().min(1, 'يجب تحديد تاريخ البداية'),
    end_date: z.string().min(1, 'يجب تحديد تاريخ النهاية'),
    assignee_user_id: z.string().min(1, 'يجب اختيار مسؤول المهمة'),
    priority: z.enum(['low', 'medium', 'high']),
    reminder_offset_days: z
      .number()
      .int('يجب أن يكون رقمًا صحيحًا')
      .min(0, 'لا يمكن أن يكون سالبًا')
      .max(30, 'الحد الأقصى 30 يومًا'),
  })
  .refine((v) => v.end_date >= v.start_date, {
    message: 'تاريخ النهاية يجب أن يكون بعد تاريخ البداية أو يساويه',
    path: ['end_date'],
  })

type FormValues = z.infer<typeof schema>

export interface TaskFormSubmitValues {
  committee_id: string
  title: string
  start_date: string
  end_date: string
  assignee_user_id: string
  priority: TaskPriority
  reminder_offset_days: number
}

interface TaskFormModalProps {
  open: boolean
  onClose: () => void
  /** اللجان التي يقدر المستخدم إنشاء مهمة لها (رئيسها، أو كل اللجان لسوبر أدمن). */
  committees: Committee[]
  task?: Task | null
  onSubmit: (values: TaskFormSubmitValues) => void
  loading?: boolean
  serverError?: string | null
}

/**
 * نموذج إنشاء/تعديل مهمة — مسؤول واحد فقط لكل مهمة (قرار صاحبة المشروع
 * 2026-09-06)، على عكس القرارات (منفذون متعددون). المسؤول حصريًا من
 * أعضاء اللجنة (بمن فيهم رئيسها) — يُتحقَّق منه أيضًا بالباك-إند
 * (task_service._validate_assignee_membership). تعديل عنوان/تواريخ
 * المهمة فقط هنا؛ إعادة الإسناد فعل منفصل من صفحة التفاصيل (راجعي
 * TaskDetailPage.tsx) لأنه يُسجَّل بمسار المهمة (Task Trail).
 */
export function TaskFormModal({
  open,
  onClose,
  committees,
  task,
  onSubmit,
  loading,
  serverError,
}: TaskFormModalProps) {
  const isEdit = !!task

  const {
    register,
    handleSubmit,
    reset,
    control,
    watch,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  const selectedCommitteeId = watch('committee_id')
  const selectedCommittee = useMemo(
    () => committees.find((c) => c.committee_id === selectedCommitteeId) ?? null,
    [committees, selectedCommitteeId],
  )

  useEffect(() => {
    if (open) {
      reset({
        committee_id:
          task?.committee_id ?? (committees.length === 1 ? committees[0].committee_id : ''),
        title: task?.title ?? '',
        start_date: task?.start_date ?? '',
        end_date: task?.end_date ?? '',
        assignee_user_id: task?.assignee.user_id ?? '',
        priority: task?.priority ?? 'medium',
        reminder_offset_days: task?.reminder_offset_days ?? 1,
      })
    }
  }, [open, task, committees, reset])

  const submit = handleSubmit((values) => onSubmit(values))

  const committeeOptions = committees.map((c) => ({ value: c.committee_id, label: c.name }))

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'تعديل بيانات المهمة' : 'مهمة جديدة'}
      description={
        isEdit ? `تعديل بيانات مهمة "${task?.title}"` : 'تُسند مباشرة لعضو واحد من أعضاء اللجنة'
      }
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button type="button" onClick={submit} loading={loading} icon={<Save size={16} />}>
            {isEdit ? 'حفظ التعديلات' : 'إنشاء المهمة'}
          </Button>
        </>
      }
    >
      <form className="flex flex-col gap-6">
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 border-b border-border-default pb-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-xs bg-brand-primary/10 text-brand-primary">
              <FileText size={13} />
            </span>
            <h3 className="text-xs font-bold uppercase tracking-wide text-text-secondary">
              بيانات المهمة<span className="text-danger"> *</span>
            </h3>
          </div>

          <Controller
            control={control}
            name="committee_id"
            render={({ field }) => (
              <Select
                label="اللجنة"
                required
                disabled={isEdit}
                placeholder="اختاري اللجنة"
                options={committeeOptions}
                error={errors.committee_id?.message}
                {...field}
              />
            )}
          />

          <Input
            label="اسم المهمة"
            required
            placeholder="مثال: إعداد تقرير الاجتماع الشهري"
            error={errors.title?.message}
            {...register('title')}
          />
        </div>

        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 border-b border-border-default pb-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-xs bg-brand-primary/10 text-brand-primary">
              <CalendarRange size={13} />
            </span>
            <h3 className="text-xs font-bold uppercase tracking-wide text-text-secondary">
              فترة التنفيذ<span className="text-danger"> *</span>
            </h3>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input
              type="date"
              label="تاريخ بداية التنفيذ"
              required
              error={errors.start_date?.message}
              {...register('start_date')}
            />
            <Input
              type="date"
              label="تاريخ نهاية التنفيذ"
              required
              error={errors.end_date?.message}
              {...register('end_date')}
            />
          </div>
        </div>

        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 border-b border-border-default pb-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-xs bg-brand-primary/10 text-brand-primary">
              <AlertTriangle size={13} />
            </span>
            <h3 className="text-xs font-bold uppercase tracking-wide text-text-secondary">
              الأولوية والتذكير
            </h3>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Controller
              control={control}
              name="priority"
              render={({ field }) => (
                <Select
                  label="الأولوية"
                  options={PRIORITY_OPTIONS}
                  error={errors.priority?.message}
                  {...field}
                />
              )}
            />
            <Input
              type="number"
              min={0}
              max={30}
              label="تذكير قبل الاستحقاق (بالأيام)"
              hint="اختياري — الافتراضي يوم واحد قبل موعد الاستحقاق"
              error={errors.reminder_offset_days?.message}
              {...register('reminder_offset_days', { valueAsNumber: true })}
            />
          </div>
          <p className="flex items-center gap-1.5 text-xs text-text-muted">
            <Bell size={12} />
            يصل التذكير للمسؤول عن المهمة فقط.
          </p>
        </div>

        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 border-b border-border-default pb-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-xs bg-brand-primary/10 text-brand-primary">
              <UserCheck size={13} />
            </span>
            <h3 className="text-xs font-bold uppercase tracking-wide text-text-secondary">
              المسؤول عن المهمة<span className="text-danger"> *</span>
            </h3>
          </div>

          {isEdit ? (
            <p className="text-xs text-text-muted">
              لا يمكن تغيير مسؤول المهمة من هنا — استخدمي "إعادة إسناد" من صفحة تفاصيل المهمة (يُسجَّل بمسار المهمة).
            </p>
          ) : !selectedCommittee ? (
            <p className="text-xs text-text-muted">اختاري اللجنة أولًا لعرض أعضائها</p>
          ) : (
            <Controller
              control={control}
              name="assignee_user_id"
              render={({ field }) => {
                const candidates = [
                  ...(selectedCommittee.chair ? [selectedCommittee.chair] : []),
                  ...selectedCommittee.members.filter(
                    (m) => m.user_id !== selectedCommittee.chair?.user_id,
                  ),
                ]

                return (
                  <div
                    className={cn(
                      'flex flex-col gap-1 rounded-sm border p-1',
                      errors.assignee_user_id ? 'border-danger' : 'border-border-default',
                    )}
                  >
                    {candidates.map((u) => {
                      const isChecked = field.value === u.user_id
                      const isChair = u.user_id === selectedCommittee.chair?.user_id
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
                            onChange={() => field.onChange(u.user_id)}
                            className="h-4 w-4 shrink-0 border-border-default text-brand-primary focus:ring-brand-accent/40"
                          />
                          <Avatar firstName={u.first_name} lastName={u.last_name} size={28} />
                          <span className="font-medium text-text-primary">
                            {u.first_name} {u.last_name}
                          </span>
                          {isChair && <span className="text-xs text-text-muted">(رئيس اللجنة)</span>}
                        </label>
                      )
                    })}
                  </div>
                )
              }}
            />
          )}
          {errors.assignee_user_id && (
            <p className="text-xs font-medium text-danger">{errors.assignee_user_id.message}</p>
          )}
        </div>

        {serverError && (
          <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
            {serverError}
          </p>
        )}
      </form>
    </Modal>
  )
}
