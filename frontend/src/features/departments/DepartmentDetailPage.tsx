import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight, Building2, FileText, Mail, Plus, UserRound, Users as UsersIcon } from 'lucide-react'
import { useDepartmentDetail } from '@/hooks/useDepartments'
import { useUpdateUser, useUsers } from '@/hooks/useUsers'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { StatCard } from '@/components/ui/StatCard'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { Skeleton, TableSkeleton } from '@/components/ui/Skeleton'
import { Avatar } from '@/components/ui/Avatar'
import { UserStatusBadge, RoleBadge } from '@/components/ui/StatusBadge'
import { useToast } from '@/components/ui/Toast'
import { UserFormModal } from '@/features/users/UserFormModal'
import { MemberDetailModal } from '@/features/users/MemberDetailModal'
import { AssignExistingUserModal } from './AssignExistingUserModal'
import { extractErrorMessage, formatDate } from '@/lib/utils'
import type { User, UserUpdatePayload } from '@/types'

/**
 * صفحة تفاصيل إدارة واحدة — الاسم، الوصف، عدد الأعضاء، وقائمة الأعضاء
 * كاملة، بالإضافة إلى إمكانية إضافة مستخدم **موجود مسبقًا** لهذه الإدارة
 * (AssignExistingUserModal — PATCH /users/{id} بحقل dep_id فقط). إنشاء
 * مستخدم جديد بالكامل انتقل حصرًا لصفحة "المستخدمين" (UsersPage) — قرار
 * موثّق مع المستخدمة 2026-09-13: زر "إضافة مستخدم" هنا كان يفتح نموذج
 * تسجيل مستخدم جديد دائمًا، حتى لو المطلوب فعليًا نقل مستخدم موجود من
 * إدارة أخرى أو بدون إدارة. UserFormModal ما زال مستخدَمًا هنا لكن فقط
 * لتعديل بيانات عضو موجود أصلاً بالإدارة (من MemberDetailModal.onEdit).
 */
export function DepartmentDetailPage() {
  const { depId } = useParams<{ depId: string }>()
  const navigate = useNavigate()
  const { data: detail, isLoading, isError, refetch } = useDepartmentDetail(depId)
  const { data: allUsers } = useUsers()
  const updateMutation = useUpdateUser()
  const assignMutation = useUpdateUser()
  const { showToast } = useToast()

  const [formOpen, setFormOpen] = useState(false)
  const [editingMember, setEditingMember] = useState<User | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [detailUserId, setDetailUserId] = useState<string | null>(null)
  const [assignOpen, setAssignOpen] = useState(false)
  const [assignError, setAssignError] = useState<string | null>(null)

  function openAssignModal() {
    setAssignError(null)
    setAssignOpen(true)
  }

  /** مرشّحو الإضافة = كل مستخدمي النظام ما عدا من هو أصلاً عضو بهذه الإدارة. */
  const assignCandidates = (allUsers ?? []).filter((u) => u.dep_id !== detail?.dep_id)

  function handleAssignExisting(userId: string) {
    if (!detail) return
    setAssignError(null)
    assignMutation.mutate(
      { userId, payload: { dep_id: detail.dep_id } },
      {
        onSuccess: () => {
          setAssignOpen(false)
          showToast('تمت إضافة المستخدم إلى الإدارة بنجاح', 'success')
        },
        onError: (err) => setAssignError(extractErrorMessage(err)),
      },
    )
  }

  function handleEdit(values: UserUpdatePayload) {
    if (!editingMember) return
    setFormError(null)
    updateMutation.mutate(
      { userId: editingMember.user_id, payload: values },
      {
        onSuccess: () => {
          setFormOpen(false)
          showToast('تم تحديث بيانات العضو بنجاح', 'success')
        },
        onError: (err) => setFormError(extractErrorMessage(err)),
      },
    )
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <div className="overflow-hidden rounded-md border border-border-default bg-bg-surface">
          <TableSkeleton />
        </div>
      </div>
    )
  }

  if (isError || !detail) {
    return <ErrorState onRetry={() => refetch()} />
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-start gap-3">
          <button
            onClick={() => navigate('/departments')}
            className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="العودة إلى الإدارات"
          >
            <ArrowRight size={18} />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-text-primary">{detail.name}</h1>
              {detail.code && (
                <span className="rounded-xs bg-bg-elevated px-1.5 py-0.5 text-[10px] font-semibold text-text-muted">
                  {detail.code}
                </span>
              )}
            </div>
            <p className="mt-1 text-sm text-text-muted">{detail.description || 'لا يوجد وصف'}</p>
          </div>
        </div>
        <Button icon={<Plus size={16} />} onClick={openAssignModal}>
          إضافة مستخدم
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard label="عدد الأعضاء" value={detail.member_count} icon={<UsersIcon size={20} />} tone="brand" />
        <StatCard
          label="المسؤول عن الإدارة"
          value={detail.manager ? `${detail.manager.first_name} ${detail.manager.last_name}` : '—'}
          icon={<UserRound size={20} />}
          tone="orange"
        />
        <StatCard
          label="أُنشئت في"
          value={formatDate(detail.created_at)}
          icon={<Building2 size={20} />}
          tone="purple"
        />
      </div>

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <FileText size={15} />
            أعضاء الإدارة
          </h2>
        </div>

        {detail.members.length === 0 ? (
          <div className="p-2">
            <EmptyState
              icon={<UsersIcon size={26} />}
              title="لا يوجد أعضاء في هذه الإدارة بعد"
              description="ابدأ بإضافة أول عضو لهذه الإدارة"
              action={
                <Button size="sm" icon={<Plus size={14} />} onClick={openAssignModal}>
                  إضافة مستخدم
                </Button>
              }
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-right text-sm">
              <thead>
                <tr className="border-b border-border-default bg-table-header">
                  <th className="px-4 py-3 font-semibold text-text-secondary">العضو</th>
                  <th className="px-4 py-3 font-semibold text-text-secondary">الدور</th>
                  <th className="px-4 py-3 font-semibold text-text-secondary">الحالة</th>
                </tr>
              </thead>
              <tbody>
                {detail.members.map((member, i) => (
                  <motion.tr
                    key={member.user_id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.15, delay: Math.min(i * 0.02, 0.2) }}
                    onClick={() => setDetailUserId(member.user_id)}
                    className="cursor-pointer border-b border-border-default transition-colors last:border-0 hover:bg-table-hover"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <Avatar firstName={member.first_name} lastName={member.last_name} />
                        <div>
                          <p className="font-medium text-text-primary">
                            {member.first_name} {member.last_name}
                          </p>
                          <p className="flex items-center gap-1 text-xs text-text-muted">
                            <Mail size={11} />
                            {member.email}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <RoleBadge role={member.role} />
                    </td>
                    <td className="px-4 py-3">
                      <UserStatusBadge status={member.status} />
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <UserFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        user={editingMember}
        departments={[detail]}
        defaultDepId={detail.dep_id}
        onSubmitCreate={() => {}}
        onSubmitEdit={handleEdit}
        loading={updateMutation.isPending}
        serverError={formError}
      />

      <AssignExistingUserModal
        open={assignOpen}
        onClose={() => setAssignOpen(false)}
        candidates={assignCandidates}
        onAssign={handleAssignExisting}
        loading={assignMutation.isPending}
        serverError={assignError}
      />

      <MemberDetailModal
        userId={detailUserId}
        onClose={() => setDetailUserId(null)}
        onEdit={(userId) => {
          const target = detail.members.find((m) => m.user_id === userId)
          if (target) {
            setDetailUserId(null)
            setEditingMember(target)
            setFormError(null)
            setFormOpen(true)
          }
        }}
        allowRemoveFromDepartment
      />
    </div>
  )
}
