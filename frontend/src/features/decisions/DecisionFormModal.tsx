import { useEffect, useState } from 'react'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { CalendarRange, FileText, Paperclip, Save, Vote } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import type { Committee, Decision, DecisionClassification } from '@/types'
import { FixedVoteOptions } from './FixedVoteOptions'

const schema = z
  .object({
    committee_id: z.string().min(1, 'يجب اختيار اللجنة'),
    title: z.string().min(2, 'اسم القرار يجب أن يكون حرفين على الأقل').max(255),
    classification: z.enum(['final', 'voting'], { message: 'يجب اختيار تصنيف القرار' }),
    start_date: z.string().min(1, 'يجب تحديد تاريخ البداية'),
    end_date: z.string().min(1, 'يجب تحديد تاريخ النهاية'),
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
  /**
   * طرح القرار للتصويت مباشرة بعد إنشائه — true فقط لو classification ===
   * 'voting' بالإنشاء (بلاغ خطأ 2026-09-08: إنشاء + طرح للتصويت خطوة واحدة).
   * DecisionsPage.tsx.handleCreate يستدعي open-voting تلقائيًا بعد نجاح
   * الإنشاء. الخيارات ثابتة (تحديث 2026-11-03) فلا تُرسل من هنا.
   */
  openVotingNow: boolean
  /** مرفق اختياري عند الإنشاء فقط (طلب صاحبة المشروع 2026-11-01) — يُرفع بنداء منفصل بعد نجاح الإنشاء. */
  attachmentFile: File | null
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
 * نموذج إنشاء/تعديل قرار مستقل (بدون مصدر اجتماع — يُبنى لاحقًا).
 *
 * تحديث 2026-09-08 (بلاغ خطأ من رئيسة لجنة فعلية أثناء الاستخدام):
 * اختيار "خاضع للتصويت" يظهر الآن حقول الخيارات مباشرة بنفس النموذج
 * (بدل التنقّل لصفحة تفاصيل منفصلة وفتح قسم "طرح للتصويت" هناك يدويًا).
 * فقط عند الإنشاء (isEdit=false) — التعديل لا يزال بلا خيارات تصويت
 * (تُدار من صفحة التفاصيل، لأن قرارًا قائمًا قد يكون له تصويت مفتوح
 * أصلًا لا معنى لإعادة تعريف خياراته هنا).
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

  const [attachmentFile, setAttachmentFile] = useState<File | null>(null)

  const classification = watch('classification')
  const showOptionsBuilder = !isEdit && classification === 'voting'

  useEffect(() => {
    if (open) {
      reset({
        committee_id:
          decision?.committee_id ?? (committees.length === 1 ? committees[0].committee_id : ''),
        title: decision?.title ?? '',
        classification: decision?.classification ?? 'final',
        start_date: decision?.start_date ?? '',
        end_date: decision?.end_date ?? '',
      })
      setAttachmentFile(null)
    }
  }, [open, decision, committees, reset])

  const submit = handleSubmit((values) => {
    onSubmit({ ...values, openVotingNow: showOptionsBuilder, attachmentFile })
  })

  const committeeOptions = committees.map((c) => ({ value: c.committee_id, label: c.name }))
  const watchedCommitteeId = watch('committee_id')
  const selectedCommittee = committees.find((c) => c.committee_id === watchedCommitteeId)

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'تعديل بيانات القرار' : 'قرار جديد'}
      description={
        isEdit
          ? `تعديل بيانات قرار "${decision?.title}"`
          : 'يُصدر مباشرة من واجهة القرارات — يشمل تلقائيًا كل أعضاء اللجنة كمنفذين'
      }
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button type="button" onClick={submit} loading={loading} icon={<Save size={16} />}>
            {isEdit ? 'حفظ التعديلات' : showOptionsBuilder ? 'إنشاء القرار وطرحه للتصويت' : 'إنشاء القرار'}
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
                placeholder="اختر اللجنة"
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
                    classification === opt.value
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

        {showOptionsBuilder && (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2 border-b border-border-default pb-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-xs bg-brand-primary/10 text-brand-primary">
                <Vote size={13} />
              </span>
              <h3 className="text-xs font-bold uppercase tracking-wide text-text-secondary">
                خيارات التصويت
              </h3>
            </div>
            <FixedVoteOptions />
          </div>
        )}

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
              min={selectedCommittee?.start_date ?? undefined}
              max={selectedCommittee?.end_date ?? undefined}
              hint={
                selectedCommittee?.start_date && selectedCommittee.end_date
                  ? `ضمن فترة اللجنة (${selectedCommittee.start_date} - ${selectedCommittee.end_date})`
                  : undefined
              }
              {...register('start_date')}
            />
            <Input
              type="date"
              label="تاريخ نهاية التنفيذ"
              required
              error={errors.end_date?.message}
              min={selectedCommittee?.start_date ?? undefined}
              max={selectedCommittee?.end_date ?? undefined}
              {...register('end_date')}
            />
          </div>
        </div>

        {!isEdit && (
          <div className="flex flex-col gap-2 border-t border-border-default pt-3">
            <label className="flex items-center gap-1.5 text-sm font-medium text-text-primary">
              <Paperclip size={14} />
              مرفق
            </label>
            <input
              type="file"
              onChange={(e) => setAttachmentFile(e.target.files?.[0] ?? null)}
              className="text-sm text-text-secondary file:ml-3 file:rounded-sm file:border-0 file:bg-brand-primary/10 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-brand-primary"
            />
            {attachmentFile && (
              <p className="text-xs text-text-muted">تم اختيار: {attachmentFile.name}</p>
            )}
          </div>
        )}

        {serverError && (
          <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
            {serverError}
          </p>
        )}
      </form>
    </Modal>
  )
}
