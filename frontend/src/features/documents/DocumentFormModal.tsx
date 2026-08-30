import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Save, Upload, FileText, X } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { MultiCheckPicker } from '@/components/ui/MultiCheckPicker'
import type { Committee, Department, Document, DocumentCategory, User } from '@/types'

const schema = z.object({
  title: z.string().min(2, 'عنوان الوثيقة يجب أن يكون حرفين على الأقل').max(255),
  description: z.string().max(2000).optional(),
  category_id: z.string().optional(),
})

type FormValues = z.infer<typeof schema>

export interface DocumentFormSubmitValues {
  title: string
  description: string | null
  category_id: string | null
  is_public: boolean
  department_ids: string[]
  committee_ids: string[]
  user_ids: string[]
}

interface DocumentFormModalProps {
  open: boolean
  onClose: () => void
  document?: Document | null
  categories: DocumentCategory[]
  departments: Department[]
  committees: Committee[]
  users: User[]
  onSubmitCreate: (values: DocumentFormSubmitValues & { file: File }) => void
  onSubmitEdit: (values: DocumentFormSubmitValues) => void
  loading?: boolean
  serverError?: string | null
}

const MAX_UPLOAD_MB = 25

/**
 * الهدف:
 * نموذج رفع وثيقة جديدة أو تعديل بيانات وثيقة موجودة — نفس مكوّن واحد
 * لكلا الوضعين (بنفس أسلوب DepartmentFormModal/RoleFormModal) بدل تكرار
 * الفورم مرتين، مع فرق جوهري واحد: حقل الملف يظهر فقط عند الإنشاء، لأن
 * تعديل وثيقة موجودة Metadata فقط ولا يستبدل الملف نفسه (قرار موثّق في
 * DocumentUpdate schema بالباك-إند — لتغيير الملف تُرفع وثيقة جديدة).
 *
 * المسؤولية:
 * التحقق من صحة عنوان/وصف/تصنيف الوثيقة (Zod)، وإدارة اختيار نطاق
 * الرؤية المركّب (عام بالكامل أو إدارات/لجان/مستخدمون محددون) عبر
 * MultiCheckPicker، وبناء القيم النهائية لتُرسَل للصفحة الأم التي تستدعي
 * فعليًا useUploadDocument/useUpdateDocument.
 *
 * الصلاحيات: لا تُفحص هنا — الصفحة الأم (DocumentsPage/DocumentDetailPage)
 * هي من تقرر إظهار زر الفتح أصلًا حسب صلاحيات المستخدم.
 */
export function DocumentFormModal({
  open,
  onClose,
  document,
  categories,
  departments,
  committees,
  users,
  onSubmitCreate,
  onSubmitEdit,
  loading,
  serverError,
}: DocumentFormModalProps) {
  const isEdit = !!document
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [isPublic, setIsPublic] = useState(false)
  const [departmentIds, setDepartmentIds] = useState<string[]>([])
  const [committeeIds, setCommitteeIds] = useState<string[]>([])
  const [userIds, setUserIds] = useState<string[]>([])

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  useEffect(() => {
    if (!open) return
    reset({
      title: document?.title ?? '',
      description: document?.description ?? '',
      category_id: document?.category?.category_id ?? '',
    })
    setFile(null)
    setFileError(null)
    setIsPublic(document?.is_public ?? false)
    setDepartmentIds(document?.visible_departments.map((d) => d.dep_id) ?? [])
    setCommitteeIds(document?.visible_committees.map((c) => c.committee_id) ?? [])
    setUserIds(document?.visible_users.map((u) => u.user_id) ?? [])
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [open, document, reset])

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0] ?? null
    if (selected && selected.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setFileError(`حجم الملف يتجاوز الحد الأقصى المسموح (${MAX_UPLOAD_MB} ميجابايت)`)
      setFile(null)
      return
    }
    setFileError(null)
    setFile(selected)
  }

  function submit(values: FormValues) {
    if (!isEdit && !file) {
      setFileError('اختيار ملف مطلوب')
      return
    }
    const common: DocumentFormSubmitValues = {
      title: values.title,
      description: values.description?.trim() || null,
      category_id: values.category_id || null,
      is_public: isPublic,
      department_ids: departmentIds,
      committee_ids: committeeIds,
      user_ids: userIds,
    }
    if (isEdit) {
      onSubmitEdit(common)
    } else if (file) {
      onSubmitCreate({ ...common, file })
    }
  }

  const categoryOptions = categories.map((c) => ({
    value: c.category_id,
    label: c.scope === 'global' ? c.name : `${c.name} (خاص بإدارة)`,
  }))

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'تعديل بيانات الوثيقة' : 'رفع وثيقة جديدة'}
      description={isEdit ? `تعديل "${document?.title}"` : 'أدخل بيانات الوثيقة واختر ملفًا لرفعه'}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button form="document-form" type="submit" loading={loading} icon={<Save size={16} />}>
            {isEdit ? 'حفظ التعديلات' : 'رفع الوثيقة'}
          </Button>
        </>
      }
    >
      <form id="document-form" onSubmit={handleSubmit(submit)} className="flex flex-col gap-4">
        {!isEdit && (
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-text-primary">
              الملف
              <span className="text-danger"> *</span>
            </label>
            {file ? (
              <div className="flex items-center gap-3 rounded-sm border border-border-default bg-bg-surface px-3 py-2">
                <FileText size={18} className="shrink-0 text-brand-primary" />
                <p className="flex-1 truncate text-sm text-text-primary">{file.name}</p>
                <button
                  type="button"
                  onClick={() => {
                    setFile(null)
                    if (fileInputRef.current) fileInputRef.current.value = ''
                  }}
                  className="shrink-0 rounded-sm p-1 text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
                  aria-label="إزالة الملف"
                >
                  <X size={14} />
                </button>
              </div>
            ) : (
              <label
                className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-sm border border-dashed border-border-default bg-bg-surface px-4 py-6 text-center transition-colors hover:bg-bg-elevated"
              >
                <Upload size={20} className="text-text-muted" />
                <p className="text-sm text-text-secondary">اضغط لاختيار ملف (حتى {MAX_UPLOAD_MB} ميجابايت)</p>
                <input ref={fileInputRef} type="file" className="hidden" onChange={handleFileChange} />
              </label>
            )}
            {fileError && <p className="text-xs font-medium text-danger">{fileError}</p>}
          </div>
        )}

        <Input
          label="عنوان الوثيقة"
          required
          placeholder="مثال: محضر اجتماع مجلس الإدارة"
          error={errors.title?.message}
          {...register('title')}
        />

        <Textarea
          label="الوصف"
          placeholder="وصف مختصر لمحتوى الوثيقة (اختياري)"
          error={errors.description?.message}
          {...register('description')}
        />

        <Select
          label="التصنيف"
          placeholder="بدون تصنيف"
          options={categoryOptions}
          error={errors.category_id?.message}
          {...register('category_id')}
        />

        <div className="flex flex-col gap-3 rounded-sm border border-border-default p-3">
          <label className="flex cursor-pointer items-center gap-2.5 text-sm font-medium text-text-primary">
            <input
              type="checkbox"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.target.checked)}
              className="h-4 w-4 shrink-0 rounded-xs border-border-default text-brand-primary focus:ring-brand-accent/40"
            />
            إتاحة الوثيقة للجميع (عامة)
          </label>

          {!isPublic && (
            <div className="flex flex-col gap-4 border-t border-border-default pt-3">
              <p className="text-xs text-text-muted">
                غير عامة — حدّد من يستطيع رؤيتها: إدارات و/أو لجان و/أو مستخدمون محددون (يكفي تحديد واحدة، ويمكن الجمع بينها)
              </p>
              <div className="flex flex-col gap-1.5">
                <p className="text-xs font-bold text-text-secondary">إدارات محددة</p>
                <MultiCheckPicker
                  items={departments}
                  getId={(d) => d.dep_id}
                  getLabel={(d) => d.name}
                  selected={departmentIds}
                  onChange={setDepartmentIds}
                  searchPlaceholder="ابحث باسم الإدارة..."
                  emptyText="لا توجد إدارات"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <p className="text-xs font-bold text-text-secondary">لجان محددة</p>
                <MultiCheckPicker
                  items={committees}
                  getId={(c) => c.committee_id}
                  getLabel={(c) => c.name}
                  selected={committeeIds}
                  onChange={setCommitteeIds}
                  searchPlaceholder="ابحث باسم اللجنة..."
                  emptyText="لا توجد لجان معتمدة"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <p className="text-xs font-bold text-text-secondary">مستخدمون محددون</p>
                <MultiCheckPicker
                  items={users}
                  getId={(u) => u.user_id}
                  getLabel={(u) => `${u.first_name} ${u.last_name}`}
                  getSublabel={(u) => u.email}
                  selected={userIds}
                  onChange={setUserIds}
                  searchPlaceholder="ابحث بالاسم أو البريد الإلكتروني..."
                  emptyText="لا يوجد مستخدمون"
                />
              </div>
            </div>
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
