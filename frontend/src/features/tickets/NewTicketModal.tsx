import { useState } from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useNavigate } from 'react-router-dom'
import { Paperclip, Send, UploadCloud } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/components/ui/Toast'
import { useCreateTicket } from '@/hooks/useTickets'
import { cn, extractErrorMessage } from '@/lib/utils'
import { TicketEditor } from './ticketEditor'
import { DropOverlay, SelectedFilesList } from './TicketAttachments'
import { useTicketFilePicker } from './useTicketFilePicker'
import {
  ACCEPTED_FILES_HINT,
  BODY_MAX,
  DESCRIPTION_MIN,
  TITLE_MAX,
  TITLE_MIN,
  countChars,
  newClientMessageId,
  ticketPlainText,
} from './ticketContent'
import { TICKET_MODULE_OPTIONS, TICKET_TYPE_OPTIONS } from './ticketLabels'
import type { TicketDoc, TicketModule, TicketType } from '@/types/tickets'

/**
 * قواعد النموذج — نفس حدود الباك-إند (القسم 5): العنوان 5–150 حرف، والوصف
 * 10–5000 حرف (يُحسب من النص المجرّد بنفس طريقة الخادم).
 */
const schema = z.object({
  title: z
    .string()
    .trim()
    .min(TITLE_MIN, `العنوان لازم يكون ${TITLE_MIN} أحرف على الأقل`)
    .max(TITLE_MAX, `العنوان لازم ما يتجاوز ${TITLE_MAX} حرف`),
  ticket_type: z.string().min(1, 'اختر نوع التذكرة'),
  module: z.string().min(1, 'اختر الوحدة المتأثرة'),
  body: z.custom<TicketDoc | null>().superRefine((doc, ctx) => {
    const length = countChars(ticketPlainText(doc))
    if (length < DESCRIPTION_MIN) {
      ctx.addIssue({ code: 'custom', message: `اكتب وصفًا من ${DESCRIPTION_MIN} أحرف على الأقل` })
    } else if (length > BODY_MAX) {
      ctx.addIssue({ code: 'custom', message: `الوصف أطول من الحد المسموح (${BODY_MAX} حرف)` })
    }
  }),
})

type FormValues = z.infer<typeof schema>

const EMPTY_VALUES: FormValues = { title: '', ticket_type: '', module: '', body: null }

/**
 * الهدف:
 * نموذج إرسال تذكرة جديدة (TKT-FR-001): العنوان، النوع، الوحدة المتأثرة،
 * الوصف (محرر TipTap)، ومرفقات اختيارية بالسحب والإفلات.
 *
 * المسؤولية:
 * - التحقق من الحدود قبل الإرسال (الباك-إند يعيد الفحص).
 * - معرّف إرسال ثابت لكل فتحة نموذج (client_message_id): لو ضغط "إرسال" مرة
 *   ثانية بعد انقطاع، يرجع الباك-إند نفس التذكرة بدل ما ينشئ تذكرة مكررة.
 * - تأكيد قبل الإغلاق لو فيه شيء مكتوب، عشان ما يضيع وصف طويل بنقرة خارج النافذة.
 * - بعد النجاح: رسالة نجاح بالرقم المرجعي، وفتح صفحة التذكرة.
 *
 * المدخلات: open، onClose.
 * الصلاحيات: يظهر لمن يملك "إرسال التذاكر ومتابعتها" (الباك-إند يفحص نفس الصلاحية).
 */
export function NewTicketModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const createMutation = useCreateTicket()
  const [files, setFiles] = useState<File[]>([])
  const [clientId, setClientId] = useState(newClientMessageId)
  const [serverError, setServerError] = useState<string | null>(null)
  const [confirmDiscard, setConfirmDiscard] = useState(false)

  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors, isDirty },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: EMPTY_VALUES })

  const picker = useTicketFilePicker(files, setFiles, createMutation.isPending)

  /**
   * إغلاق مع تصفير النموذج ومعرّف إرسال جديد، فالفتحة التالية تبدأ فاضية
   * (وما ترجع نفس التذكرة السابقة بسبب نفس المعرّف).
   */
  function closeAndReset() {
    reset(EMPTY_VALUES)
    setFiles([])
    setServerError(null)
    setClientId(newClientMessageId())
    picker.clearError()
    onClose()
  }

  const descriptionLength = countChars(ticketPlainText(useWatch({ control, name: 'body' })))
  const hasContent = isDirty || files.length > 0

  function requestClose() {
    if (createMutation.isPending) return
    if (hasContent) setConfirmDiscard(true)
    else closeAndReset()
  }

  const submit = handleSubmit((values) => {
    setServerError(null)
    createMutation.mutate(
      {
        title: values.title.trim(),
        ticket_type: values.ticket_type as TicketType,
        module: values.module as TicketModule,
        body: values.body as TicketDoc,
        client_message_id: clientId,
        files,
      },
      {
        onSuccess: (result) => {
          showToast(`تم إرسال التذكرة ${result.ticket.ticket_number} بنجاح`, 'success')
          closeAndReset()
          navigate(`/tickets/${result.ticket.ticket_id}`)
        },
        onError: (err) => setServerError(extractErrorMessage(err)),
      },
    )
  })

  return (
    <>
      <Modal
        open={open}
        onClose={requestClose}
        size="lg"
        title="تذكرة جديدة"
        description="اكتب طلبك للدعم الفني، وبيوصلك إشعار مع كل رد"
        footer={
          <>
            <Button variant="ghost" onClick={requestClose} disabled={createMutation.isPending}>
              إلغاء
            </Button>
            <Button type="submit" form="new-ticket-form" icon={<Send size={16} />} loading={createMutation.isPending}>
              إرسال التذكرة
            </Button>
          </>
        }
      >
        <form id="new-ticket-form" onSubmit={submit} className="flex flex-col gap-4" noValidate>
          <Input
            label="عنوان التذكرة"
            required
            maxLength={TITLE_MAX}
            placeholder="مثال: ما يظهر زر توقيع المحضر"
            hint={`من ${TITLE_MIN} إلى ${TITLE_MAX} حرف، وما يتعدّل بعد الإرسال`}
            error={errors.title?.message}
            {...register('title')}
          />

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Select
              label="نوع التذكرة"
              required
              placeholder="اختر النوع"
              options={TICKET_TYPE_OPTIONS}
              error={errors.ticket_type?.message}
              {...register('ticket_type')}
            />
            <Select
              label="الوحدة المتأثرة"
              required
              placeholder="اختر الوحدة"
              options={TICKET_MODULE_OPTIONS}
              error={errors.module?.message}
              {...register('module')}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <span id="new-ticket-body-label" className="text-sm font-medium text-text-primary">
              الوصف<span className="text-danger"> *</span>
            </span>
            <Controller
              control={control}
              name="body"
              render={({ field }) => (
                <TicketEditor
                  ariaLabel="وصف التذكرة"
                  placeholder="اشرح المطلوب بالتفصيل: وش كنت تحاول تسوي، ووش صار، ووش المتوقع"
                  minHeightClass="min-h-36"
                  invalid={!!errors.body}
                  onChange={field.onChange}
                  onSubmitShortcut={submit}
                />
              )}
            />
            <div className="flex items-start justify-between gap-3 text-xs">
              {errors.body ? (
                <p className="font-medium text-danger">{errors.body.message}</p>
              ) : (
                <p className="text-text-muted">إذا كانت متابعة لتذكرة مغلقة، اذكر رقمها في الوصف</p>
              )}
              <span
                className={cn(
                  'shrink-0 tabular-nums',
                  descriptionLength > BODY_MAX ? 'font-semibold text-danger' : 'text-text-muted',
                )}
              >
                {descriptionLength} / {BODY_MAX}
              </span>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium text-text-primary">المرفقات (اختياري)</span>
            <div
              {...picker.getRootProps({
                className: cn(
                  'relative flex flex-col items-center justify-center gap-2 rounded-md border border-dashed px-4 py-5 text-center transition-colors',
                  picker.isDragActive ? 'border-brand-primary bg-brand-primary/[0.04]' : 'border-border-default',
                ),
              })}
            >
              <input {...picker.getInputProps()} aria-label="اختيار مرفقات" />
              <UploadCloud size={22} className="text-brand-primary" />
              <p className="text-sm text-text-secondary">اسحب الملفات هنا، أو</p>
              <Button type="button" size="sm" variant="secondary" icon={<Paperclip size={14} />} onClick={picker.open}>
                اختر من جهازك
              </Button>
              <p className="text-xs text-text-muted">{ACCEPTED_FILES_HINT}</p>
              <DropOverlay active={picker.isDragActive} />
            </div>
            {picker.error && <p className="text-xs font-medium text-danger">{picker.error}</p>}
            <SelectedFilesList files={files} onRemove={(index) => setFiles(files.filter((_, i) => i !== index))} />
          </div>

          {serverError && (
            <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
              {serverError}
            </p>
          )}
        </form>
      </Modal>

      <ConfirmDialog
        open={confirmDiscard}
        onClose={() => setConfirmDiscard(false)}
        onConfirm={() => {
          setConfirmDiscard(false)
          closeAndReset()
        }}
        title="تجاهل التذكرة؟"
        description="ما انرسلت التذكرة بعد، واللي كتبته بيضيع إذا أغلقت النافذة."
        confirmLabel="تجاهل وإغلاق"
      />
    </>
  )
}
