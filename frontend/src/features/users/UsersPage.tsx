import { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Users as UsersIcon,
  ShieldCheck,
  PauseCircle,
  Plus,
  Pencil,
  Trash2,
  Ban,
  RotateCcw,
  Mail,
} from 'lucide-react'
import {
  useCreateUser,
  useDeleteUser,
  useReactivateUser,
  useSuspendUser,
  useUpdateUser,
  useUsers,
} from '@/hooks/useUsers'
import { useDepartments } from '@/hooks/useDepartments'
import { Button } from '@/components/ui/Button'
import { SearchInput } from '@/components/ui/SearchInput'
import { Select } from '@/components/ui/Select'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { TableSkeleton } from '@/components/ui/Skeleton'
import { ActionMenu } from '@/components/ui/ActionMenu'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { StatCard } from '@/components/ui/StatCard'
import { Avatar } from '@/components/ui/Avatar'
import { UserStatusBadge, RoleBadge } from '@/components/ui/StatusBadge'
import { useToast } from '@/components/ui/Toast'
import { UserFormModal } from './UserFormModal'
import { extractErrorMessage, ROLE_LABELS, ROLE_OPTIONS } from '@/lib/utils'
import type { User, UserCreatePayload, UserUpdatePayload } from '@/types'

const PAGE_SIZE = 10

type PendingAction =
  | { type: 'delete'; user: User }
  | { type: 'suspend'; user: User }
  | { type: 'reactivate'; user: User }
  | null

export function UsersPage() {
  const { data: users, isLoading, isError, refetch } = useUsers()
  const { data: departments } = useDepartments()
  const createMutation = useCreateUser()
  const updateMutation = useUpdateUser()
  const deleteMutation = useDeleteUser()
  const suspendMutation = useSuspendUser()
  const reactivateMutation = useReactivateUser()
  const { showToast } = useToast()

  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(1)

  const [formOpen, setFormOpen] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const [pendingAction, setPendingAction] = useState<PendingAction>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const filtered = useMemo(() => {
    if (!users) return []
    const q = search.trim().toLowerCase()
    return users.filter((u) => {
      const matchesQuery =
        !q ||
        `${u.first_name} ${u.middle_name} ${u.last_name}`.toLowerCase().includes(q) ||
        u.username.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q)
      const matchesRole = !roleFilter || u.role === roleFilter
      const matchesStatus = !statusFilter || u.status === statusFilter
      return matchesQuery && matchesRole && matchesStatus
    })
  }, [users, search, roleFilter, statusFilter])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const stats = useMemo(() => {
    if (!users) return { total: 0, active: 0, suspended: 0 }
    return {
      total: users.length,
      active: users.filter((u) => u.status === 'active').length,
      suspended: users.filter((u) => u.status === 'suspended').length,
    }
  }, [users])

  function resetFiltersPage() {
    setPage(1)
  }

  function openCreateForm() {
    setEditingUser(null)
    setFormError(null)
    setFormOpen(true)
  }

  function openEditForm(user: User) {
    setEditingUser(user)
    setFormError(null)
    setFormOpen(true)
  }

  function handleCreate(values: UserCreatePayload) {
    setFormError(null)
    createMutation.mutate(values, {
      onSuccess: () => {
        setFormOpen(false)
        showToast('تم إضافة المستخدم بنجاح', 'success')
      },
      onError: (err) => setFormError(extractErrorMessage(err)),
    })
  }

  function handleEdit(values: UserUpdatePayload) {
    if (!editingUser) return
    setFormError(null)
    updateMutation.mutate(
      { userId: editingUser.user_id, payload: values },
      {
        onSuccess: () => {
          setFormOpen(false)
          showToast('تم تحديث بيانات المستخدم بنجاح', 'success')
        },
        onError: (err) => setFormError(extractErrorMessage(err)),
      },
    )
  }

  function confirmPendingAction() {
    if (!pendingAction) return
    setActionError(null)
    const { type, user } = pendingAction

    const onError = (err: unknown) => setActionError(extractErrorMessage(err))
    const onSuccess = (message: string) => {
      setPendingAction(null)
      showToast(message, 'success')
    }

    if (type === 'delete') {
      deleteMutation.mutate(user.user_id, { onSuccess: () => onSuccess('تم حذف المستخدم بنجاح'), onError })
    } else if (type === 'suspend') {
      suspendMutation.mutate(user.user_id, { onSuccess: () => onSuccess('تم إيقاف الحساب بنجاح'), onError })
    } else if (type === 'reactivate') {
      reactivateMutation.mutate(user.user_id, { onSuccess: () => onSuccess('تم تفعيل الحساب بنجاح'), onError })
    }
  }

  const actionLoading =
    deleteMutation.isPending || suspendMutation.isPending || reactivateMutation.isPending

  const actionCopy: Record<NonNullable<PendingAction>['type'], { title: string; description: string; confirmLabel: string; variant: 'danger' | 'primary' }> = {
    delete: {
      title: 'حذف المستخدم',
      description: `هل أنت متأكد من حذف "${pendingAction?.user.first_name} ${pendingAction?.user.last_name}"؟ لا يمكن التراجع عن هذا الإجراء.`,
      confirmLabel: 'حذف المستخدم',
      variant: 'danger',
    },
    suspend: {
      title: 'إيقاف الحساب',
      description: `سيتم منع "${pendingAction?.user.first_name} ${pendingAction?.user.last_name}" من تسجيل الدخول حتى إعادة التفعيل.`,
      confirmLabel: 'إيقاف الحساب',
      variant: 'danger',
    },
    reactivate: {
      title: 'إعادة تفعيل الحساب',
      description: `سيتمكّن "${pendingAction?.user.first_name} ${pendingAction?.user.last_name}" من تسجيل الدخول مرة أخرى.`,
      confirmLabel: 'تفعيل الحساب',
      variant: 'primary',
    },
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-xl font-bold text-text-primary">المستخدمون</h1>
          <p className="mt-1 text-sm text-text-muted">إدارة حسابات المستخدمين وأدوارهم في النظام</p>
        </div>
        <Button icon={<Plus size={16} />} onClick={openCreateForm}>
          إضافة مستخدم
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard label="إجمالي المستخدمين" value={stats.total} icon={<UsersIcon size={20} />} />
        <StatCard label="حسابات نشطة" value={stats.active} icon={<ShieldCheck size={20} />} tone="success" />
        <StatCard label="حسابات موقوفة" value={stats.suspended} icon={<PauseCircle size={20} />} tone="warning" />
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput
          value={search}
          onChange={(v) => {
            setSearch(v)
            resetFiltersPage()
          }}
          placeholder="ابحث بالاسم أو اسم المستخدم أو البريد..."
        />
        <div className="grid grid-cols-2 gap-3 sm:w-auto sm:min-w-[340px] sm:grid-cols-2">
          <Select
            aria-label="تصفية حسب الدور"
            options={ROLE_OPTIONS}
            placeholder="كل الأدوار"
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value)
              resetFiltersPage()
            }}
          />
          <Select
            aria-label="تصفية حسب الحالة"
            options={[
              { value: 'active', label: 'نشط' },
              { value: 'suspended', label: 'موقوف' },
            ]}
            placeholder="كل الحالات"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value)
              resetFiltersPage()
            }}
          />
        </div>
      </div>

      {isLoading ? (
        <div className="overflow-hidden rounded-md border border-border-default bg-bg-surface">
          <TableSkeleton />
        </div>
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<UsersIcon size={26} />}
          title={search || roleFilter || statusFilter ? 'لا توجد نتائج مطابقة' : 'لا يوجد مستخدمون بعد'}
          description={
            search || roleFilter || statusFilter ? 'جرّب تعديل معايير البحث أو التصفية' : 'ابدأ بإضافة أول مستخدم في النظام'
          }
          action={
            !search &&
            !roleFilter &&
            !statusFilter && (
              <Button size="sm" icon={<Plus size={14} />} onClick={openCreateForm}>
                إضافة مستخدم
              </Button>
            )
          }
        />
      ) : (
        <div className="overflow-hidden rounded-md border border-border-default bg-bg-surface">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-right text-sm">
              <thead>
                <tr className="border-b border-border-default bg-table-header">
                  <th className="px-4 py-3 font-semibold text-text-secondary">المستخدم</th>
                  <th className="px-4 py-3 font-semibold text-text-secondary">الدور</th>
                  <th className="px-4 py-3 font-semibold text-text-secondary">الإدارة</th>
                  <th className="px-4 py-3 font-semibold text-text-secondary">الحالة</th>
                  <th className="px-4 py-3 font-semibold text-text-secondary"></th>
                </tr>
              </thead>
              <tbody>
                {paginated.map((user, i) => (
                  <motion.tr
                    key={user.user_id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.15, delay: Math.min(i * 0.02, 0.2) }}
                    className="border-b border-border-default transition-colors last:border-0 hover:bg-table-hover"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <Avatar firstName={user.first_name} lastName={user.last_name} />
                        <div>
                          <p className="font-medium text-text-primary">
                            {user.first_name} {user.last_name}
                          </p>
                          <p className="flex items-center gap-1 text-xs text-text-muted">
                            <Mail size={11} />
                            {user.email}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <RoleBadge role={user.role} label={ROLE_LABELS[user.role]} />
                    </td>
                    <td className="px-4 py-3 text-text-secondary">{user.department?.name ?? '—'}</td>
                    <td className="px-4 py-3">
                      <UserStatusBadge status={user.status} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end">
                        <ActionMenu
                          items={[
                            { label: 'تعديل', icon: <Pencil size={14} />, onClick: () => openEditForm(user) },
                            user.status === 'active'
                              ? {
                                  label: 'إيقاف الحساب',
                                  icon: <Ban size={14} />,
                                  tone: 'danger',
                                  onClick: () => {
                                    setActionError(null)
                                    setPendingAction({ type: 'suspend', user })
                                  },
                                }
                              : {
                                  label: 'إعادة تفعيل',
                                  icon: <RotateCcw size={14} />,
                                  onClick: () => {
                                    setActionError(null)
                                    setPendingAction({ type: 'reactivate', user })
                                  },
                                },
                            {
                              label: 'حذف',
                              icon: <Trash2 size={14} />,
                              tone: 'danger',
                              onClick: () => {
                                setActionError(null)
                                setPendingAction({ type: 'delete', user })
                              },
                            },
                          ]}
                        />
                      </div>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t border-border-default px-4 py-3">
              <p className="text-xs text-text-muted">
                عرض {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)} من{' '}
                {filtered.length}
              </p>
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="sm" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
                  السابق
                </Button>
                <span className="text-xs text-text-muted">
                  {page} / {totalPages}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={page === totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  التالي
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      <UserFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        user={editingUser}
        departments={departments ?? []}
        onSubmitCreate={handleCreate}
        onSubmitEdit={handleEdit}
        loading={createMutation.isPending || updateMutation.isPending}
        serverError={formError}
      />

      <ConfirmDialog
        open={!!pendingAction}
        onClose={() => setPendingAction(null)}
        onConfirm={confirmPendingAction}
        title={pendingAction ? actionCopy[pendingAction.type].title : ''}
        description={pendingAction ? actionCopy[pendingAction.type].description : ''}
        confirmLabel={pendingAction ? actionCopy[pendingAction.type].confirmLabel : ''}
        variant={pendingAction ? actionCopy[pendingAction.type].variant : 'danger'}
        loading={actionLoading}
        errorMessage={actionError}
      />
    </div>
  )
}
