import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Save, Upload, FileText, X, Globe2, Building2, Users2, UserRound } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { MultiCheckPicker } from '@/components/ui/MultiCheckPicker'
import { cn } from '@/lib/utils'
import type { Committee, Department, Document, DocumentCategory, User } from '@/types'

const schema = z.object({
  title: z.string().min(2, 'عنوان الوثيقة يجب أن يكون حرفين على الأقل').max(255),
  description: z.string().max(2000).optional(),
  category_id: z.string().optional(),
})

type FormValues = z.infer<typeof schema>

/**
 * نطاق الوثيقة — اختيار واحد حصري (بدل الأعلام المستقلة is_public +
 * قوائم إدارات/لجان/مستخدمين معًا كما كان سابقًا، اللي كانت تسمح
 * بالجمع أو الترك فارغًا بلا وضوح لمن يملأ الفورم). "عامة" تعني للجميع،
 * وبقية الخيارات كل واحد منها يحدد فئة واحدة فقط لرؤية الوثيقة — يمكن
 * تحديد أكثر من عنصر داخل نفس الفئة (مثال: أكثر من إدارة) عبر
 * MultiCheckPicker، لكن لا تركيب بين الفئات نفسها. القيمة null تعني
 * "لم تُختَر بعد" — تُمنع من الحفظ (راجع submit أدناه).
 */
type DocumentScope = 'public' | 'department' | 'committee' | 'users'

const SCOPE_OPTIONS: { value: DocumentScope; label: string; icon: typeof Globe2 }[] = [
  { value: 'public', label: 'عامة', icon: Globe2 },
  { value: 'department', label: 'إدارة', icon: Building2 },
  { value: 'committee', label: 'لجنة', icon: Users2 },
  { value: 'users', label: 'مستخدمون محددون', icon: UserRound },
]

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
  /** إدارات مُتاحة للمستخدم الحالي لإتاحة الوثيقة لها فقط (مبدأ أقل صلاحية ممكنة) — راجعي useDocumentPublishTargets، وليس القائمة الكاملة لكل إدارات الشركة. */
  departments: Department[]
  /** لجان مُتاحة للمستخدم الحالي فقط، لنفس سبب departments أعلاه. */
  committees: Committee[]
  users: User[]
  /**
   * عند الرفع من داخل صفحة لجنة معيّنة (قسم "وثائق اللجنة")، نطاق
   * الوثيقة يُضبَط تلقائيًا على "لجنة" مع تحديد هذه اللجنة مسبقًا — توفيرًا
   * لخطوات المستخدمة (رفع مباشر بدل الذهاب واختيار اللجنة يدويًا)، مع
   * إبقاء إمكانية تغييره (نطاق آخر، أو لجنة أخرى إن كانت عضوة بأكثر من
   * لجنة) لأن هذا مجرد تعبئة مبدئية وليس قفلًا. تُهمَل في وضع التعديل
   * (الوثيقة الموجودة تحدد نطاقها من بياناتها الفعلية لا من هذا الحقل).
   */
  defaultCommitteeId?: string
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
 * التحقق من صحة عنوان/وصف/تصنيف الوثيقة (Zod)، وإدارة اختيار "نطاق
 * الوثيقة" (عامة/إدارة/لجنة/مستخدمون محددون — راجعي DocumentScope أعلاه
 * لسبب توحيدها باختيار حصري واحد بدل 3 قوائم متزامنة كما كانت سابقًا)،
 * مع فرض قيد "لا يمكن أن تكون الوثيقة عامة وتصنيفها خاص بإدارة معينة"
 * على مستوى الواجهة (نفس القيد المفروض بالباك-إند في
 * document_service._assert_public_category_consistency — هذا مجرد نسخة
 * فورية بدون رحلة خادم، والباك-إند يبقى مصدر الحقيقة الفعلي والحارس
 * الأخير له)، ثم بناء القيم النهائية لتُرسَل للصفحة الأم التي تستدعي
 * فعليًا useUploadDocument/useUpdateDocument.
 *
 * الصلاحيات: لا تُفحص هنا — الصفحة الأم (DocumentsPage/DocumentDetailPage)
 * هي من تقرر إظهار زر الفتح أصلًا حسب صلاحيات المستخدم، وقوائم
 * departments/committees الممرَّرة هنا مُصفَّاة مسبقًا حسب مبدأ أقل
 * صلاحية ممكنة (راجعي التعليق على الحقلين بالأعلى).
 */
export function DocumentFormModal({
  open,
  onClose,
  document,
  categories,
  departments,
  committees,
  users,
  defaultCommitteeId,
  onSubmitCreate,
  onSubmitEdit,
  loading,
  serverError,
}: DocumentFormModalProps) {
  const isEdit = !!document
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [scope, setScope] = useState<DocumentScope | null>(null)
  const [scopeError, setScopeError] = useState<string | null>(null)
  const [departmentIds, setDepartmentIds] = useState<string[]>([])
  const [committeeIds, setCommitteeIds] = useState<string[]>([])
  const [userIds, setUserIds] = useState<string[]>([])

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  const categoryId = watch('category_id')
  const selectedCategory = categories.find((c) => c.category_id === categoryId) ?? null
  const categoryIsDepartmentScoped = selectedCategory?.scope === 'department'

  useEffect(() => {
    if (!open) return
    reset({
      title: document?.title ?? '',
      description: document?.description ?? '',
      category_id: document?.category?.category_id ?? '',
    })
    setFile(null)
    setFileError(null)
    setScopeError(null)
    const nextDepartmentIds = document?.visible_departments.map((d) => d.dep_id) ?? []
    // ربط تلقائي مع لجنة اللجنة (راجعي defaultCommitteeId أعلاه): فقط في
    // وضع الإنشاء (لا document) وعدم إرسال لجان أخرى صراحة — التعديل
    // يعتمد على بيانات الوثيقة الفعلية حصرًا.
    const nextCommitteeIds =
      document?.visible_committees.map((c) => c.committee_id) ??
      (defaultCommitteeId ? [defaultCommitteeId] : [])
    const nextUserIds = document?.visible_users.map((u) => u.user_id) ?? []
    setDepartmentIds(nextDepartmentIds)
    setCommitteeIds(nextCommitteeIds)
    setUserIds(nextUserIds)
    if (document?.is_public) setScope('public')
    else if (nextDepartmentIds.length > 0) setScope('department')
    else if (nextCommitteeIds.length > 0) setScope('committee')
    else if (nextUserIds.length > 0) setScope('users')
    else setScope(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [open, document, defaultCommitteeId, reset])

  // القيد المفروض بالباك-إند: تصنيف خاص بإدارة + وثيقة عامة = تناقض
  // مرفوض. لو المستخدمة اختارت "عامة" ثم بدّلت التصنيف لتصنيف خاص
  // بإدارة، نُلغي اختيار "عامة" تلقائيًا فورًا (بدل تركها تكتشف الرفض
  // لاحقًا عند الحفظ) ونشرح السبب — القرار من المستخدمة صراحة: "امنعها"
  // (تشديد لا تحذير فقط).
  useEffect(() => {
    if (scope === 'public' && categoryIsDepartmentScoped) {
      setScope(null)
      setScopeError(
        'تم إلغاء اختيار «عامة» تلقائيًا — التصنيف المختار خاص بإدارة معينة، ولا يمكن أن تكون الوثيقة عامة وتصنيفها خاص بإدارة في نفس الوقت. اختاري نطاقًا آخر.',
      )
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categoryIsDepartmentScoped])

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

  function selectScope(value: DocumentScope) {
    if (value === 'public' && categoryIsDepartmentScoped) return
    setScope(value)
    setScopeError(null)
  }

  function submit(values: FormValues) {
    if (!isEdit && !file) {
      setFileError('اختيار ملف مطلوب')
      return
    }
    if (!scope) {
      setScopeError('اختاري نطاق الوثيقة أولًا (عامة/إدارة/لجنة/مستخدمون محددون)')
      return
    }
    if (scope === 'public' && categoryIsDepartmentScoped) {
      setScopeError('لا يمكن أن تكون الوثيقة عامة وتصنيفها خاص بإدارة معينة في نفس الوقت')
      return
    }
    if (scope === 'department' && departmentIds.length === 0) {
      setScopeError('اختاري إدارة واحدة على الأقل')
      return
    }
    if (scope === 'committee' && committeeIds.length === 0) {
      setScopeError('اختاري لجنة واحدة على الأقل')
      return
    }
    if (scope === 'users' && userIds.length === 0) {
      setScopeError('اختاري مستخدمًا واحدًا على الأقل')
      return
    }
    setScopeError(null)

    const common: DocumentFormSubmitValues = {
      title: values.title,
      description: values.description?.trim() || null,
      category_id: values.category_id || null,
      is_public: scope === 'public',
      department_ids: scope === 'department' ? departmentIds : [],
      committee_ids: scope === 'committee' ? committeeIds : [],
      user_ids: scope === 'users' ? userIds : [],
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
          <p className="text-sm font-medium text-text-primary">
            نطاق الوثيقة
            <span className="text-danger"> *</span>
          </p>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {SCOPE_OPTIONS.map(({ value, label, icon: Icon }) => {
              const disabled = value === 'public' && categoryIsDepartmentScoped
              const active = scope === value
              return (
                <button
                  key={value}
                  type="button"
                  disabled={disabled}
                  onClick={() => selectScope(value)}
                  className={cn(
                    'flex flex-col items-center gap-1.5 rounded-sm border px-2 py-2.5 text-xs font-medium transition-colors',
                    active
                      ? 'border-brand-primary bg-brand-primary/5 text-brand-primary'
                      : 'border-border-default text-text-secondary hover:bg-bg-elevated',
                    disabled && 'cursor-not-allowed opacity-50 hover:bg-transparent',
                  )}
                >
                  <Icon size={16} />
                  {label}
                </button>
              )
            })}
          </div>

          {categoryIsDepartmentScoped && (
            <p className="text-xs text-text-muted">
              التصنيف المختار خاص بإدارة معينة، لذلك لا يمكن اختيار نطاق «عامة» لهذه الوثيقة.
            </p>
          )}
          {scopeError && <p className="text-xs font-medium text-danger">{scopeError}</p>}

          {scope === 'department' && (
            <div className="flex flex-col gap-1.5 border-t border-border-default pt-3">
              <p className="text-xs font-bold text-text-secondary">الإدارات</p>
              <MultiCheckPicker
                items={departments}
                getId={(d) => d.dep_id}
                getLabel={(d) => d.name}
                selected={departmentIds}
                onChange={setDepartmentIds}
                searchPlaceholder="ابحث باسم الإدارة..."
                emptyText="لا توجد إدارات متاحة لك لإتاحة الوثيقة لها"
              />
            </div>
          )}

          {scope === 'committee' && (
            <div className="flex flex-col gap-1.5 border-t border-border-default pt-3">
              <p className="text-xs font-bold text-text-secondary">اللجان</p>
              <MultiCheckPicker
                items={committees}
                getId={(c) => c.committee_id}
                getLabel={(c) => c.name}
                selected={committeeIds}
                onChange={setCommitteeIds}
                searchPlaceholder="ابحث باسم اللجنة..."
                emptyText="لا توجد لجان متاحة لك لإتاحة الوثيقة لها"
              />
            </div>
          )}

          {scope === 'users' && (
            <div className="flex flex-col gap-1.5 border-t border-border-default pt-3">
              <p className="text-xs font-bold text-text-secondary">المستخدمون</p>
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
