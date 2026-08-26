import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Pencil, Plus, ShieldQuestion, Trash2, Users2, KeySquare } from 'lucide-react'
import { useCreateRole, useDeleteRole, useRoles, useUpdateRole } from '@/hooks/useRoles'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { CardSkeleton } from '@/components/ui/Skeleton'
import { ActionMenu } from '@/components/ui/ActionMenu'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/components/ui/Toast'
import { RoleFormModal } from './RoleFormModal'
import { cardToneClass, cn, extractErrorMessage, roleLabel } from '@/lib/utils'
import type { Role, RoleCreatePayload, RoleUpdatePayload } from '@/types'

export function RolesPermissionsPage() {
  const navigate = useNavigate()
  const { data: roles, isLoading, isError, refetch } = useRoles()
  const createMutation = useCreateRole()
  const updateMutation = useUpdateRole()
  const deleteMutation = useDeleteRole()
  const { showToast } = useToast()

  const [formOpen, setFormOpen] = useState(false)
  const [editingRole, setEditingRole] = useState<Role | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  function openCreateForm() {
    setEditingRole(null)
    setFormError(null)
    setFormOpen(true)
  }

  function openEditForm(role: Role) {
    setEditingRole(role)
    setFormError(null)
    setFormOpen(true)
  }

  function handleCreate(values: RoleCreatePayload) {
    setFormError(null)
    createMutation.mutate(values, {
      onSuccess: () => {
        setFormOpen(false)
        showToast('تم إنشاء الدور بنجاح', 'success')
      },
      onError: (err) => setFormError(extractErrorMessage(err)),
    })
  }

  function handleEdit(values: RoleUpdatePayload) {
    if (!editingRole) return
    setFormError(null)
    updateMutation.mutate(
      { roleId: editingRole.role_id, payload: values },
      {
        onSuccess: () => {
          setFormOpen(false)
          showToast('تم تحديث الدور بنجاح', 'success')
        },
        onError: (err) => setFormError(extractErrorMessage(err)),
      },
    )
  }

  function handleDelete() {
    if (!deleteTarget) return
    setDeleteError(null)
    deleteMutation.mutate(deleteTarget.role_id, {
      onSuccess: () => {
        setDeleteTarget(null)
        showToast('تم حذف الدور بنجاح', 'success')
      },
      onError: (err) => setDeleteError(extractErrorMessage(err)),
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-base font-bold text-text-primary">الأدوار والصلاحيات</h2>
          <p className="mt-1 text-sm text-text-muted">
            أنشئ أدوارًا مخصصة وحدد صلاحياتها من الواجهة مباشرة — بدون الحاجة لأي تعديل تقني
          </p>
        </div>
        <Button icon={<Plus size={16} />} onClick={openCreateForm}>
          إنشاء دور جديد
        </Button>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : !roles || roles.length === 0 ? (
        <EmptyState
          icon={<ShieldQuestion size={26} />}
          title="لا توجد أدوار بعد"
          description="ابدأ بإنشاء أول دور مخصص في النظام"
          action={
            <Button size="sm" icon={<Plus size={14} />} onClick={openCreateForm}>
              إنشاء دور جديد
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {roles.map((role, i) => (
            <motion.div
              key={role.role_id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: Math.min(i * 0.03, 0.3) }}
            >
              <Card
                onClick={() => navigate(`/users/roles/${role.role_id}`)}
                className={cn(
                  'flex h-full cursor-pointer flex-col gap-3 transition-shadow hover:shadow-md',
                  cardToneClass(i),
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div
                    className={cn(
                      'flex h-10 w-10 shrink-0 items-center justify-center rounded-sm',
                      role.is_super_admin ? 'bg-danger-bg text-danger' : 'bg-brand-primary/10 text-brand-primary',
                    )}
                  >
                    <ShieldQuestion size={18} />
                  </div>
                  <div onClick={(e) => e.stopPropagation()}>
                    <ActionMenu
                      items={[
                        { label: 'تعديل', icon: <Pencil size={14} />, onClick: () => openEditForm(role) },
                        {
                          label: 'حذف',
                          icon: <Trash2 size={14} />,
                          tone: 'danger',
                          onClick: () => {
                            setDeleteError(null)
                            setDeleteTarget(role)
                          },
                        },
                      ]}
                    />
                  </div>
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold text-text-primary">{roleLabel(role)}</h3>
                    {role.is_system && (
                      <span className="rounded-xs bg-neutral-bg px-1.5 py-0.5 text-[10px] font-semibold text-neutral">
                        نظامي
                      </span>
                    )}
                  </div>
                  <p className="mt-1 line-clamp-2 text-sm text-text-muted">{role.description || 'لا يوجد وصف'}</p>
                </div>
                <div className="mt-auto flex items-center gap-4 border-t border-border-default pt-3 text-xs text-text-muted">
                  <span className="flex items-center gap-1">
                    <KeySquare size={13} />
                    {role.permission_count} صلاحية
                  </span>
                  <span className="flex items-center gap-1">
                    <Users2 size={13} />
                    {role.user_count} مستخدم
                  </span>
                </div>
              </Card>
            </motion.div>
          ))}
        </div>
      )}

      <RoleFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        role={editingRole}
        onSubmitCreate={handleCreate}
        onSubmitEdit={handleEdit}
        loading={createMutation.isPending || updateMutation.isPending}
        serverError={formError}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title="حذف الدور"
        description={`هل أنت متأكد من حذف دور "${deleteTarget ? roleLabel(deleteTarget) : ''}"؟ لا يمكن التراجع عن هذا الإجراء.`}
        confirmLabel="حذف الدور"
        loading={deleteMutation.isPending}
        errorMessage={deleteError}
      />
    </div>
  )
}
