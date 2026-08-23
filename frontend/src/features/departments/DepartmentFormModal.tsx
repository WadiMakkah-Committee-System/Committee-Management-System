import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Save } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { useUsers } from '@/hooks/useUsers'
import type { Department } from '@/types'

const schema = z.object({
  name: z.string().min(2, 'اسم الإدارة يجب أن يكون حرفين على الأقل').max(150),
  code: z
    .string()
    .min(1, 'الرمز التعريفي مطلوب')
    .max(20, 'الرمز التعريفي طويل جدًا (٢٠ حرفًا كحد أقصى)'),
  description: z.string().max(500).optional(),
  manager_user_id: z.string().min(1, 'المسؤول عن الإدارة مطلوب'),
})

type FormValues = z.infer<typeof schema>

interface DepartmentFormModalProps {
  open: boolean
  onClose: () => void
  department?: Department | null
  onSubmit: (values: { name: string; code: string; description: string | null; manager_user_id: string }) => void
  loading?: boolean
  serverError?: string | null
}

export function DepartmentFormModal({
  open,
  onClose,
  department,
  onSubmit,
  loading,
  serverError,
}: DepartmentFormModalProps) {
  const isEdit = !!department
  const { data: users } = useUsers()
  const managerOptions = (users ?? []).map((u) => ({
    value: u.user_id,
    label: `${u.first_name} ${u.last_name}`,
  }))

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  useEffect(() => {
    if (open) {
      reset({
        name: department?.name ?? '',
        code: department?.code ?? '',
        description: department?.description ?? '',
        manager_user_id: department?.manager?.user_id ?? '',
      })
    }
  }, [open, department, reset])

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'تعديل الإدارة' : 'إضافة إدارة جديدة'}
      description={isEdit ? `تعديل بيانات "${department?.name}"` : 'أدخل بيانات الإدارة الجديدة'}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button form="department-form" type="submit" loading={loading} icon={<Save size={16} />}>
            {isEdit ? 'حفظ التعديلات' : 'إضافة الإدارة'}
          </Button>
        </>
      }
    >
      <form
        id="department-form"
        onSubmit={handleSubmit((values) =>
          onSubmit({
            name: values.name,
            code: values.code.trim(),
            description: values.description?.trim() || null,
            manager_user_id: values.manager_user_id,
          }),
        )}
        className="flex flex-col gap-4"
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="sm:col-span-2">
            <Input
              label="اسم الإدارة"
              required
              placeholder="مثال: إدارة تقنية المعلومات"
              error={errors.name?.message}
              {...register('name')}
            />
          </div>
          <Input
            label="الرمز التعريفي"
            required
            placeholder="مثال: IT"
            error={errors.code?.message}
            {...register('code')}
          />
        </div>
        <Input
          label="الوصف"
          placeholder="وصف مختصر لمهام الإدارة (اختياري)"
          error={errors.description?.message}
          {...register('description')}
        />
        <div className="flex flex-col gap-1">
          <Select
            label="المسؤول عن الإدارة"
            required
            placeholder="اختر المسؤول عن الإدارة"
            options={managerOptions}
            error={errors.manager_user_id?.message}
            {...register('manager_user_id')}
          />
          {!errors.manager_user_id && (
            <p className="text-xs text-text-muted">يُضاف تلقائيًا كعضو في هذه الإدارة</p>
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
