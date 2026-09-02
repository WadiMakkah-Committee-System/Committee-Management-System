import { useEffect, useMemo } from 'react'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { CalendarRange, FileText, Save, UserCheck } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { Avatar } from '@/components/ui/Avatar'
import { cn } from '@/lib/utils'
import type { Committee, Decision, DecisionClassification } from '@/types'

const schema = z
  .object({
    committee_id: z.string().min(1, 'يجب اختيار اللجنة'),
    title: z.string().min(2, 'اسم القرار يجب أن يكون حرفين على الأقل').max(255),
    classification: z.enum(['final', 'voting'], { required_error: 'يجب اختيار تصنيف القرار' }),
    start_date: z.string().min(1, 'يجب تحديد تاريخ البداية'),
    end_date: z.string().min(1, 'يجب تحديد تاريخ النهاية'),
    assignee_ids: z.array(z.string()).min(1, 'اختاري منفّذًا واحدًا على الأقل'),
  })
  .refine((v) => v.end_date >= v.start_date, {
    message: 'تاريخ النهاية يجب أن يكون بعد تاريخ البداية أو يساويه',
    path: ['end_date'],
  })

type FormValues = z.infer<typeof schema>

export interface DecisionFormSubmitValues {
  committee_id: string
  title: string
  classification: DecisionClassification
  start_date: string
  end_date: string
  assignee_ids: string[]
}

interface DecisionFormModalProps {
  open: boolean
  onClose: () => void
  /** اللجان التي يقدر المستخدم إنشاء قرار لها (رئيسها، أو كل اللجان لسوبر أدمن). */
  committees: Committee[]
  decision?: Decision | null
  onSubmit: (values: DecisionFormSubmitValues) => void
  loading?: boolean
  serverError?: string | null
}

const CLASSIFICATION_OPTIONS: { value: DecisionClassification; label: string; hint: string }[] = [
  { value: 'final', label: 'قرار نهائي', hint: 'يُعتمد مباشرة بدون تصويت' },
  { value: 'voting', label: 'خاضع للتصويت', hint: 'يُطرح لتصويت أعضاء اللجنة' },
]

/**
 * نموذج إنشاء/تعديل قرار مستقل (بدون مصدر اجتماع — يُبنى لاحقًا). المنفذون
 * حصريًا من أعضاء اللجنة (بمن فيهم رئيسها) — قرار صاحبة المشروع
 * 2026-09-02، يُتحقَّق منه أيضًا بالباك-إند (decision_service._resolve_assignees).
 */
export function DecisionFormModal({
  open,
  onClose,
  committees,
  decision,
  onSubmit,
  loading,
  serverError,
}: DecisionFormModalProps) {
  const isEdit = !!decision

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
          decision?.committee_id ?? (committees.length === 1 ? committees[0].committee_id : ''),
        title: decision?.title ?? '',
        classification: decision?.classification ?? 'final',
        start_date: decision?.start_date ?? '',
        end_date: decision?.end_date ?? '',
        assignee_ids: decision?.assignees.map((a) => a.user_id) ?? [],
      })
    }
  }, [open, decision, committees, reset])

  const submit = handleSubmit((values) => onSubmit(values))

  const committeeOptions = committees.map((c) => ({ value: c.committee_id, label: c.name }))

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'تعديل بيانات القرار' : 'قرار جديد'}
      description={
        isEdit
          ? `تعديل بيانات قرار "${decision?.title}"`
          : 'يُصدر مباشرة من واجهة القرارات — بدون مصدر اجتماع'
      }
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button type="button" onClick={submit} loading={loading} icon={<Save size={16} />}>
            {isEdit ? 'حفظ التعديلات' : 'إنشاء القرار'}
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
              بيانات القرار<span className="text-danger"> *</span>
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
            label="اسم القرار"
            required
            placeholder="مثال: اعتماد الميزانية التشغيلية"
            error={errors.title?.message}
            {...register('title')}
          />

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-text-primary">
              تصنيف القرار<span className="text-danger"> *</span>
            </label>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {CLASSIFICATION_OPTIONS.map((opt) => (
                <label
                  key={opt.value}
                  className={cn(
                    'flex cursor-pointer flex-col gap-0.5 rounded-sm border p-3 text-sm transition-colors',
                    watch('classification') === opt.value
                      ? 'border-brand-primary bg-brand-primary/5'
                      : 'border-border-default hover:bg-bg-elevated',
                  )}
                >
                  <span className="flex items-center gap-2 font-medium text-text-primary">
                    <input
                      type="radio"
                      value={opt.value}
                      {...register('classification')}
                      className="h-4 w-4 text-brand-primary focus:ring-brand-accent/40"
                    />
                    {opt.label}
                  </span>
                  <span className="pr-6 text-xs text-text-muted">{opt.hint}</span>
                </label>
              ))}
            </div>
            {errors.classification && (
              <p className="text-xs font-medium text-danger">{errors.classification.message}</p>
            )}
          </div>
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
              <UserCheck size={13} />
            </span>
            <h3 className="text-xs font-bold uppercase tracking-wide text-text-secondary">
              المنفذون<span className="text-danger"> *</span>
            </h3>
          </div>

          {!selectedCommittee ? (
            <p className="text-xs text-text-muted">اختاري اللجنة أولًا لعرض أعضائها</p>
          ) : (
            <Controller
              control={control}
              name="assignee_ids"
              render={({ field }) => {
                const candidates = [
                  ...(selectedCommittee.chair ? [selectedCommittee.chair] : []),
                  ...selectedCommittee.members.filter(
                    (m) => m.user_id !== selectedCommittee.chair?.user_id,
                  ),
                ]
                const selectedSet = new Set(field.value ?? [])

                function toggle(userId: string) {
                  if (selectedSet.has(userId)) {
                    field.onChange((field.value ?? []).filter((id) => id !== userId))
                  } else {
                    field.onChange([...(field.value ?? []), userId])
                  }
                }

                return (
                  <div
                    className={cn(
                      'flex flex-col gap-1 rounded-sm border p-1',
                      errors.assignee_ids ? 'border-danger' : 'border-border-default',
                    )}
                  >
                    {candidates.map((u) => {
                      const isChecked = selectedSet.has(u.user_id)
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
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => toggle(u.user_id)}
                            className="h-4 w-4 shrink-0 rounded-xs border-border-default text-brand-primary focus:ring-brand-accent/40"
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
          {errors.assignee_ids && (
            <p className="text-xs font-medium text-danger">{errors.assignee_ids.message}</p>
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
