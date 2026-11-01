import { useEffect, useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Save, Users as UsersIcon } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useUsers } from '@/hooks/useUsers'
import type { Department } from '@/types'
import { DepartmentUserPicker } from './DepartmentUserPicker'

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

/** قيم النموذج المُرسَلة للصفحة — member_user_ids موجودة بالإنشاء فقط. */
export interface DepartmentFormSubmitValues {
  name: string
  code: string
  description: string | null
  manager_user_id: string
  member_user_ids?: string[]
}

interface DepartmentFormModalProps {
  open: boolean
  onClose: () => void
  department?: Department | null
  onSubmit: (values: DepartmentFormSubmitValues) => void
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
  const { data: users } = useUsers({ enabled: open })

  /** المحدَّدون الذين لديهم إدارة حالية (سيُنقَلون) — يُعرَضون بنص تأكيد النقل. */
  function usersToMove(ids: string[]) {
    const set = new Set(ids)
    return (users ?? []).filter((u) => set.has(u.user_id) && u.department)
  }
  const managerOptions = (users ?? []).map((u) => ({
    value: u.user_id,
    label: `${u.first_name} ${u.last_name}`,
  }))

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  // أعضاء الإدارة (طلب صاحبة المشروع 2026-10-29) — بالإنشاء فقط؛ التعديل
  // يدير الأعضاء من صفحة تفاصيل الإدارة (AssignExistingUserModal).
  const [memberIds, setMemberIds] = useState<string[]>([])
  /** قيم بانتظار تأكيد نقل أعضاء من إدارات أخرى — null عند عدم وجود تأكيد معلّق. */
  const [pendingValues, setPendingValues] = useState<DepartmentFormSubmitValues | null>(null)
  const managerId = watch('manager_user_id')

  /** المسؤول عضو تلقائيًا بالباك-إند، فيُستبعد من قائمة الاختيار. */
  const memberCandidates = useMemo(
    () => (users ?? []).filter((u) => u.user_id !== managerId),
    [users, managerId],
  )

  useEffect(() => {
    if (open) {
      setMemberIds([])
      setPendingValues(null)
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
      size={isEdit ? 'sm' : 'md'}
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
        onSubmit={handleSubmit((values) => {
          const submitValues: DepartmentFormSubmitValues = {
            name: values.name,
            code: values.code.trim(),
            description: values.description?.trim() || null,
            manager_user_id: values.manager_user_id,
          }
          if (isEdit) {
            onSubmit(submitValues)
            return
          }
          submitValues.member_user_ids = memberIds.filter((id) => id !== values.manager_user_id)
          // من هو بإدارة أخرى سيُنقَل — تأكيد صريح قبل الإرسال (نفس قاعدة AssignExistingUserModal).
          if (usersToMove(submitValues.member_user_ids).length > 0) {
            setPendingValues(submitValues)
            return
          }
          onSubmit(submitValues)
        })}
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
        {!isEdit && (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2 border-b border-border-default pb-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-xs bg-brand-primary/10 text-brand-primary">
                <UsersIcon size={13} />
              </span>
              <h3 className="text-xs font-bold uppercase tracking-wide text-text-secondary">أعضاء الإدارة</h3>
              <span className="text-xs text-text-muted">(اختياري — المسؤول يُضاف تلقائيًا)</span>
            </div>
            <DepartmentUserPicker
              candidates={memberCandidates}
              selectedIds={memberIds}
              onSelectedIdsChange={setMemberIds}
            />
          </div>
        )}
        {serverError && (
          <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
            {serverError}
          </p>
        )}
      </form>

      <ConfirmDialog
        open={!!pendingValues}
        onClose={() => setPendingValues(null)}
        onConfirm={() => {
          if (pendingValues) onSubmit(pendingValues)
          setPendingValues(null)
        }}
        title="تأكيد نقل الأعضاء"
        description={
          pendingValues
            ? 'سيتم نقل الأعضاء التالية أسماؤهم من إداراتهم الحالية إلى الإدارة الجديدة: ' +
              usersToMove(pendingValues.member_user_ids ?? [])
                .map((u) => `${u.first_name} ${u.last_name} (من إدارة ${u.department!.name})`)
                .join('، ') +
              '. هل أنت متأكد من المتابعة؟'
            : ''
        }
        confirmLabel="تأكيد النقل"
        variant="primary"
        loading={loading}
      />
    </Modal>
  )
}
