import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
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
  Users as UsersIcon,
  Video,
  X,
} from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { Avatar } from '@/components/ui/Avatar'
import { DateField } from '@/components/ui/DateField'
import type { Committee, Meeting, MeetingAttachmentLinkRole, MeetingMode } from '@/types'

const agendaItemSchema = z.object({
  title: z.string().min(2, 'عنوان البند يجب أن يكون حرفين على الأقل').max(255),
  description: z.string().max(2000).optional(),
})

/**
 * وقت النهاية إلزامي فقط عند إنشاء اجتماع جديد — يطابق تمامًا الفرق بين
 * MeetingCreate.scheduled_end_at المُلزم وMeetingUpdate.scheduled_end_at
 * الاختياري بالباك-إند (راجعي app/schemas/meeting.py وmigration 0023).
 * تعديل اجتماع قديم (قبل هذا الحقل) لا يجب أن يُحجب بحقل لا تملك بياناته
 * أصلًا — طلب لاما 2026-09-05 كان بالنص "وقت يحدد لنهاية الاجتماع
 * **في اجتماع جديد**"، لا بأثر رجعي على كل تعديل لاجتماع قائم.
 */
function buildSchema(isEdit: boolean) {
  return z
    .object({
      committee_id: z.string().min(1, 'يجب اختيار اللجنة'),
      title: z.string().min(2, 'عنوان الاجتماع يجب أن يكون حرفين على الأقل').max(255),
      description: z.string().max(2000).optional(),
      mode: z.enum(['in_person', 'remote'], { message: 'يجب اختيار نوع الاجتماع' }),
      location: z.string().max(255).optional(),
      meeting_date: z.string().min(1, 'يجب تحديد تاريخ الاجتماع'),
      meeting_time: z.string().min(1, 'يجب تحديد وقت بداية الاجتماع'),
      meeting_end_time: isEdit
        ? z.string().optional()
        : z.string().min(1, 'يجب تحديد وقت نهاية الاجتماع'),
      agenda_items: z.array(agendaItemSchema),
    })
    .refine((v) => v.mode !== 'in_person' || !!v.location?.trim(), {
      message: 'مكان الاجتماع إلزامي للاجتماع الحضوري',
      path: ['location'],
    })
    .refine((v) => !v.meeting_time || !v.meeting_end_time || v.meeting_end_time > v.meeting_time, {
      message: 'وقت نهاية الاجتماع يجب أن يكون بعد وقت البداية',
      path: ['meeting_end_time'],
    })
}

type FormValues = z.infer<ReturnType<typeof buildSchema>>

export interface StagedMeetingAttachment {
  file: File
  link_role: MeetingAttachmentLinkRole
}

export interface MeetingFormSubmitValues {
  committee_id: string
  title: string
  description: string | null
  mode: MeetingMode
  location: string | null
  scheduled_at: string
  /** غير موجود فقط لو تعديل اجتماع قديم بلا وقت نهاية تُرك فارغًا — يعني عدم تغييره. إلزامي دائمًا عند الإنشاء (يفرضه buildSchema أعلاه). */
  scheduled_end_at?: string
  participant_ids: string[]
  /** تُستخدم فقط عند الإنشاء (راجعي isEdit أدناه) — تُتجاهل عند التعديل. */
  agenda_items: { title: string; description: string | null; sort_order: number }[]
  /** تُرفع فعليًا بعد نجاح الإنشاء فقط (لا يوجد meeting_id قبل ذلك) — راجعي MeetingsPage.tsx. */
  attachments: StagedMeetingAttachment[]
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

/** عنوان فرعي لتقسيم النموذج بصريًا — بنفس نمط CommitteeRequestFormModal::FormSection. */
function FormSection({
  icon,
  title,
  required,
  action,
  children,
}: {
  icon: ReactNode
  title: string
  required?: boolean
  action?: ReactNode
  children: ReactNode
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

const MEETING_MODE_OPTIONS = [
  { value: 'in_person', label: 'حضوري' },
  { value: 'remote', label: 'عن بُعد' },
]

/**
 * نموذج إنشاء/تعديل اجتماع — بنفس نمط CommitteeRequestFormModal.
 *
 * تحديث 2026-09-01 (قرار موثّق مع لاما):
 * - نوع الاجتماع اختيار مقيَّد (حضوري/عن بُعد) بدل نص حر — الحضوري يطلب
 *   مكان الاجتماع، وعن بُعد يُربط لاحقًا بـTeams (لا حقل له الآن).
 * - الموعد حقلان منفصلان (تاريخ/وقت) بدل حقل واحد — يُدمجان بـscheduled_at
 *   عند الإرسال فقط.
 * - المشاركون لم يعودوا يُختارون يدويًا — كل أعضاء اللجنة المختارة (ورئيسها)
 *   يُدعَون تلقائيًا بمجرد اختيار اللجنة نفسها (كانت هذه خطوة مكررة —
 *   اختيار اللجنة أصلًا يحدد نطاق من يمكنه الحضور).
 * - جدول الأعمال والمرفقات يظهران فقط عند الإنشاء (وليس التعديل) — بنفس
 *   المنطق الذي كان مطبَّقًا سابقًا على جدول الأعمال وحده ("يُدار من صفحة
 *   تفاصيل الاجتماع مباشرة" عند التعديل)؛ صفحة التفاصيل فيها إدارة كاملة
 *   للأجندة والمرفقات بعد الإنشاء على أي حال.
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
  } = useForm<FormValues>({
    resolver: zodResolver(useMemo(() => buildSchema(isEdit), [isEdit])),
    defaultValues: { agenda_items: [] },
  })

  const agendaFieldArray = useFieldArray({ control, name: 'agenda_items' })

  const selectedCommitteeId = watch('committee_id')
  const selectedMode = watch('mode')
  const selectedCommittee = useMemo(
    () => committees.find((c) => c.committee_id === selectedCommitteeId) ?? null,
    [committees, selectedCommitteeId],
  )

  const autoParticipants = useMemo(() => {
    if (!selectedCommittee) return []
    const chair = selectedCommittee.chair
    const rest = selectedCommittee.members.filter((m) => m.user_id !== chair?.user_id)
    return chair ? [chair, ...rest] : rest
  }, [selectedCommittee])

  const [presentationFile, setPresentationFile] = useState<File | null>(null)
  const [attachmentFiles, setAttachmentFiles] = useState<File[]>([])
  const presentationInputRef = useRef<HTMLInputElement>(null)
  const attachmentInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      // mode يُترك '' حتى تختار المستخدمة صراحة (لا قيمة افتراضية
      // منطقية بين حضوري/عن بُعد) — cast (as FormValues) هنا لتفادي تعارض
      // النوع مع z.enum(['in_person','remote']) بنفس أسلوب الـcast الموجود
      // مسبقًا بـUserFormModal.tsx لمشكلة type مشابهة تمامًا مع status.
      reset({
        committee_id: meeting?.committee_id ?? (committees.length === 1 ? committees[0].committee_id : ''),
        title: meeting?.title ?? '',
        description: meeting?.description ?? '',
        mode: meeting?.mode ?? '',
        location: meeting?.location ?? '',
        // نفس منطق slice المتّبع سابقًا مع datetime-local (راجع الرأس أعلاه) —
        // فُصل هنا لحقلين بدل حقل واحد فقط، بدون تغيير جوهر التحويل.
        meeting_date: meeting?.scheduled_at ? meeting.scheduled_at.slice(0, 10) : '',
        meeting_time: meeting?.scheduled_at ? meeting.scheduled_at.slice(11, 16) : '',
        meeting_end_time: meeting?.scheduled_end_at ? meeting.scheduled_end_at.slice(11, 16) : '',
        agenda_items: [],
      } as FormValues)
      setPresentationFile(null)
      setAttachmentFiles([])
    }
  }, [open, meeting, committees, reset])

  function toSubmitValues(values: FormValues): MeetingFormSubmitValues {
    const attachments: StagedMeetingAttachment[] = [
      ...(presentationFile ? [{ file: presentationFile, link_role: 'presentation' as const }] : []),
      ...attachmentFiles.map((file) => ({ file, link_role: 'attachment' as const })),
    ]
    return {
      committee_id: values.committee_id,
      title: values.title,
      description: values.description?.trim() || null,
      mode: values.mode,
      location: values.mode === 'in_person' ? values.location?.trim() || null : null,
      scheduled_at: new Date(`${values.meeting_date}T${values.meeting_time}`).toISOString(),
      scheduled_end_at: values.meeting_end_time
        ? new Date(`${values.meeting_date}T${values.meeting_end_time}`).toISOString()
        : undefined,
      participant_ids: autoParticipants.map((u) => u.user_id),
      agenda_items: values.agenda_items.map((item, index) => ({
        title: item.title,
        description: item.description?.trim() || null,
        sort_order: index,
      })),
      attachments,
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
          : 'أدخلي بيانات الاجتماع — يُرسل إشعار تلقائي لكل أعضاء اللجنة المختارة'
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

          <Controller
            control={control}
            name="mode"
            render={({ field }) => (
              <Select
                label="نوع الاجتماع"
                required
                placeholder="اختاري نوع الاجتماع"
                options={MEETING_MODE_OPTIONS}
                error={errors.mode?.message}
                {...field}
              />
            )}
          />

          {selectedMode === 'in_person' && (
            <Input
              label="مكان الاجتماع"
              required
              placeholder="مثال: قاعة الاجتماعات الرئيسية، الطابق الثاني"
              error={errors.location?.message}
              {...register('location')}
            />
          )}
          {selectedMode === 'remote' && (
            <p className="flex items-center gap-1.5 text-xs text-text-muted">
              <Video size={13} />
              سيُربط هذا الاجتماع بـMicrosoft Teams لاحقًا
            </p>
          )}
        </FormSection>

        <FormSection icon={<CalendarClock size={13} />} title="الموعد" required>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Controller
              control={control}
              name="meeting_date"
              render={({ field }) => (
                <DateField
                  label="تاريخ الاجتماع"
                  required
                  error={errors.meeting_date?.message}
                  value={field.value ?? ''}
                  onChange={field.onChange}
                />
              )}
            />
            <Input
              type="time"
              label="وقت البداية"
              required
              error={errors.meeting_time?.message}
              {...register('meeting_time')}
            />
            <Input
              type="time"
              label="وقت النهاية"
              required={!isEdit}
              error={errors.meeting_end_time?.message}
              {...register('meeting_end_time')}
            />
          </div>
        </FormSection>

        <FormSection icon={<UsersIcon size={13} />} title="المشاركون">
          {!selectedCommittee ? (
            <p className="text-xs text-text-muted">اختاري اللجنة أولًا لعرض أعضائها</p>
          ) : autoParticipants.length === 0 ? (
            <p className="text-xs text-text-muted">لا يوجد أعضاء بهذه اللجنة</p>
          ) : (
            <>
              <p className="text-xs text-text-muted">
                كل أعضاء اللجنة يُدعَون تلقائيًا لهذا الاجتماع — لا حاجة لاختيارهم يدويًا:
              </p>
              <div className="flex flex-wrap gap-2">
                {autoParticipants.map((u) => {
                  const isChair = u.user_id === selectedCommittee.chair?.user_id
                  return (
                    <div
                      key={u.user_id}
                      className="flex items-center gap-2 rounded-sm border border-border-default bg-bg-surface px-2 py-1.5"
                    >
                      <Avatar firstName={u.first_name} lastName={u.last_name} size={24} />
                      <span className="text-xs font-medium text-text-primary">
                        {u.first_name} {u.last_name}
                      </span>
                      {isChair && <span className="text-[11px] text-text-muted">(رئيس اللجنة)</span>}
                    </div>
                  )
                })}
              </div>
            </>
          )}
        </FormSection>

        {!isEdit && (
          <FormSection
            icon={<ListChecks size={13} />}
            title="اجندة الاجتماع"
            action={
              <button
                type="button"
                onClick={() => agendaFieldArray.append({ title: '', description: '' })}
                className="flex h-6 w-6 items-center justify-center rounded-xs bg-brand-primary/10 text-brand-primary transition-colors hover:bg-brand-primary/20"
                aria-label="إضافة بند لجدول الأعمال"
              >
                <Plus size={14} />
              </button>
            }
          >
            {agendaFieldArray.fields.length === 0 ? (
              <p className="text-xs text-text-muted">لا توجد بنود بعد — اضغطي + لإضافة بند</p>
            ) : (
              <div className="flex flex-col gap-2">
                {agendaFieldArray.fields.map((field, index) => (
                  <div key={field.id} className="flex items-start gap-2">
                    <span className="mt-2.5 text-xs text-text-muted">{index + 1}.</span>
                    <Input
                      placeholder="عنوان بند جدول الأعمال"
                      className="flex-1"
                      error={errors.agenda_items?.[index]?.title?.message}
                      {...register(`agenda_items.${index}.title` as const)}
                    />
                    <button
                      type="button"
                      onClick={() => agendaFieldArray.remove(index)}
                      className="mt-1 rounded-sm p-1.5 text-text-muted transition-colors hover:bg-danger-bg hover:text-danger"
                      aria-label="حذف البند"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </FormSection>
        )}

        {!isEdit && (
          <FormSection icon={<Paperclip size={13} />} title="المرفقات">
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between gap-2 rounded-sm border border-border-default px-3 py-2">
                <span className="flex items-center gap-2 text-xs font-medium text-text-primary">
                  <Presentation size={14} className="text-text-muted" />
                  العرض التقديمي
                </span>
                {presentationFile ? (
                  <span className="flex items-center gap-1.5 text-xs text-text-secondary">
                    {presentationFile.name}
                    <button
                      type="button"
                      onClick={() => setPresentationFile(null)}
                      className="rounded-sm p-0.5 text-text-muted hover:text-danger"
                      aria-label="إزالة العرض التقديمي"
                    >
                      <X size={13} />
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => presentationInputRef.current?.click()}
                    className="text-xs font-medium text-brand-primary hover:underline"
                  >
                    رفع ملف
                  </button>
                )}
                <input
                  ref={presentationInputRef}
                  type="file"
                  className="hidden"
                  onChange={(e) => setPresentationFile(e.target.files?.[0] ?? null)}
                />
              </div>

              <div className="rounded-sm border border-border-default px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 text-xs font-medium text-text-primary">
                    <Paperclip size={14} className="text-text-muted" />
                    مرفقات الاجتماع
                  </span>
                  <button
                    type="button"
                    onClick={() => attachmentInputRef.current?.click()}
                    className="text-xs font-medium text-brand-primary hover:underline"
                  >
                    رفع ملف
                  </button>
                  <input
                    ref={attachmentInputRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={(e) => {
                      const files = Array.from(e.target.files ?? [])
                      setAttachmentFiles((prev) => [...prev, ...files])
                      e.target.value = ''
                    }}
                  />
                </div>
                {attachmentFiles.length > 0 && (
                  <ul className="mt-2 flex flex-col gap-1">
                    {attachmentFiles.map((file, i) => (
                      <li
                        key={`${file.name}-${i}`}
                        className="flex items-center justify-between gap-2 text-xs text-text-secondary"
                      >
                        {file.name}
                        <button
                          type="button"
                          onClick={() => setAttachmentFiles((prev) => prev.filter((_, idx) => idx !== i))}
                          className="rounded-sm p-0.5 text-text-muted hover:text-danger"
                          aria-label="إزالة المرفق"
                        >
                          <X size={13} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </FormSection>
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
