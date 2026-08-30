import { useEffect } from 'react'
import { Controller, useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Save } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { CreatableSelect } from '@/components/ui/CreatableSelect'
import { useRoles } from '@/hooks/useRoles'
import { useCreateJobTitle, useJobTitles } from '@/hooks/useJobTitles'
import { roleLabel } from '@/lib/utils'
import type { Department, User, UserCreatePayload, UserUpdatePayload } from '@/types'

const baseFields = {
  first_name: z.string().min(1, 'الاسم الأول مطلوب').max(100),
  middle_name: z.string().min(1, 'الاسم الأوسط مطلوب').max(100),
  last_name: z.string().min(1, 'اسم العائلة مطلوب').max(100),
  email: z.string().email('بريد إلكتروني غير صحيح'),
  // اختياري (مراجعة لاما 2026-08-30 — "لا تجعل حقل الدور إجباريًا عند إضافة مستخدم"):
  // '' تعني "غير محدد"، تُحوَّل لـnull عند الإرسال (نفس نمط dep_id/job_title_id).
  role_id: z.string(),
  dep_id: z.string(),
  job_title_id: z.string(),
}

const createSchema = z.object({
  ...baseFields,
  username: z
    .string()
    .min(3, 'اسم المستخدم 3 أحرف على الأقل')
    .max(50)
    .regex(/^[a-zA-Z0-9_.]+$/, 'أحرف إنجليزية وأرقام و . _ فقط'),
  password: z
    .string()
    .min(8, 'يجب أن تحتوي على 8 أحرف على الأقل')
    .regex(/[A-Z]/, 'يجب أن تحتوي على حرف كبير')
    .regex(/[a-z]/, 'يجب أن تحتوي على حرف صغير')
    .regex(/[0-9]/, 'يجب أن تحتوي على رقم'),
  status: z.enum(['active', 'suspended']),
})

const editSchema = z.object(baseFields)

type CreateFormValues = z.infer<typeof createSchema>
type EditFormValues = z.infer<typeof editSchema>

interface UserFormModalProps {
  open: boolean
  onClose: () => void
  user?: User | null
  departments: Department[]
  /** إدارة مبدئية مُختارة مسبقًا (عند الإضافة من داخل صفحة تفاصيل إدارة معيّنة). */
  defaultDepId?: string | null
  onSubmitCreate: (values: UserCreatePayload) => void
  onSubmitEdit: (values: UserUpdatePayload) => void
  loading?: boolean
  serverError?: string | null
}

export function UserFormModal({
  open,
  onClose,
  user,
  departments,
  defaultDepId,
  onSubmitCreate,
  onSubmitEdit,
  loading,
  serverError,
}: UserFormModalProps) {
  const isEdit = !!user
  const { data: roles } = useRoles()
  const { data: jobTitles } = useJobTitles()
  const createJobTitleMutation = useCreateJobTitle()
  const roleOptions = [
    { value: '', label: 'غير محدد' },
    ...(roles ?? []).map((r) => ({ value: r.role_id, label: roleLabel(r) })),
  ]
  const jobTitleOptions = (jobTitles ?? []).map((jt) => ({ value: jt.job_title_id, label: jt.name }))
  const depOptions = [
    { value: '', label: 'بدون إدارة' },
    ...departments.map((d) => ({ value: d.dep_id, label: d.name })),
  ]
  const statusOptions = [
    { value: 'active', label: 'نشط' },
    { value: 'suspended', label: 'موقوف' },
  ]

  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors },
  } = useForm<CreateFormValues | EditFormValues>({
    resolver: zodResolver(isEdit ? editSchema : createSchema),
  })

  useEffect(() => {
    if (open) {
      reset({
        first_name: user?.first_name ?? '',
        middle_name: user?.middle_name ?? '',
        last_name: user?.last_name ?? '',
        email: user?.email ?? '',
        role_id: user?.role?.role_id ?? '',
        dep_id: user?.dep_id ?? defaultDepId ?? '',
        job_title_id: user?.job_title_id ?? '',
        ...(isEdit ? {} : { username: '', password: '', status: 'active' }),
      } as CreateFormValues)
    }
  }, [open, user, isEdit, defaultDepId, reset])

  function onValid(values: CreateFormValues | EditFormValues) {
    if (isEdit) {
      const v = values as EditFormValues
      onSubmitEdit({
        first_name: v.first_name,
        middle_name: v.middle_name,
        last_name: v.last_name,
        email: v.email,
        role_id: v.role_id || undefined,
        dep_id: v.dep_id || null,
        job_title_id: v.job_title_id || null,
      })
    } else {
      const v = values as CreateFormValues
      onSubmitCreate({
        first_name: v.first_name,
        middle_name: v.middle_name,
        last_name: v.last_name,
        username: v.username,
        email: v.email,
        password: v.password,
        role_id: v.role_id || null,
        dep_id: v.dep_id || null,
        job_title_id: v.job_title_id || null,
        status: v.status,
      })
    }
  }

  const createErrors = errors as typeof errors &
    Partial<Record<'username' | 'password' | 'status', { message?: string }>>

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'تعديل بيانات المستخدم' : 'إضافة مستخدم جديد'}
      description={isEdit ? `تعديل بيانات "${user?.first_name} ${user?.last_name}"` : 'أدخل بيانات المستخدم الجديد'}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button form="user-form" type="submit" loading={loading} icon={<Save size={16} />}>
            {isEdit ? 'حفظ التعديلات' : 'إضافة المستخدم'}
          </Button>
        </>
      }
    >
      <form id="user-form" onSubmit={handleSubmit(onValid)} className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Input label="الاسم الأول" required error={errors.first_name?.message} {...register('first_name')} />
          <Input label="الاسم الأوسط" required error={errors.middle_name?.message} {...register('middle_name')} />
          <Input label="اسم العائلة" required error={errors.last_name?.message} {...register('last_name')} />
        </div>

        {!isEdit && (
          <Input
            label="اسم المستخدم"
            required
            hint="يُستخدم لتسجيل الدخول — لا يمكن تعديله لاحقًا"
            error={createErrors.username?.message}
            {...register('username' as 'first_name')}
          />
        )}

        <Input label="البريد الإلكتروني" type="email" required error={errors.email?.message} {...register('email')} />

        {!isEdit && (
          <Input
            label="كلمة المرور المؤقتة"
            type="password"
            required
            hint="سيُطلب من المستخدم تغييرها عند أول تسجيل دخول"
            error={createErrors.password?.message}
            {...register('password' as 'first_name')}
          />
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Select
            label="الدور"
            placeholder="اختر الدور"
            options={roleOptions}
            error={errors.role_id?.message}
            {...register('role_id')}
          />
          <Select label="الإدارة" placeholder="اختر الإدارة" options={depOptions} {...register('dep_id')} />
        </div>

        <Controller
          name="job_title_id"
          control={control}
          render={({ field }) => (
            <CreatableSelect
              label="المسمى الوظيفي"
              placeholder="اختر المسمى الوظيفي"
              clearLabel="بدون مسمى وظيفي"
              options={jobTitleOptions}
              value={field.value ?? ''}
              onChange={field.onChange}
              onCreate={async (name) => {
                const created = await createJobTitleMutation.mutateAsync({ name })
                return { value: created.job_title_id, label: created.name }
              }}
            />
          )}
        />

        {!isEdit && (
          <Select
            label="حالة الحساب"
            options={statusOptions}
            error={createErrors.status?.message}
            {...register('status' as 'first_name')}
          />
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
