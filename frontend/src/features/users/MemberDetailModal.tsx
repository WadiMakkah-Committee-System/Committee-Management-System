import { useState } from 'react'
import { Ban, Mail, Pencil, RotateCcw, UserMinus, Building2, KeySquare } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { Avatar } from '@/components/ui/Avatar'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { RoleBadge, UserStatusBadge } from '@/components/ui/StatusBadge'
import { useToast } from '@/components/ui/Toast'
import { Skeleton } from '@/components/ui/Skeleton'
import { useUserDetail, useSuspendUser, useReactivateUser, useUpdateUser } from '@/hooks/useUsers'
import { usePermissionsCatalog } from '@/hooks/useRoles'
import { extractErrorMessage } from '@/lib/utils'

interface MemberDetailModalProps {
  userId: string | null
  onClose: () => void
  onEdit: (userId: string) => void
  /** يظهر زر "إزالة من الإدارة" فقط عند فتح النافذة من سياق إدارة معيّنة. */
  allowRemoveFromDepartment?: boolean
}

export function MemberDetailModal({
  userId,
  onClose,
  onEdit,
  allowRemoveFromDepartment,
}: MemberDetailModalProps) {
  const { data: user, isLoading } = useUserDetail(userId ?? undefined)
  const { data: permissions } = usePermissionsCatalog()
  const suspendMutation = useSuspendUser()
  const reactivateMutation = useReactivateUser()
  const updateMutation = useUpdateUser()
  const { showToast } = useToast()

  const [statusError, setStatusError] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [removeError, setRemoveError] = useState<string | null>(null)

  const labelByCode = new Map((permissions ?? []).map((p) => [p.code, p.label_ar]))

  function handleToggleStatus() {
    if (!user) return
    setStatusError(null)
    if (user.status === 'active') {
      suspendMutation.mutate(user.user_id, {
        onSuccess: () => showToast('تم إيقاف الحساب بنجاح', 'success'),
        onError: (err) => setStatusError(extractErrorMessage(err)),
      })
    } else {
      reactivateMutation.mutate(user.user_id, {
        onSuccess: () => showToast('تم تفعيل الحساب بنجاح', 'success'),
        onError: (err) => setStatusError(extractErrorMessage(err)),
      })
    }
  }

  function handleRemoveFromDepartment() {
    if (!user) return
    setRemoveError(null)
    updateMutation.mutate(
      { userId: user.user_id, payload: { dep_id: null } },
      {
        onSuccess: () => {
          setConfirmRemove(false)
          showToast('تمت إزالة العضو من الإدارة', 'success')
          onClose()
        },
        onError: (err) => setRemoveError(extractErrorMessage(err)),
      },
    )
  }

  return (
    <>
      <Modal open={!!userId} onClose={onClose} title="تفاصيل العضو" size="md">
        {isLoading || !user ? (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <Skeleton className="h-14 w-14 rounded-full" />
              <div className="flex flex-1 flex-col gap-2">
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-3 w-1/3" />
              </div>
            </div>
            <Skeleton className="h-24 w-full" />
          </div>
        ) : (
          <div className="flex flex-col gap-5">
            <div className="flex items-center gap-3">
              <Avatar firstName={user.first_name} lastName={user.last_name} size={56} />
              <div>
                <p className="text-base font-bold text-text-primary">
                  {user.first_name} {user.middle_name} {user.last_name}
                </p>
                <p className="text-sm text-text-muted">@{user.username}</p>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 rounded-sm border border-border-default p-4 sm:grid-cols-2">
              <div className="flex items-center gap-2 text-sm">
                <Mail size={15} className="text-text-muted" />
                <span className="text-text-secondary">{user.email}</span>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <Building2 size={15} className="text-text-muted" />
                <span className="text-text-secondary">{user.department?.name ?? 'بدون إدارة'}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-text-muted">الدور:</span>
                <RoleBadge role={user.role} />
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-text-muted">الحالة:</span>
                <UserStatusBadge status={user.status} />
              </div>
            </div>

            <div>
              <p className="mb-2 flex items-center gap-1.5 text-sm font-medium text-text-primary">
                <KeySquare size={14} />
                الصلاحيات المرتبطة به ({user.permissions.length})
              </p>
              {user.permissions.length === 0 ? (
                <p className="text-sm text-text-muted">لا توجد صلاحيات مرتبطة بدور هذا العضو</p>
              ) : (
                <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
                  {user.permissions.map((code) => (
                    <span
                      key={code}
                      className="rounded-xs bg-bg-elevated px-2 py-1 text-xs text-text-secondary"
                    >
                      {labelByCode.get(code) ?? code}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {statusError && (
              <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
                {statusError}
              </p>
            )}

            <div className="flex flex-wrap items-center gap-2 border-t border-border-default pt-4">
              <Button size="sm" variant="secondary" icon={<Pencil size={14} />} onClick={() => onEdit(user.user_id)}>
                تعديل بيانات العضو
              </Button>
              <Button
                size="sm"
                variant={user.status === 'active' ? 'danger' : 'primary'}
                icon={user.status === 'active' ? <Ban size={14} /> : <RotateCcw size={14} />}
                loading={suspendMutation.isPending || reactivateMutation.isPending}
                onClick={handleToggleStatus}
              >
                {user.status === 'active' ? 'إيقاف الحساب' : 'تفعيل الحساب'}
              </Button>
              {allowRemoveFromDepartment && user.dep_id && (
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<UserMinus size={14} />}
                  onClick={() => {
                    setRemoveError(null)
                    setConfirmRemove(true)
                  }}
                >
                  إزالة من الإدارة
                </Button>
              )}
            </div>
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={confirmRemove}
        onClose={() => setConfirmRemove(false)}
        onConfirm={handleRemoveFromDepartment}
        title="إزالة العضو من الإدارة"
        description={`سيبقى حساب "${user?.first_name} ${user?.last_name}" في النظام، لكن بدون ارتباط بأي إدارة.`}
        confirmLabel="إزالة من الإدارة"
        loading={updateMutation.isPending}
        errorMessage={removeError}
      />
    </>
  )
}
