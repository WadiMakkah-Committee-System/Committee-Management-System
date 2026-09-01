import { useEffect, useMemo, useState } from 'react'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { CalendarClock, FileText, Save, Users as UsersIcon } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { Avatar } from '@/components/ui/Avatar'
import { cn } from '@/lib/utils'
import type { Committee, Meeting } from '@/types'

const schema = z.object({
  committee_id: z.string().min(1, 'يجب اختيار اللجنة'),
  title: z.string().min(2, 'عنوان الاجتماع يجب أن يكون حرفين على الأقل').max(255),
  description: z.string().max(2000).optional(),
  meeting_type: z.string().max(100).optional(),
  scheduled_at: z.string().min(1, 'يجب تحديد موعد الاجتماع'),
  participant_ids: z.array(z.string()).min(1, 'اختاري مشاركًا واحدًا على الأقل'),
})

type FormValues = z.infer<typeof schema>

export interface MeetingFormSubmitValues {
  committee_id: string
  title: string
  description: string | null
  meeting_type: string | null
  scheduled_at: string
  participant_ids: string[]
}

interface MeetingFormModalProps {
  open: boolean
  onClose: () => void
  /** اللجان التي يقدر المستخدم إنشاء اجتماع لها (رئيسها، أو كل اللجان لسوبر أدمن). */
  committees: Committee[]
  meeting?: Meeting | null
  onSubmit: (values: MeetingFormSubmitValues) => void
  loading?: boolean
  serverError?: string | null
}

/**
 * نموذج إنشاء/تعديل اجتماع — بنفس نمط CommitteeRequestFormModal. عند
 * التعديل، حقل اللجنة يبقى ثابتًا (لا يمكن نقل اجتماع بين لجان)، والمشاركون
 * يُختارون حصريًا من أعضاء اللجنة نفسها (بما فيهم رئيسها) — بنفس القيد
 * المفروض بالباك-إند (meeting_service._resolve_participants). بدون حقل
 * جدول الأعمال عند التعديل — يُدار من صفحة تفاصيل الاجتماع مباشرة.
 */
export function MeetingFormModal({
  open,
  onClose,
  committees,
  meeting,
  onSubmit,
  loading,
  serverError,
}: MeetingFormModalProps) {
  const isEdit = !!meeting

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

  const [participantsError, setParticipantsError] = useState<string | undefined>()

  useEffect(() => {
    if (open) {
      reset({
        committee_id: meeting?.committee_id ?? (committees.length === 1 ? committees[0].committee_id : ''),
        title: meeting?.title ?? '',
        description: meeting?.description ?? '',
        meeting_type: meeting?.meeting_type ?? '',
        // datetime-local لا يقبل لاحقة Z — نقصّها عند التعبئة، ونضيفها عند الإرسال.
        scheduled_at: meeting?.scheduled_at ? meeting.scheduled_at.slice(0, 16) : '',
        participant_ids: meeting?.participants.map((p) => p.user_id) ?? [],
      })
    }
  }, [open, meeting, committees, reset])

  function toSubmitValues(values: FormValues): MeetingFormSubmitValues {
    return {
      committee_id: values.committee_id,
      title: values.title,
      description: values.description?.trim() || null,
      meeting_type: values.meeting_type?.trim() || null,
      scheduled_at: new Date(values.scheduled_at).toISOString(),
      participant_ids: values.participant_ids,
    }
  }

  const submit = handleSubmit((values) => onSubmit(toSubmitValues(values)))

  const committeeOptions = committees.map((c) => ({ value: c.committee_id, label: c.name }))

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'تعديل بيانات الاجتماع' : 'اجتماع جديد'}
      description={
        isEdit
          ? `تعديل بيانات اجتماع "${meeting?.title}"`
          : 'أدخلي بيانات الاجتماع — يُرسل إشعار تلقائي لكل المشاركين المختارين'
      }
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button type="button" onClick={submit} loading={loading} icon={<Save size={16} />}>
            {isEdit ? 'حفظ التعديلات' : 'إنشاء الاجتماع'}
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
              بيانات الاجتماع<span className="text-danger"> *</span>
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
            label="عنوان الاجتماع"
            required
            placeholder="مثال: الاجتماع الدوري الأول"
            error={errors.title?.message}
            {...register('title')}
          />
          <Textarea
            label="وصف الاجتماع"
            placeholder="وصف مختصر لموضوع الاجتماع (اختياري)"
            error={errors.description?.message}
            {...register('description')}
          />
          <Input
            label="نوع الاجتماع"
            placeholder="مثال: دوري، طارئ (اختياري)"
            error={errors.meeting_type?.message}
            {...register('meeting_type')}
          />
        </div>

        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 border-b border-border-default pb-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-xs bg-brand-primary/10 text-brand-primary">
              <CalendarClock size={13} />
            </span>
            <h3 className="text-xs font-bold uppercase tracking-wide text-text-secondary">
              الموعد<span className="text-danger"> *</span>
            </h3>
          </div>
          <Input
            type="datetime-local"
            label="تاريخ ووقت الاجتماع"
            required
            error={errors.scheduled_at?.message}
            {...register('scheduled_at')}
          />
        </div>

        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 border-b border-border-default pb-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-xs bg-brand-primary/10 text-brand-primary">
              <UsersIcon size={13} />
            </span>
            <h3 className="text-xs font-bold uppercase tracking-wide text-text-secondary">
              المشاركون<span className="text-danger"> *</span>
            </h3>
          </div>

          {!selectedCommittee ? (
            <p className="text-xs text-text-muted">اختاري اللجنة أولًا لعرض أعضائها</p>
          ) : (
            <Controller
              control={control}
              name="participant_ids"
              render={({ field }) => {
                const candidates = [
                  ...(selectedCommittee.chair ? [selectedCommittee.chair] : []),
                  ...selectedCommittee.members.filter(
                    (m) => m.user_id !== selectedCommittee.chair?.user_id,
                  ),
                ]
                const selectedSet = new Set(field.value ?? [])

                function toggle(userId: string) {
                  setParticipantsError(undefined)
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
                      errors.participant_ids ? 'border-danger' : 'border-border-default',
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
          {(errors.participant_ids?.message || participantsError) && (
            <p className="text-xs font-medium text-danger">
              {errors.participant_ids?.message ?? participantsError}
            </p>
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
