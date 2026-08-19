import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Save } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import type { Department } from '@/types'

const schema = z.object({
  name: z.string().min(2, 'اسم الإدارة يجب أن يكون حرفين على الأقل').max(150),
  description: z.string().max(500).optional(),
})

type FormValues = z.infer<typeof schema>

interface DepartmentFormModalProps {
  open: boolean
  onClose: () => void
  department?: Department | null
  onSubmit: (values: { name: string; description: string | null }) => void
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

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  useEffect(() => {
    if (open) {
      reset({ name: department?.name ?? '', description: department?.description ?? '' })
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
          onSubmit({ name: values.name, description: values.description?.trim() || null }),
        )}
        className="flex flex-col gap-4"
      >
        <Input
          label="اسم الإدارة"
          required
          placeholder="مثال: إدارة تقنية المعلومات"
          error={errors.name?.message}
          {...register('name')}
        />
        <Input
          label="الوصف"
          placeholder="وصف مختصر لمهام الإدارة (اختياري)"
          error={errors.description?.message}
          {...register('description')}
        />
        {serverError && (
          <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
            {serverError}
          </p>
        )}
      </form>
    </Modal>
  )
}
