import { useEffect } from 'react'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Save } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'
import { Button } from '@/components/ui/Button'
import { useUsers } from '@/hooks/useUsers'
import { MemberPicker } from './MemberPicker'
import type { CommitteeFormationRequest } from '@/types'

const schema = z
  .object({
    committee_name: z.string().min(2, 'اسم اللجنة يجب أن يكون حرفين على الأقل').max(200),
    statement: z.string().max(2000).optional(),
    start_date: z.string().min(1, 'تاريخ البداية مطلوب'),
    end_date: z.string().min(1, 'تاريخ النهاية مطلوب'),
    proposed_member_ids: z.array(z.string()).min(1, 'اختاري عضوًا واحدًا على الأقل'),
  })
  .refine((v) => v.end_date > v.start_date, {
    message: 'تاريخ نهاية عمل اللجنة يجب أن يكون بعد تاريخ البداية',
    path: ['end_date'],
  })

type FormValues = z.infer<typeof schema>

export interface CommitteeRequestFormSubmitValues {
  committee_name: string
  statement: string | null
  start_date: string
  end_date: string
  proposed_member_ids: string[]
}

interface CommitteeRequestFormModalProps {
  open: boolean
  onClose: () => void
  request?: CommitteeFormationRequest | null
  onSubmit: (values: CommitteeRequestFormSubmitValues) => void
  loading?: boolean
  serverError?: string | null
}

/**
 * نموذج إنشاء/تعديل طلب تشكيل لجنة — يُستخدم لكلا الحالتين (Create/Edit)
 * بنفس نمط DepartmentFormModal. من يقدر يفتحه ومتى محكوم بمنطق الصفحة
 * المستدعية حسب حالة الطلب (draft/returned لمقدّم الطلب، أو
 * submitted/under_review للمكتب التنفيذي) — لا قيد هنا على مستوى النموذج
 * نفسه، القيد الفعلي مفروض بالباك-إند (committee_service.update_request).
 */
export function CommitteeRequestFormModal({
  open,
  onClose,
  request,
  onSubmit,
  loading,
  serverError,
}: CommitteeRequestFormModalProps) {
  const isEdit = !!request
  const { data: users } = useUsers()

  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  useEffect(() => {
    if (open) {
      reset({
        committee_name: request?.committee_name ?? '',
        statement: request?.statement ?? '',
        start_date: request?.start_date ?? '',
        end_date: request?.end_date ?? '',
        proposed_member_ids: request?.proposed_members.map((m) => m.user_id) ?? [],
      })
    }
  }, [open, request, reset])

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'تعديل طلب تشكيل اللجنة' : 'طلب تشكيل لجنة جديد'}
      description={
        isEdit
          ? `تعديل بيانات طلب "${request?.committee_name}"`
          : 'أدخلي بيانات اللجنة المقترح تشكيلها — يُحفظ الطلب كمسودة، وتقدرين ترسلينه لاحقًا'
      }
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button form="committee-request-form" type="submit" loading={loading} icon={<Save size={16} />}>
            {isEdit ? 'حفظ التعديلات' : 'حفظ كمسودة'}
          </Button>
        </>
      }
    >
      <form
        id="committee-request-form"
        onSubmit={handleSubmit((values) =>
          onSubmit({
            committee_name: values.committee_name,
            statement: values.statement?.trim() || null,
            start_date: values.start_date,
            end_date: values.end_date,
            proposed_member_ids: values.proposed_member_ids,
          }),
        )}
        className="flex flex-col gap-4"
      >
        <Input
          label="اسم اللجنة"
          required
          placeholder="مثال: لجنة تطوير الأنظمة الداخلية"
          error={errors.committee_name?.message}
          {...register('committee_name')}
        />
        <Textarea
          label="بيان/غرض اللجنة"
          placeholder="وصف مختصر للهدف من تشكيل اللجنة (اختياري)"
          error={errors.statement?.message}
          {...register('statement')}
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input
            type="date"
            label="تاريخ بداية عمل اللجنة"
            required
            error={errors.start_date?.message}
            {...register('start_date')}
          />
          <Input
            type="date"
            label="تاريخ نهاية عمل اللجنة"
            required
            error={errors.end_date?.message}
            {...register('end_date')}
          />
        </div>
        <Controller
          control={control}
          name="proposed_member_ids"
          render={({ field }) => (
            <MemberPicker
              users={users ?? []}
              selected={field.value ?? []}
              onChange={field.onChange}
              error={errors.proposed_member_ids?.message}
            />
          )}
        />
        {serverError && (
          <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
            {serverError}
          </p>
        )}
      </form>
    </Modal>
  )
}
