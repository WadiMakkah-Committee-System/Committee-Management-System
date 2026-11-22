import { useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { ArrowRight, CheckCircle2, Download, Eye, FileSpreadsheet, Mail, Upload, X } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { useDownloadImportTemplate, useImportUsers, usePreviewImportUsers } from '@/hooks/useUsers'
import type { ImportRowError, UserImportPreview, UserImportResult } from '@/api/users'
import { cn, extractErrorMessage } from '@/lib/utils'

/** نفس حدود الباك إند (user_import_service.MAX_USERS / MAX_FILE_BYTES). */
const MAX_USERS = 200
const MAX_FILE_BYTES = 2 * 1024 * 1024

interface UserImportModalProps {
  open: boolean
  onClose: () => void
}

/**
 * يستخرج أخطاء الصفوف من رد 400 لـPOST /users/import
 * (detail = { message, errors }) — أو null لأي خطأ آخر (خطأ بالملف ككل/شبكة).
 */
function extractRowErrors(error: unknown): { message: string; errors: ImportRowError[] } | null {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (detail && typeof detail === 'object' && 'errors' in detail && Array.isArray((detail as { errors: unknown }).errors)) {
    const d = detail as { message?: string; errors: ImportRowError[] }
    return { message: d.message ?? 'الملف يحتوي أخطاء', errors: d.errors }
  }
  return null
}

/**
 * الهدف:
 * نافذة "رفع ملف" المستخدمين (users.import — طلب لاما 2026-11-01).
 *
 * المسؤولية:
 * - اختيار ملف .xlsx (زر أو سحب وإفلات) + تحميل النموذج المحدث من النظام.
 * - المعاينة أولًا (طلب لاما 2026-11-22): ملخص المستخدمين وتعييناتهم والإدارات
 *   الجديدة (وأمهاتها) قبل أي إنشاء، ثم التأكيد.
 * - الرفع، ثم عرض النتيجة: إما ملخص المستخدمين المنشأين (أسماء المستخدمين
 *   والإدارات الجديدة) — وبيانات الدخول تصل لبريد كل مستخدم — أو جدول
 *   أخطاء برقم الصف والعمود (لا يُضاف أحد عند وجود أي خطأ).
 *
 * الحالة: الملف المختار، والنتيجة الأخيرة (نجاح/أخطاء صفوف/خطأ عام).
 * الأمان: الصلاحية ونطاقها مفروضان بالباك إند؛ إظهار الزر بالصفحة للراحة فقط.
 * لا تُعرض كلمات المرور هنا إطلاقًا.
 */
export function UserImportModal({ open, onClose }: UserImportModalProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const importMutation = useImportUsers()
  const previewMutation = usePreviewImportUsers()
  const templateMutation = useDownloadImportTemplate()

  const result: UserImportResult | undefined = importMutation.data
  const preview: UserImportPreview | undefined = previewMutation.data
  const requestError = importMutation.error ?? previewMutation.error
  const rowErrors = requestError ? extractRowErrors(requestError) : null
  const generalError = localError ?? (requestError && !rowErrors ? extractErrorMessage(requestError) : null)
  const busy = importMutation.isPending || previewMutation.isPending

  const reset = () => {
    setFile(null)
    setLocalError(null)
    importMutation.reset()
    previewMutation.reset()
    if (inputRef.current) inputRef.current.value = ''
  }

  const handleClose = () => {
    if (busy) return
    reset()
    onClose()
  }

  const pickFile = (picked: File | undefined) => {
    importMutation.reset()
    previewMutation.reset()
    setLocalError(null)
    if (!picked) return
    if (!picked.name.toLowerCase().endsWith('.xlsx')) {
      setFile(null)
      setLocalError('الملف يجب أن يكون بصيغة Excel ‏(.xlsx)')
      return
    }
    if (picked.size > MAX_FILE_BYTES) {
      setFile(null)
      setLocalError('حجم الملف أكبر من 2 ميجابايت')
      return
    }
    setFile(picked)
  }

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault()
    setDragging(false)
    pickFile(event.dataTransfer.files?.[0])
  }

  const footer = result ? (
    <Button className="w-full" onClick={handleClose}>
      تم
    </Button>
  ) : preview ? (
    <div className="flex w-full flex-col-reverse gap-2 sm:flex-row sm:justify-between">
      <Button
        variant="ghost"
        icon={<ArrowRight size={16} />}
        disabled={importMutation.isPending}
        onClick={() => {
          previewMutation.reset()
          importMutation.reset()
        }}
      >
        رجوع
      </Button>
      <Button
        icon={<Upload size={16} />}
        loading={importMutation.isPending}
        onClick={() => file && importMutation.mutate(file)}
      >
        تأكيد وإضافة {preview.users_count} مستخدم
      </Button>
    </div>
  ) : (
    <div className="flex w-full flex-col-reverse gap-2 sm:flex-row sm:justify-between">
      <Button
        variant="ghost"
        icon={<Download size={16} />}
        loading={templateMutation.isPending}
        onClick={() => templateMutation.mutate()}
      >
        تحميل النموذج
      </Button>
      <Button
        icon={<Eye size={16} />}
        disabled={!file}
        loading={previewMutation.isPending}
        onClick={() => file && previewMutation.mutate(file)}
      >
        معاينة الملف
      </Button>
    </div>
  )

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="رفع ملف المستخدمين"
      description="أضيفي عدة مستخدمين دفعة واحدة من ملف Excel — يُنشأ لكل مستخدم اسم مستخدم وكلمة مرور مؤقتة تُرسل لبريده"
      size="lg"
      footer={footer}
    >
      {result ? (
        <div className="flex flex-col gap-4">
          <div className="flex items-start gap-3 rounded-sm border border-success-border/40 bg-success-bg px-4 py-3">
            <CheckCircle2 size={20} className="mt-0.5 shrink-0 text-success" />
            <div className="text-sm">
              <p className="font-semibold text-text-primary">تمت إضافة {result.created_count} مستخدم بنجاح</p>
              <p className="mt-0.5 flex items-center gap-1.5 text-text-secondary">
                <Mail size={14} />
                تُرسل بيانات الدخول الآن لبريد كل مستخدم برسالة منفصلة
              </p>
              {result.departments_created.length > 0 && (
                <p className="mt-1 text-text-secondary">
                  إدارات جديدة أُنشئت:{' '}
                  {result.departments_created
                    .map((d) => `${d.name} (${d.code})${d.parent_name ? ` تحت ${d.parent_name}` : ''}`)
                    .join('، ')}
                </p>
              )}
              {result.job_titles_created.length > 0 && (
                <p className="mt-1 text-text-secondary">
                  مسميات وظيفية جديدة أُضيفت: {result.job_titles_created.join('، ')}
                </p>
              )}
            </div>
          </div>
          <div className="max-h-72 overflow-auto rounded-sm border border-border-default">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-bg-elevated text-text-secondary">
                <tr>
                  <th className="px-3 py-2 text-start font-medium">الصف</th>
                  <th className="px-3 py-2 text-start font-medium">الاسم</th>
                  <th className="px-3 py-2 text-start font-medium">اسم المستخدم</th>
                  <th className="px-3 py-2 text-start font-medium">الإدارة</th>
                </tr>
              </thead>
              <tbody>
                {result.users.map((u) => (
                  <tr key={u.user_id} className="border-t border-border-default">
                    <td className="px-3 py-2 text-text-muted">{u.row}</td>
                    <td className="px-3 py-2 text-text-primary">
                      {u.full_name}
                      {u.is_department_manager && (
                        <span className="ms-2 rounded-sm bg-brand-primary/10 px-1.5 py-0.5 text-xs text-brand-primary">
                          مدير الإدارة
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono text-text-primary" dir="ltr">
                      {u.username}
                    </td>
                    <td className="px-3 py-2 text-text-secondary">{u.department ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : preview ? (
        <ImportPreviewSummary preview={preview} rowErrors={rowErrors} generalError={generalError} />
      ) : (
        <div className="flex flex-col gap-4">
          <label
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed px-4 py-8 text-center transition-colors',
              dragging ? 'border-brand-primary bg-brand-primary/5' : 'border-border-default hover:border-brand-primary/60',
            )}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              className="sr-only"
              onChange={(e: ChangeEvent<HTMLInputElement>) => pickFile(e.target.files?.[0])}
            />
            <FileSpreadsheet size={32} className="text-brand-primary" />
            {file ? (
              <span className="flex items-center gap-2 text-sm font-medium text-text-primary">
                {file.name}
                <button
                  type="button"
                  aria-label="إزالة الملف"
                  className="rounded-sm p-0.5 text-text-muted hover:text-danger"
                  onClick={(e) => {
                    e.preventDefault()
                    reset()
                  }}
                >
                  <X size={14} />
                </button>
              </span>
            ) : (
              <span className="text-sm font-medium text-text-primary">اختاري ملف Excel أو اسحبيه هنا</span>
            )}
            <span className="text-xs text-text-muted">
              ‎.xlsx فقط — حتى {MAX_USERS} مستخدم و2 ميجابايت
            </span>
          </label>

          <ul className="list-disc space-y-1 ps-5 text-xs text-text-secondary">
            <li>كل صف = إدارة ودور. الشخص في أكثر من إدارة يتكرر بنفس البريد، والنظام ينشئ له حسابًا واحدًا.</li>
            <li>الاسم والمسمى الوظيفي لازم يتطابقون بكل صفوف نفس البريد، و«نعم» بعمود الإدارة الأساسية بصف واحد فقط.</li>
            <li>الإدارة غير الموجودة تُنشأ تلقائيًا (تحت الإدارة الأم لو كتبتيها)، ومديرها صاحب الصف الذي دوره «مدير إدارة (أدمن)».</li>
            <li>قبل الإضافة تظهر لك معاينة بالمستخدمين والإدارات الجديدة لتأكيدها.</li>
            <li>لو فيه أي خطأ بأي صف، ما يُضاف أحد — تظهر الأخطاء برقم الصف لتصحيحها.</li>
          </ul>

          <GeneralError message={generalError} />
          <ImportErrors rowErrors={rowErrors} />

          {templateMutation.error && (
            <p className="text-xs text-danger">{extractErrorMessage(templateMutation.error)}</p>
          )}
        </div>
      )}
    </Modal>
  )
}

function GeneralError({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p role="alert" className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
      {message}
    </p>
  )
}

/** جدول أخطاء الصفوف (رقم الصف + العمود + الخطأ) — من المعاينة أو الرفع. */
function ImportErrors({ rowErrors }: { rowErrors: { message: string; errors: ImportRowError[] } | null }) {
  if (!rowErrors) return null
  return (
    <div role="alert" className="flex flex-col gap-2">
      <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
        {rowErrors.message}
      </p>
      <div className="max-h-64 overflow-auto rounded-sm border border-border-default">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-bg-elevated text-text-secondary">
            <tr>
              <th className="px-3 py-2 text-start font-medium">الصف</th>
              <th className="px-3 py-2 text-start font-medium">العمود</th>
              <th className="px-3 py-2 text-start font-medium">الخطأ</th>
            </tr>
          </thead>
          <tbody>
            {rowErrors.errors.map((e, i) => (
              <tr key={`${e.row}-${i}`} className="border-t border-border-default align-top">
                <td className="px-3 py-2 text-text-muted">{e.row}</td>
                <td className="whitespace-nowrap px-3 py-2 text-text-secondary">{e.field ?? '—'}</td>
                <td className="px-3 py-2 text-danger">{e.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/**
 * ملخص المعاينة: كل شخص بتعييناته (إدارة + دور) وإدارته الأساسية، والإدارات
 * الجديدة وأمهاتها، والمسميات الجديدة — لتأكيدها قبل الإنشاء.
 */
function ImportPreviewSummary({
  preview,
  rowErrors,
  generalError,
}: {
  preview: UserImportPreview
  rowErrors: { message: string; errors: ImportRowError[] } | null
  generalError: string | null
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-sm border border-brand-primary/30 bg-brand-primary/5 px-4 py-3 text-sm">
        <p className="font-semibold text-text-primary">
          سيُضاف {preview.users_count} مستخدم بـ{preview.assignments_count} تعيين (إدارة + دور)
        </p>
        {preview.departments_to_create.length > 0 && (
          <div className="mt-2">
            <p className="font-medium text-text-primary">
              إدارات جديدة ستُنشأ ({preview.departments_to_create.length}) — تأكدي من الإملاء:
            </p>
            <ul className="mt-1 list-disc ps-5 text-text-secondary">
              {preview.departments_to_create.map((d) => (
                <li key={d.name}>
                  {d.name}
                  {d.parent_name ? ` (تحت ${d.parent_name})` : ' (إدارة مستقلة)'}
                </li>
              ))}
            </ul>
          </div>
        )}
        {preview.job_titles_to_create.length > 0 && (
          <p className="mt-2 text-text-secondary">
            مسميات وظيفية جديدة: {preview.job_titles_to_create.join('، ')}
          </p>
        )}
      </div>

      <div className="max-h-72 overflow-auto rounded-sm border border-border-default">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-bg-elevated text-text-secondary">
            <tr>
              <th className="px-3 py-2 text-start font-medium">الصف</th>
              <th className="px-3 py-2 text-start font-medium">الاسم</th>
              <th className="px-3 py-2 text-start font-medium">الإدارات والأدوار</th>
            </tr>
          </thead>
          <tbody>
            {preview.users.map((u) => (
              <tr key={u.email} className="border-t border-border-default align-top">
                <td className="px-3 py-2 text-text-muted">{u.row}</td>
                <td className="px-3 py-2 text-text-primary">
                  {u.full_name}
                  <span className="block text-xs text-text-muted" dir="ltr">
                    {u.email}
                  </span>
                </td>
                <td className="px-3 py-2 text-text-secondary">
                  <ul className="flex flex-col gap-0.5">
                    {u.assignments.map((a, i) => (
                      <li key={`${a.department}-${a.role}-${i}`}>
                        {a.department ?? 'بدون إدارة'} — {a.role ?? 'بدون دور'}
                        {a.department && a.department === u.primary_department && (
                          <span className="ms-2 rounded-sm bg-brand-primary/10 px-1.5 py-0.5 text-xs text-brand-primary">
                            أساسية
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <GeneralError message={generalError} />
      <ImportErrors rowErrors={rowErrors} />
    </div>
  )
}
