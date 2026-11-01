import { useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { CheckCircle2, Download, FileSpreadsheet, Mail, Upload, X } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { useDownloadImportTemplate, useImportUsers } from '@/hooks/useUsers'
import type { ImportRowError, UserImportResult } from '@/api/users'
import { cn, extractErrorMessage } from '@/lib/utils'

/** نفس حدود الباك إند (user_import_service.MAX_ROWS / MAX_FILE_BYTES). */
const MAX_ROWS = 200
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
  const templateMutation = useDownloadImportTemplate()

  const result: UserImportResult | undefined = importMutation.data
  const rowErrors = importMutation.error ? extractRowErrors(importMutation.error) : null
  const generalError =
    localError ?? (importMutation.error && !rowErrors ? extractErrorMessage(importMutation.error) : null)

  const reset = () => {
    setFile(null)
    setLocalError(null)
    importMutation.reset()
    if (inputRef.current) inputRef.current.value = ''
  }

  const handleClose = () => {
    if (importMutation.isPending) return
    reset()
    onClose()
  }

  const pickFile = (picked: File | undefined) => {
    importMutation.reset()
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
        icon={<Upload size={16} />}
        disabled={!file}
        loading={importMutation.isPending}
        onClick={() => file && importMutation.mutate(file)}
      >
        رفع وإضافة المستخدمين
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
                  {result.departments_created.map((d) => `${d.name} (${d.code})`).join('، ')}
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
              ‎.xlsx فقط — حتى {MAX_ROWS} مستخدم و2 ميجابايت
            </span>
          </label>

          <ul className="list-disc space-y-1 ps-5 text-xs text-text-secondary">
            <li>الأعمدة الإلزامية: الاسم الأول، الأوسط، العائلة، البريد. الإدارة والمسمى والدور اختيارية.</li>
            <li>الإدارة غير الموجودة تُنشأ تلقائيًا، ومديرها صاحب الصف الذي دوره «مدير إدارة (أدمن)».</li>
            <li>المسمى الوظيفي غير الموجود يُضاف تلقائيًا لقائمة المسميات.</li>
            <li>لو فيه أي خطأ بأي صف، ما يُضاف أحد — تظهر الأخطاء برقم الصف لتصحيحها.</li>
          </ul>

          {generalError && (
            <p role="alert" className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
              {generalError}
            </p>
          )}

          {rowErrors && (
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
          )}

          {templateMutation.error && (
            <p className="text-xs text-danger">{extractErrorMessage(templateMutation.error)}</p>
          )}
        </div>
      )}
    </Modal>
  )
}
