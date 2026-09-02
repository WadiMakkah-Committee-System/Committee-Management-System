import { useEffect, useState } from 'react'
import { useForm, Controller, useFieldArray } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import {
  CalendarClock,
  FileText,
  ListChecks,
  Paperclip,
  Plus,
  Presentation,
  Save,
  Trash2,
  Upload,
} from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import type { Committee, Meeting, MeetingMode } from '@/types'

const schema = z
  .object({
    committee_id: z.string().min(1, 'يجب اختيار اللجنة'),
    title: z.string().min(2, 'عنوان الاجتماع يجب أن يكون حرفين على الأقل').max(255),
    description: z.string().max(2000).optional(),
    mode: z.enum(['remote', 'in_person'], { required_error: 'يجب اختيار نوع الاجتماع' }),
    location: z.string().max(255).optional(),
    meeting_date: z.string().min(1, 'يجب تحديد تاريخ الاجتماع'),
    meeting_time: z.string().min(1, 'يجب تحديد وقت الاجتماع'),
    agenda_items: z
      .array(z.object({ title: z.string().min(1, 'عنوان البند مطلوب'), description: z.string().optional() }))
      .default([]),
  })
  .refine((v) => v.mode !== 'in_person' || !!v.location?.trim(), {
    message: 'مكان الاجتماع إلزامي عند اختيار اجتماع حضوري',
    path: ['location'],
  })

type FormValues = z.infer<typeof schema>

export interface MeetingFormSubmitValues {
  committee_id: string
  title: string
  description: string | null
  mode: MeetingMode
  location: string | null
  scheduled_at: string
  agenda_items: { title: string; description?: string | null }[]
  /** ملفات مؤجَّلة الرفع — تُرفع بعد نجاح الإنشاء (تحتاج meeting_id). فارغة عند التعديل. */
  presentationFile: File | null
  attachmentFiles: File[]
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

const MODE_OPTIONS: { value: MeetingMode; label: string }[] = [
  { value: 'remote', label: 'عن بُعد' },
  { value: 'in_person', label: 'حضوري' },
]

function FormSection({
  icon,
  title,
  required,
  action,
  children,
}: {
  icon: React.ReactNode
  title: string
  required?: boolean
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2 border-b border-border-default pb-2">
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-xs bg-brand-primary/10 text-brand-primary">
            {icon}
          </span>
          <h3 className="text-xs font-bold uppercase tracking-wide text-text-secondary">
            {title}
            {required && <span className="text-danger"> *</span>}
          </h3>
        </div>
        {action}
      </div>
      {children}
    </div>
  )
}

/**
 * نموذج إنشاء/تعديل اجتماع.
 *
 * قرارات صاحبة المشروع 2026-09-01:
 * - نوع الاجتماع اختيار ثنائي (عن بُعد/حضوري) لا نص حر — حضوري يفتح حقل
 *   "مكان الاجتماع"، عن بُعد يُربط لاحقًا بـTeams (لا حقل إضافي الآن).
 * - الموعد حقلان منفصلان (تاريخ + وقت) بدل حقل واحد مدمج.
 * - لا يوجد اختيار يدوي للمشاركين — كل أعضاء اللجنة يُضافون تلقائيًا فور
 *   اختيار اللجنة (تُنفَّذ بطبقة الخدمة بالباك-إند، لا حاجة لأي واجهة هنا).
 * - قسم "أجندة الاجتماع" (+ لإضافة بند) وقسم "المرفقات" (عرض تقديمي +
 *   مرفقات عامة) — يظهران فقط عند الإنشاء (ليس التعديل، حيث تُدار الأجندة
 *   من صفحة التفاصيل مباشرة). ملفات المرفقات تُرفع فعليًا بعد نجاح إنشاء
 *   الاجتماع (تحتاج meeting_id) — راجعي MeetingsPage.tsx لتسلسل الاستدعاء.
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
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { agenda_items: [] } })

  const { fields: agendaFields, append: appendAgendaItem, remove: removeAgendaItem } =
    useFieldArray({ control, name: 'agenda_items' })

  const mode = watch('mode')

  const [presentationFile, setPresentationFile] = useState<File | null>(null)
  const [attachmentFiles, setAttachmentFiles] = useState<File[]>([])

  useEffect(() => {
    if (open) {
      const [datePart, timePart] = meeting?.scheduled_at
        ? [meeting.scheduled_at.slice(0, 10), meeting.scheduled_at.slice(11, 16)]
        : ['', '']
      reset({
        committee_id: meeting?.committee_id ?? (committees.length === 1 ? committees[0].committee_id : ''),
        title: meeting?.title ?? '',
        description: meeting?.description ?? '',
        mode: meeting?.mode ?? 'remote',
        location: meeting?.location ?? '',
        meeting_date: datePart,
        meeting_time: timePart,
        agenda_items: [],
      })
      setPresentationFile(null)
      setAttachmentFiles([])
    }
  }, [open, meeting, committees, reset])

  function toSubmitValues(values: FormValues): MeetingFormSubmitValues {
    const scheduledAt = new Date(`${values.meeting_date}T${values.meeting_time}`).toISOString()
    return {
      committee_id: values.committee_id,
      title: values.title,
      description: values.description?.trim() || null,
      mode: values.mode,
      location: values.mode === 'in_person' ? values.location?.trim() || null : null,
      scheduled_at: scheduledAt,
      agenda_items: values.agenda_items
        .filter((item) => item.title.trim())
        .map((item) => ({ title: item.title.trim(), description: item.description?.trim() || null })),
      presentationFile,
      attachmentFiles,
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
          : 'أدخلي بيانات الاجتماع — يشمل تلقائيًا كل أعضاء اللجنة كمشاركين'
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
        <FormSection icon={<FileText size={13} />} title="بيانات الاجتماع" required>
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
        </FormSection>

        <FormSection icon={<CalendarClock size={13} />} title="نوع الاجتماع والموعد" required>
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-text-primary">
              نوع الاجتماع<span className="text-danger"> *</span>
            </label>
            <div className="flex gap-3">
              {MODE_OPTIONS.map((opt) => (
                <label
                  key={opt.value}
                  className={cn(
                    'flex flex-1 cursor-pointer items-center justify-center gap-2 rounded-sm border py-2.5 text-sm font-medium transition-colors',
                    mode === opt.value
                      ? 'border-brand-primary bg-brand-primary/5 text-brand-primary'
                      : 'border-border-default text-text-secondary hover:bg-bg-elevated',
                  )}
                >
                  <input type="radio" value={opt.value} {...register('mode')} className="sr-only" />
                  {opt.label}
                </label>
              ))}
            </div>
            {errors.mode && <p className="text-xs font-medium text-danger">{errors.mode.message}</p>}
          </div>

          {mode === 'in_person' && (
            <Input
              label="مكان الاجتماع"
              required
              placeholder="مثال: قاعة الاجتماعات الرئيسية — الدور الثالث"
              error={errors.location?.message}
              {...register('location')}
            />
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input
              type="date"
              label="تاريخ الاجتماع"
              required
              error={errors.meeting_date?.message}
              {...register('meeting_date')}
            />
            <Input
              type="time"
              label="وقت الاجتماع"
              required
              error={errors.meeting_time?.message}
              {...register('meeting_time')}
            />
          </div>
        </FormSection>

        {!isEdit && (
          <>
            <FormSection
              icon={<ListChecks size={13} />}
              title="أجندة الاجتماع"
              action={
                <button
                  type="button"
                  onClick={() => appendAgendaItem({ title: '', description: '' })}
                  className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-primary/10 text-brand-primary transition-colors hover:bg-brand-primary/20"
                  aria-label="إضافة بند لأجندة الاجتماع"
                >
                  <Plus size={14} />
                </button>
              }
            >
              {agendaFields.length === 0 ? (
                <p className="text-xs text-text-muted">
                  لا توجد بنود بعد — اضغطي + لإضافة أول بند بجدول الأعمال (اختياري)
                </p>
              ) : (
                <div className="flex flex-col gap-2">
                  {agendaFields.map((field, index) => (
                    <div key={field.id} className="flex items-start gap-2">
                      <Input
                        placeholder={`بند ${index + 1}`}
                        error={errors.agenda_items?.[index]?.title?.message}
                        {...register(`agenda_items.${index}.title` as const)}
                      />
                      <button
                        type="button"
                        onClick={() => removeAgendaItem(index)}
                        className="mt-2 shrink-0 rounded-sm p-1.5 text-text-muted transition-colors hover:bg-danger-bg hover:text-danger"
                        aria-label="حذف البند"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </FormSection>

            <FormSection icon={<Paperclip size={13} />} title="المرفقات">
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
                  <Presentation size={14} className="text-text-muted" />
                  العرض التقديمي
                </div>
                <label className="flex cursor-pointer items-center gap-2 rounded-sm border border-dashed border-border-default px-3 py-2.5 text-sm text-text-muted transition-colors hover:border-brand-primary hover:text-brand-primary">
                  <Upload size={14} />
                  {presentationFile ? presentationFile.name : 'اختاري ملف العرض التقديمي (اختياري)'}
                  <input
                    type="file"
                    className="hidden"
                    onChange={(e) => setPresentationFile(e.target.files?.[0] ?? null)}
                  />
                </label>
              </div>

              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
                  <Paperclip size={14} className="text-text-muted" />
                  مرفقات الاجتماع
                </div>
                <label className="flex cursor-pointer items-center gap-2 rounded-sm border border-dashed border-border-default px-3 py-2.5 text-sm text-text-muted transition-colors hover:border-brand-primary hover:text-brand-primary">
                  <Upload size={14} />
                  إضافة ملفات (يمكن اختيار أكثر من ملف)
                  <input
                    type="file"
                    multiple
                    className="hidden"
                    onChange={(e) => setAttachmentFiles(Array.from(e.target.files ?? []))}
                  />
                </label>
                {attachmentFiles.length > 0 && (
                  <ul className="flex flex-col gap-1">
                    {attachmentFiles.map((f, i) => (
                      <li
                        key={i}
                        className="flex items-center justify-between rounded-xs bg-bg-elevated px-2.5 py-1.5 text-xs text-text-secondary"
                      >
                        {f.name}
                        <button
                          type="button"
                          onClick={() => setAttachmentFiles((prev) => prev.filter((_, idx) => idx !== i))}
                          className="text-text-muted hover:text-danger"
                          aria-label={`إزالة ${f.name}`}
                        >
                          <Trash2 size={12} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </FormSection>
          </>
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
