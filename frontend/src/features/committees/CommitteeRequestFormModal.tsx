import { useEffect } from 'react'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { CalendarRange, FileText, Save, Send, Users as UsersIcon } from 'lucide-react'
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

/** عنوان فرعي لتقسيم النموذج بصريًا — يوضّح التسلسل المنطقي (Hierarchy) لمستخدم غير تقني. */
function FormSection({
  icon,
  title,
  required,
  children,
}: {
  icon: React.ReactNode
  title: string
  required?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 border-b border-border-default pb-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-xs bg-brand-primary/10 text-brand-primary">
          {icon}
        </span>
        <h3 className="text-xs font-bold uppercase tracking-wide text-text-secondary">
          {title}
          {required && <span className="text-danger"> *</span>}
        </h3>
      </div>
      {children}
    </div>
  )
}

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
  /**
   * تُمرَّر فقط عندما يكون بإمكان المستخدم الحالي إرسال الطلب مباشرة
   * (صاحب الطلب بحالة draft/returned) — إن لم تُمرَّر، لا يظهر زر
   * "حفظ وإرسال" إطلاقًا (المسار القديم "حفظ فقط" يبقى يعمل كما هو).
   */
  onSubmitAndSend?: (values: CommitteeRequestFormSubmitValues) => void
  loading?: boolean
  /** حالة التحميل الخاصة بزر "حفظ وإرسال" فقط — منفصلة عن loading الخاص بالحفظ العادي. */
  sendLoading?: boolean
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
  onSubmitAndSend,
  loading,
  sendLoading,
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

  /** تحويل قيم النموذج (FormValues) إلى شكل الإرسال النهائي (trim + null بدل فراغ). */
  function toSubmitValues(values: FormValues): CommitteeRequestFormSubmitValues {
    return {
      committee_name: values.committee_name,
      statement: values.statement?.trim() || null,
      start_date: values.start_date,
      end_date: values.end_date,
      proposed_member_ids: values.proposed_member_ids,
    }
  }

  const submitDraft = handleSubmit((values) => onSubmit(toSubmitValues(values)))
  const submitAndSend = onSubmitAndSend
    ? handleSubmit((values) => onSubmitAndSend(toSubmitValues(values)))
    : undefined

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
          <Button variant="ghost" onClick={onClose} disabled={loading || sendLoading}>
            إلغاء
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={submitDraft}
            loading={loading}
            disabled={sendLoading}
            icon={<Save size={16} />}
          >
            {isEdit ? 'حفظ التعديلات' : 'حفظ كمسودة'}
          </Button>
          {submitAndSend && (
            <Button
              type="button"
              onClick={submitAndSend}
              loading={sendLoading}
              disabled={loading}
              icon={<Send size={16} />}
            >
              حفظ وإرسال
            </Button>
          )}
        </>
      }
    >
      <form id="committee-request-form" className="flex flex-col gap-6">
        <FormSection icon={<FileText size={13} />} title="بيانات اللجنة">
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
        </FormSection>

        <FormSection icon={<CalendarRange size={13} />} title="الفترة الزمنية">
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
        </FormSection>

        <FormSection icon={<UsersIcon size={13} />} title="الأعضاء المقترحون" required>
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
        </FormSection>

        {serverError && (
          <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
            {serverError}
          </p>
        )}
      </form>
    </Modal>
  )
}
