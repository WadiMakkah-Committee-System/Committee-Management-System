import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Save } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import type { JobTitle } from '@/types'

const schema = z.object({
  name: z.string().min(2, 'المسمى الوظيفي يجب أن يكون حرفين على الأقل').max(150),
})

type FormValues = z.infer<typeof schema>

interface JobTitleFormModalProps {
  open: boolean
  onClose: () => void
  jobTitle?: JobTitle | null
  onSubmit: (values: { name: string }) => void
  loading?: boolean
  serverError?: string | null
}

/** نموذج إنشاء/تعديل مسمى وظيفي — بنفس نمط DepartmentFormModal، بحقل واحد فقط (name). */
export function JobTitleFormModal({ open, onClose, jobTitle, onSubmit, loading, serverError }: JobTitleFormModalProps) {
  const isEdit = !!jobTitle

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  useEffect(() => {
    if (open) {
      reset({ name: jobTitle?.name ?? '' })
    }
  }, [open, jobTitle, reset])

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'تعديل المسمى الوظيفي' : 'إضافة مسمى وظيفي'}
      description={isEdit ? `تعديل "${jobTitle?.name}"` : 'أدخل اسم المسمى الوظيفي الجديد'}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button form="job-title-form" type="submit" loading={loading} icon={<Save size={16} />}>
            {isEdit ? 'حفظ التعديلات' : 'إضافة المسمى الوظيفي'}
          </Button>
        </>
      }
    >
      <form
        id="job-title-form"
        onSubmit={handleSubmit((values) => onSubmit({ name: values.name.trim() }))}
        className="flex flex-col gap-4"
      >
        <Input
          label="اسم المسمى الوظيفي"
          required
          placeholder="مثال: مديرة تقنية المعلومات"
          error={errors.name?.message}
          {...register('name')}
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
