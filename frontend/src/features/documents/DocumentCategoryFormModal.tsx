import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Save } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import type { Department, DocumentCategory, DocumentCategoryScope } from '@/types'

const schema = z
  .object({
    name: z.string().min(2, 'اسم التصنيف يجب أن يكون حرفين على الأقل').max(150),
    scope: z.enum(['global', 'department']),
    department_id: z.string().optional(),
  })
  .refine((values) => values.scope !== 'department' || !!values.department_id, {
    message: 'اختيار الإدارة مطلوب لتصنيف خاص بإدارة',
    path: ['department_id'],
  })

type FormValues = z.infer<typeof schema>

export interface DocumentCategoryFormSubmitValues {
  name: string
  scope: DocumentCategoryScope
  department_id: string | null
}

interface DocumentCategoryFormModalProps {
  open: boolean
  onClose: () => void
  category?: DocumentCategory | null
  departments: Department[]
  /** يحدّد قيم "النطاق" المتاحة عند الإنشاء حسب صلاحيات المستخدم الفعلية فقط. */
  allowGlobal: boolean
  allowDepartment: boolean
  onSubmit: (values: DocumentCategoryFormSubmitValues) => void
  loading?: boolean
  serverError?: string | null
}

/**
 * نموذج إنشاء/تعديل تصنيف وثائق — عند التعديل الاسم فقط قابل للتغيير
 * (DocumentCategoryUpdate بالباك-إند لا يسمح بتغيير النطاق أو الإدارة بعد
 * الإنشاء)، لذلك حقلا النطاق والإدارة يظهران فقط عند الإنشاء.
 */
export function DocumentCategoryFormModal({
  open,
  onClose,
  category,
  departments,
  allowGlobal,
  allowDepartment,
  onSubmit,
  loading,
  serverError,
}: DocumentCategoryFormModalProps) {
  const isEdit = !!category

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { scope: allowGlobal ? 'global' : 'department' },
  })

  const scope = watch('scope')

  useEffect(() => {
    if (open) {
      reset({
        name: category?.name ?? '',
        scope: category?.scope ?? (allowGlobal ? 'global' : 'department'),
        department_id: category?.department_id ?? '',
      })
    }
  }, [open, category, allowGlobal, reset])

  const scopeOptions = [
    ...(allowGlobal ? [{ value: 'global', label: 'عام (لكل الشركة)' }] : []),
    ...(allowDepartment ? [{ value: 'department', label: 'خاص بإدارة معيّنة' }] : []),
  ]

  const departmentOptions = departments.map((d) => ({ value: d.dep_id, label: d.name }))

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'تعديل التصنيف' : 'إضافة تصنيف جديد'}
      description={isEdit ? `تعديل اسم "${category?.name}"` : 'أدخل بيانات التصنيف الجديج'}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button form="document-category-form" type="submit" loading={loading} icon={<Save size={16} />}>
            {isEdit ? 'حفظ التعديلات' : 'إضافة التصنيف'}
          </Button>
        </>
      }
    >
      <form
        id="document-category-form"
        onSubmit={handleSubmit((values) =>
          onSubmit({
            name: values.name,
            scope: values.scope,
            department_id: values.scope === 'department' ? values.department_id || null : null,
          }),
        )}
        className="flex flex-col gap-4"
      >
        <Input
          label="اسم التصنيف"
          required
          placeholder="مثال: محاضر الاجتماعات"
          error={errors.name?.message}
          {...register('name')}
        />

        {!isEdit && (
          <>
            <Select
              label="النطاق"
              required
              options={scopeOptions}
              error={errors.scope?.message}
              {...register('scope')}
            />
            {scope === 'department' && (
              <Select
                label="الإدارة"
                required
                placeholder="اختر الإدارة"
                options={departmentOptions}
                error={errors.department_id?.message}
                {...register('department_id')}
              />
            )}
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
