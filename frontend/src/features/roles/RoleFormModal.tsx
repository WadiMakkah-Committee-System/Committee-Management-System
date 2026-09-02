import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Save } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { PermissionsPicker } from './PermissionsPicker'
import { usePermissionsCatalog } from '@/hooks/useRoles'
import { TableSkeleton } from '@/components/ui/Skeleton'
import type { Permission, PermissionScope, Role, RoleCreatePayload, RoleUpdatePayload } from '@/types'

const schema = z.object({
  name: z.string().min(2, 'اسم الدور مطلوب (حرفان على الأقل)').max(100),
  description: z.string().max(500).optional(),
})

type FormValues = z.infer<typeof schema>

interface RoleFormModalProps {
  open: boolean
  onClose: () => void
  role?: Role | null
  onSubmitCreate: (values: RoleCreatePayload) => void
  onSubmitEdit: (values: RoleUpdatePayload) => void
  loading?: boolean
  serverError?: string | null
}

export function RoleFormModal({
  open,
  onClose,
  role,
  onSubmitCreate,
  onSubmitEdit,
  loading,
  serverError,
}: RoleFormModalProps) {
  const isEdit = !!role
  const { data: permissions, isLoading: permissionsLoading } = usePermissionsCatalog()
  // مراجعة لاما 2026-08-31 ("أدوار اللجان"): عند تعديل دور لجنة (رئيس/عضو)،
  // تُخفى فقط الأقسام الثلاثة اللي ما تخدم اللجان إطلاقًا (الإدارات،
  // المستخدمون، المسميات الوظيفية) — قرار صريح من لاما: "تظهر كل الأقسام
  // ماعدا أقسام الإدارات والمستخدمون والمسميات الوظيفية لأنها ما تخدم
  // اللجان". بقية الأقسام (اللجان، الاجتماعات، المهام، القرارات، البنود
  // المستخرجة من الذكاء الاصطناعي، الوثائق، المحاضر) تظهر كاملة تمامًا
  // مثل تعديل أي دور نظامي عادي — لا يوجد قسم "أدوار لجان" منفصل، حسب
  // رفض لاما الصريح لهذه الفكرة (مراجعة 2026-09-01): الصلاحيات الحقيقية
  // نفسها هي ما تُختار، وليس نسخة مجردة موازية عنها.
  const CATEGORIES_HIDDEN_FOR_COMMITTEE_ROLE = new Set(['departments', 'users', 'job_titles'])
  const filteredPermissions =
    role?.kind === 'committee'
      ? (permissions ?? []).filter((p) => !CATEGORIES_HIDDEN_FOR_COMMITTEE_ROLE.has(p.category))
      : (permissions ?? [])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [scopes, setScopes] = useState<Record<string, PermissionScope>>({})
  const [permissionsError, setPermissionsError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  useEffect(() => {
    if (open) {
      reset({ name: role?.name ?? '', description: role?.description ?? '' })
      setSelected(new Set((role?.permissions ?? []).map((p: Permission) => p.code)))
      setScopes(
        Object.fromEntries((role?.permissions ?? []).map((p) => [p.code, p.scope])),
      )
      setPermissionsError(null)
    }
  }, [open, role, reset])

  function onValid(values: FormValues) {
    const permission_codes = Array.from(selected)
    if (permission_codes.length === 0) {
      setPermissionsError('يجب اختيار صلاحية واحدة على الأقل')
      return
    }
    setPermissionsError(null)
    // نطاق كل صلاحية محددة فقط — الأكواد غير المحددة لا داعي لإرسال نطاق لها.
    const permission_scopes = Object.fromEntries(
      permission_codes.map((code) => [code, scopes[code] ?? 'all']),
    )
    if (isEdit) {
      onSubmitEdit({
        name: values.name,
        description: values.description || null,
        permission_codes,
        permission_scopes,
      })
    } else {
      onSubmitCreate({
        name: values.name,
        description: values.description || null,
        permission_codes,
        permission_scopes,
      })
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'تعديل الدور' : 'إنشاء دور جديد'}
      description={
        isEdit
          ? role?.kind === 'committee'
            ? `تعديل صلاحيات "${role?.name}" — تنطبق تلقائيًا على كل من يحمل هذا الدور بأي لجنة`
            : `تعديل "${role?.name}"`
          : 'حدد اسم الدور ووصفه، ثم اختر صلاحياته من الأقسام أدناه'
      }
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button form="role-form" type="submit" loading={loading} icon={<Save size={16} />}>
            {isEdit ? 'حفظ التعديلات' : 'إنشاء الدور'}
          </Button>
        </>
      }
    >
      <form id="role-form" onSubmit={handleSubmit(onValid)} className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input
            label="اسم الدور"
            required
            error={errors.name?.message}
            {...register('name')}
          />
          <Input label="الوصف" error={errors.description?.message} {...register('description')} />
        </div>

        <div>
          <p className="mb-2 text-sm font-medium text-text-primary">الصلاحيات ({selected.size} محددة)</p>
          {permissionsLoading ? (
            <TableSkeleton />
          ) : (
            <PermissionsPicker
              permissions={filteredPermissions}
              selected={selected}
              onChange={(next) => {
                setSelected(next)
                if (next.size > 0) setPermissionsError(null)
              }}
              scopes={scopes}
              onScopeChange={(code, scope) => setScopes((prev) => ({ ...prev, [code]: scope }))}
            />
          )}
          {permissionsError && <p className="mt-2 text-sm font-medium text-danger">{permissionsError}</p>}
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
