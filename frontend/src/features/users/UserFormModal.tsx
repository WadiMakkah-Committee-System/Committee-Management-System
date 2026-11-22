import { useEffect, useRef } from 'react'
import { Controller, useFieldArray, useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Copy, Plus, RefreshCw, Save, Trash2 } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { CreatableSelect } from '@/components/ui/CreatableSelect'
import { useToast } from '@/components/ui/Toast'
import { useRoleOptions } from '@/hooks/useRoles'
import { useUserDetail } from '@/hooks/useUsers'
import { useCreateJobTitle, useJobTitles } from '@/hooks/useJobTitles'
import {
  generateTemporaryPassword,
  PRELAUNCH_INITIAL_PASSWORD,
  suggestUsernameFromEmail,
} from '@/lib/credentialSuggestions'
import { assignedRoles, roleLabel } from '@/lib/utils'
import type { Department, User, UserAssignmentInput, UserCreatePayload, UserUpdatePayload } from '@/types'

const baseFields = {
  first_name: z.string().min(1, 'الاسم الأول مطلوب').max(100),
  middle_name: z.string().min(1, 'الاسم الأوسط مطلوب').max(100),
  last_name: z.string().min(1, 'اسم العائلة مطلوب').max(100),
  email: z.string().email('بريد إلكتروني غير صحيح'),
  // تعدد الإدارات (migration 0052 — قرار لاما 2026-11-22): صف لكل تعيين
  // (إدارة + دور). [] = بلا دور (مراجعة لاما 2026-08-30: الدور اختياري). أول
  // تعيين = دوره الحالي عند أول دخول، ويبدّل بين أدواره من الشريط العلوي.
  assignments: z.array(
    z.object({
      dep_id: z.string(),
      role_id: z.string().min(1, 'اختر الدور'),
    }),
  ),
  // الإدارة الأساسية (للعرض) — من إدارات التعيينات، أو أي إدارة لو بلا تعيينات.
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

type AssignmentRow = { dep_id: string; role_id: string }

/**
 * تعيينات المستخدم كصفوف النموذج: الدور الحالي أولًا (فيبقى الحالي بعد الحفظ)،
 * وأدواره المسندة بلا إدارة محددة تظهر بـ"بدون إدارة". مستخدم بلا
 * assignments محمّلة: كل دور على إدارته الأساسية (نفس معنى ما قبل 0052).
 */
function assignmentRows(user: User): AssignmentRow[] {
  const currentId = user.role?.role_id
  const rows: AssignmentRow[] = user.assignments
    ? user.assignments.map((a) => ({ dep_id: a.department.dep_id, role_id: a.role.role_id }))
    : []
  const withDep = new Set(rows.map((r) => r.role_id))
  for (const role of assignedRoles(user)) {
    if (!withDep.has(role.role_id)) {
      rows.push({ dep_id: user.assignments ? '' : (user.dep_id ?? ''), role_id: role.role_id })
    }
  }
  return [...rows.filter((r) => r.role_id === currentId), ...rows.filter((r) => r.role_id !== currentId)]
}

function toPayload(rows: AssignmentRow[]): UserAssignmentInput[] {
  return rows.map((r) => ({ role_id: r.role_id, dep_id: r.dep_id || null }))
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
  // تعدد الأدوار/الإدارات (0046/0052): بعض الشاشات (أعضاء الإدارة) تمرّر
  // مستخدمًا بدون أدواره وتعييناته كاملة — نجلب تفاصيله عند فتح النموذج حتى
  // يعرض كل تعييناته، بدل أن يظهر بعضها ثم يُحفظ ناقصًا.
  const rolesUnknown = isEdit && open && (!user?.roles || !user?.assignments)
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
  // الإدارة التابعة تظهر باسم أمها (هيكل المستويين — migration 0048).
  const departmentName = new Map(departments.map((d) => [d.dep_id, d.name]))
  const departmentLabel = (d: Department) =>
    d.parent_dep_id && departmentName.has(d.parent_dep_id)
      ? `${departmentName.get(d.parent_dep_id)} ← ${d.name}`
      : d.name
  const depOptions = [
    { value: '', label: 'بدون إدارة' },
    ...departments.map((d) => ({ value: d.dep_id, label: departmentLabel(d) })),
  ]
  const roleOptions = systemRoles.map((r) => ({ value: r.role_id, label: roleLabel(r) }))
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
    resetField,
    formState: { errors, isSubmitted, dirtyFields },
  } = useForm<CreateFormValues | EditFormValues>({
    resolver: zodResolver(isEdit ? editSchema : createSchema),
  })

  const { fields, append, remove } = useFieldArray({ control, name: 'assignments' })

  // هل عدّل السوبر ادمن اسم المستخدم يدويًا؟ طالما لا، يتبع الحقل
  // البريد الإلكتروني تلقائيًا. إذا مسح الحقل بالكامل يعود الاقتراح التلقائي.
  const usernameEditedManually = useRef(false)
  const detailRef = useRef<User | undefined>(undefined)
  // قبل تأثير reset أدناه (التأثيرات تعمل بترتيب تعريفها).
  useEffect(() => {
    detailRef.current = rolesUnknown ? userDetail : undefined
  }, [rolesUnknown, userDetail])

  useEffect(() => {
    if (open) {
      usernameEditedManually.current = false
      reset({
        first_name: user?.first_name ?? '',
        middle_name: user?.middle_name ?? '',
        last_name: user?.last_name ?? '',
        email: user?.email ?? '',
        // التفاصيل الكاملة لو وصلت قبل الفتح (من الكاش) — وإلا تُحدَّث عند وصولها أدناه.
        assignments: user ? assignmentRows(detailRef.current ?? user) : [],
        dep_id: user?.dep_id ?? defaultDepId ?? '',
        job_title_id: user?.job_title_id ?? '',
        // كلمة المرور المؤقتة تُملأ تلقائيًا عند فتح نموذج الإضافة (قابلة للتعديل).
        // مؤقت قبل التدشين: الكلمة الموحّدة PRELAUNCH_INITIAL_PASSWORD بدل
        // generateTemporaryPassword() — يوم التدشين أرجعها كما كانت.
        ...(isEdit ? {} : { username: '', password: PRELAUNCH_INITIAL_PASSWORD, status: 'active' }),
      } as CreateFormValues)
    }
  }, [open, user, isEdit, defaultDepId, reset])

  // وصلت تعيينات المستخدم الكاملة (حين لم تكن مع بيانات الشاشة): نحدّث حقل
  // التعيينات وحده — بدون مسح أي تعديل بدأه المسؤول بالحقول الأخرى، وبدون
  // الكتابة فوقه لو عدّله هو بنفسه قبل الوصول.
  useEffect(() => {
    if (!rolesUnknown || !userDetail) return
    if (getFieldState('assignments').isDirty) return
    resetField('assignments', { defaultValue: assignmentRows(userDetail) })
  }, [rolesUnknown, userDetail, getFieldState, resetField])

  const watchedAssignments = useWatch({ control, name: 'assignments' }) as AssignmentRow[] | undefined
  // خيارات الإدارة الأساسية: إدارات التعيينات، وإلا كل الإدارات.
  const assignmentDepIds = [...new Set((watchedAssignments ?? []).map((a) => a.dep_id).filter(Boolean))]
  const primaryOptions = assignmentDepIds.length
    ? depOptions.filter((o) => assignmentDepIds.includes(o.value))
    : depOptions
  const primaryDepId = useWatch({ control, name: 'dep_id' })
  // الإدارة الأساسية لازم تكون من إدارات التعيينات — تُصحَّح تلقائيًا لأولها.
  const assignmentDepKey = assignmentDepIds.join(',')
  useEffect(() => {
    const ids = assignmentDepKey ? assignmentDepKey.split(',') : []
    if (!open || !ids.length || ids.includes(primaryDepId ?? '')) return
    setValue('dep_id', ids[0], { shouldDirty: true })
  }, [open, assignmentDepKey, primaryDepId, setValue])

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
        // التعيينات تُرسَل فقط لو عدّلها المسؤول فعلًا — حماية إضافية من
        // استبدال تعيينات المستخدم بقائمة ناقصة لو تعذّر جلبها كاملة.
        ...((dirtyFields as { assignments?: unknown }).assignments
          ? { assignments: toPayload(v.assignments) }
          : {}),
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
        assignments: toPayload(v.assignments),
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

        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-text-primary">الإدارات والأدوار</span>
          {fields.length === 0 && (
            <p className="rounded-sm border border-dashed border-border-default px-3 py-2 text-xs text-text-muted">
              بلا دور — أضيفي تعيينًا لو يحتاج المستخدم صلاحيات
            </p>
          )}
          {fields.map((item, index) => (
            <div key={item.id} className="flex items-start gap-2">
              <div className="grid flex-1 grid-cols-1 gap-2 sm:grid-cols-2">
                <Select
                  aria-label="الإدارة"
                  options={depOptions}
                  {...register(`assignments.${index}.dep_id` as const)}
                />
                <Select
                  aria-label="الدور"
                  placeholder="اختر الدور"
                  options={roleOptions}
                  error={errors.assignments?.[index]?.role_id?.message}
                  {...register(`assignments.${index}.role_id` as const)}
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label="إزالة التعيين"
                icon={<Trash2 size={14} />}
                className="mt-1"
                onClick={() => remove(index)}
              />
            </div>
          ))}
          <div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => append({ dep_id: primaryDepId || defaultDepId || '', role_id: '' })}
            >
              إضافة إدارة ودور
            </Button>
          </div>
          <p className="text-xs text-text-muted">
            صف لكل إدارة يشتغل فيها المستخدم بدوره فيها (مثل: مدير بالقانونية، وعضو بمكتب الرئيس). أول صف =
            دوره عند أول دخول، ويبدّل بين أدواره من الشريط العلوي — وكل دور تكون صلاحياته على إداراته فقط.
          </p>
        </div>

        <Select
          label="الإدارة الأساسية"
          placeholder="اختر الإدارة"
          options={primaryOptions}
          {...register('dep_id')}
        />

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
