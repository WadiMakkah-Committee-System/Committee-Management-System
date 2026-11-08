import { useEffect, useRef } from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Copy, RefreshCw, Save } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { CreatableSelect } from '@/components/ui/CreatableSelect'
import { MultiCheckPicker } from '@/components/ui/MultiCheckPicker'
import { useToast } from '@/components/ui/Toast'
import { useRoleOptions } from '@/hooks/useRoles'
import { useUserDetail } from '@/hooks/useUsers'
import { useCreateJobTitle, useJobTitles } from '@/hooks/useJobTitles'
import { generateTemporaryPassword, suggestUsernameFromEmail } from '@/lib/credentialSuggestions'
import { assignedRoles, roleLabel } from '@/lib/utils'
import type { Department, RoleOption, User, UserCreatePayload, UserUpdatePayload } from '@/types'

const baseFields = {
  first_name: z.string().min(1, 'الاسم الأول مطلوب').max(100),
  middle_name: z.string().min(1, 'الاسم الأوسط مطلوب').max(100),
  last_name: z.string().min(1, 'اسم العائلة مطلوب').max(100),
  email: z.string().email('بريد إلكتروني غير صحيح'),
  // اختياري (مراجعة لاما 2026-08-30 — "لا تجعل حقل الدور إجباريًا عند إضافة مستخدم").
  // تعدد الأدوار (migration 0046): دور واحد أو أكثر — [] = بلا دور. أول دور
  // مختار = دوره الحالي عند أول دخول (ويبدّل بينها من الشريط العلوي).
  role_ids: z.array(z.string()),
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

/** معرّفات أدوار المستخدم: الدور الحالي أولًا ثم بقية أدواره المسندة (تعدد الأدوار). */
function orderedRoleIds(user: User): string[] {
  const currentId = user.role?.role_id
  return [
    ...(currentId ? [currentId] : []),
    ...assignedRoles(user)
      .map((r) => r.role_id)
      .filter((id) => id !== currentId),
  ]
}

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
  // تعدد الأدوار (migration 0046): بعض الشاشات (أعضاء الإدارة) تمرّر مستخدمًا
  // بدون قائمة أدواره كاملة (roles = null) — نجلب تفاصيله عند فتح النموذج حتى
  // يعرض المنتقي كل أدواره، بدل أن يظهر الدور الحالي وحده ثم يُحفظ وحده.
  const rolesUnknown = isEdit && open && !user?.roles
  const { data: userDetail } = useUserDetail(rolesUnknown ? user?.user_id : undefined)
  // تحديث 2026-09-12 (بلاغ لاما — بطء ملحوظ بكل الصفحات): هذا المودال
  // يُركَّب (mount) ضمن شجرة UsersPage/MeetingFormModal بشكل دائم — كان
  // useRoles/useJobTitles يجلبان بياناتهما فورًا عند التركيب، حتى لو
  // المودال مغلق (open=false) وما حد فاتحه أصلًا، وحتى لو المستخدم
  // الحالي ما عنده صلاحية رؤيتها (403 متكرر بلا فايدة — راجعي شبكة
  // Chrome لصفحات اللجان/الاجتماعات/المهام/القرارات، يطلعان فيها رغم
  // عدم فتح هذا المودال إطلاقًا). enabled: open يمنع الجلب إلا لما
  // المودال يُفتح فعليًا.
  const { data: roles } = useRoleOptions({ enabled: open })
  const { data: jobTitles } = useJobTitles({ enabled: open })
  const createJobTitleMutation = useCreateJobTitle()
  // مراجعة لاما 2026-08-31 ("أدوار اللجان"): "رئيس اللجنة"/"عضو اللجنة" لا
  // يظهران هنا إطلاقًا — ليسا من System Roles، ولا يُسندان كـuser.role_id
  // أبدًا (الباك-إند يرفضها فعليًا أيضًا — راجعي user_service.create_user).
  const systemRoles = (roles ?? []).filter((r) => r.kind === 'user')
  const jobTitleOptions = (jobTitles ?? []).map((jt) => ({ value: jt.job_title_id, label: jt.name }))
  const depOptions = [
    { value: '', label: 'بدون إدارة' },
    ...departments.map((d) => ({ value: d.dep_id, label: d.name })),
  ]
  const statusOptions = [
    { value: 'active', label: 'نشط' },
    { value: 'suspended', label: 'موقوف' },
  ]

  const { showToast } = useToast()

  const {
    register,
    handleSubmit,
    reset,
    control,
    setValue,
    getValues,
    getFieldState,
    formState: { errors, isSubmitted, dirtyFields },
  } = useForm<CreateFormValues | EditFormValues>({
    resolver: zodResolver(isEdit ? editSchema : createSchema),
  })

  // هل عدّل السوبر ادمن اسم المستخدم يدويًا؟ طالما لا، يتبع الحقل
  // البريد الإلكتروني تلقائيًا. إذا مسح الحقل بالكامل يعود الاقتراح التلقائي.
  const usernameEditedManually = useRef(false)

  useEffect(() => {
    if (open) {
      usernameEditedManually.current = false
      reset({
        first_name: user?.first_name ?? '',
        middle_name: user?.middle_name ?? '',
        last_name: user?.last_name ?? '',
        email: user?.email ?? '',
        role_ids: user ? orderedRoleIds(user) : [],
        dep_id: user?.dep_id ?? defaultDepId ?? '',
        job_title_id: user?.job_title_id ?? '',
        // كلمة المرور المؤقتة تُقترح تلقائيًا عند فتح نموذج الإضافة (قابلة للتعديل)
        ...(isEdit ? {} : { username: '', password: generateTemporaryPassword(), status: 'active' }),
      } as CreateFormValues)
    }
  }, [open, user, isEdit, defaultDepId, reset])

  // وصلت أدوار المستخدم الكاملة (حين لم تكن مع بيانات الشاشة): نحدّث حقل
  // الأدوار وحده — بدون مسح أي تعديل بدأه المسؤول بالحقول الأخرى، وبدون
  // الكتابة فوق الأدوار لو عدّلها هو بنفسه قبل الوصول.
  useEffect(() => {
    if (!rolesUnknown || !userDetail) return
    if (getFieldState('role_ids').isDirty) return
    setValue('role_ids', orderedRoleIds(userDetail), { shouldDirty: false })
  }, [rolesUnknown, userDetail, getFieldState, setValue])

  const email = useWatch({ control, name: 'email' })

  // اقتراح اسم المستخدم من البريد أثناء الكتابة (نموذج الإضافة فقط)
  useEffect(() => {
    if (!open || isEdit || usernameEditedManually.current) return
    setValue('username' as 'first_name', suggestUsernameFromEmail(email ?? '') ?? '', {
      shouldValidate: isSubmitted,
    })
  }, [open, isEdit, email, isSubmitted, setValue])

  const usernameField = register('username' as 'first_name')

  /** توليد كلمة مرور مؤقتة جديدة واستبدال الحالية بها. */
  function regeneratePassword() {
    setValue('password' as 'first_name', generateTemporaryPassword(), {
      shouldDirty: true,
      shouldValidate: isSubmitted,
    })
  }

  /** نسخ كلمة المرور المؤقتة الحالية للحافظة لتسليمها للموظف. */
  function copyPassword() {
    const password = (getValues() as CreateFormValues).password ?? ''
    if (!password) return
    navigator.clipboard
      .writeText(password)
      .then(() => showToast('تم نسخ كلمة المرور المؤقتة', 'success'))
      .catch(() => showToast('تعذّر نسخ كلمة المرور', 'error'))
  }

  function onValid(values: CreateFormValues | EditFormValues) {
    if (isEdit) {
      const v = values as EditFormValues
      onSubmitEdit({
        first_name: v.first_name,
        middle_name: v.middle_name,
        last_name: v.last_name,
        email: v.email,
        // تعدد الأدوار: الأدوار تُرسَل فقط لو عدّلها المسؤول فعلًا — حماية
        // إضافية من استبدال أدوار المستخدم بقائمة ناقصة لو تعذّر جلبها كاملة.
        ...((dirtyFields as { role_ids?: unknown }).role_ids ? { role_ids: v.role_ids } : {}),
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
        role_ids: v.role_ids,
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
            autoComplete="off"
            hint="يُقترح تلقائيًا من البريد الإلكتروني ويمكنك تعديله — لا يمكن تعديله بعد إنشاء الحساب"
            error={createErrors.username?.message}
            {...usernameField}
            onChange={(event) => {
              usernameEditedManually.current = event.target.value !== ''
              return usernameField.onChange(event)
            }}
          />
        )}

        <Input
          label="البريد الإلكتروني"
          type="email"
          required
          autoComplete={isEdit ? undefined : 'off'}
          error={errors.email?.message}
          {...register('email')}
        />

        {!isEdit && (
          <div className="flex flex-col gap-2">
            <Input
              label="كلمة المرور المؤقتة"
              type="password"
              required
              // new-password يمنع المتصفح من تعبئة كلمة مرور الادمن المحفوظة هنا
              autoComplete="new-password"
              hint="مولّدة تلقائيًا — انسخها وسلّمها للموظف، وسيُطلب منه تغييرها عند أول تسجيل دخول"
              error={createErrors.password?.message}
              {...register('password' as 'first_name')}
            />
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="ghost" size="sm" icon={<RefreshCw size={14} />} onClick={regeneratePassword}>
                توليد كلمة مرور جديدة
              </Button>
              <Button type="button" variant="ghost" size="sm" icon={<Copy size={14} />} onClick={copyPassword}>
                نسخ
              </Button>
            </div>
          </div>
        )}

        <Controller
          name="role_ids"
          control={control}
          render={({ field }) => (
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium text-text-primary">الأدوار</span>
              <MultiCheckPicker<RoleOption>
                items={systemRoles}
                getId={(r) => r.role_id}
                getLabel={(r) => roleLabel(r)}
                getSublabel={(r) => r.description}
                selected={field.value ?? []}
                onChange={field.onChange}
                searchPlaceholder="ابحث عن دور..."
                emptyText="لا توجد أدوار مطابقة"
                error={errors.role_ids?.message}
              />
              <p className="text-xs text-text-muted">
                {isEdit
                  ? 'يمكن اختيار أكثر من دور — يبقى دوره الحالي كما هو لو ما زال ضمن أدواره، والمستخدم يبدّل بينها من الشريط العلوي'
                  : 'اختياري، ويمكن اختيار أكثر من دور — أول دور تختاره يكون دوره عند أول دخول، ويبدّل بينها من الشريط العلوي'}
              </p>
            </div>
          )}
        />

        <Select label="الإدارة" placeholder="اختر الإدارة" options={depOptions} {...register('dep_id')} />

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
