import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight, CalendarDays, FileText, Mail, Users as UsersIcon } from 'lucide-react'
import { useCommitteeDetail } from '@/hooks/useCommittees'
import { useAuthStore } from '@/store/authStore'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { ErrorState } from '@/components/ui/ErrorState'
import { Skeleton, TableSkeleton } from '@/components/ui/Skeleton'
import { Avatar } from '@/components/ui/Avatar'
import { cn, formatDate, formatDateTime } from '@/lib/utils'

/**
 * تفاصيل لجنة معتمدة واحدة — Phase 5، عرض فقط (Read-only). لا أي إجراء
 * تعديل/إضافة/حذف أعضاء هنا عمدًا — قرار موثّق من Lama (راجعي
 * project_memory: phase2-committee-formation-requests.md).
 */
export function CommitteeDetailPage() {
  const { committeeId } = useParams<{ committeeId: string }>()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { data: committee, isLoading, isError, refetch } = useCommitteeDetail(committeeId)

  const isSuperAdmin = !!user?.role.is_super_admin
  const permissions = user?.permissions ?? []
  const canViewSourceRequest = isSuperAdmin || permissions.includes('committees.request.view')

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-8 w-56" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <div className="overflow-hidden rounded-md border border-border-default bg-bg-surface">
          <TableSkeleton />
        </div>
      </div>
    )
  }

  if (isError || !committee) {
    return <ErrorState onRetry={() => refetch()} />
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-start gap-3">
          <button
            onClick={() => navigate('/committees/approved')}
            className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="العودة إلى اللجان المعتمدة"
          >
            <ArrowRight size={18} />
          </button>
          <div>
            <h1 className="text-xl font-bold text-text-primary">{committee.name}</h1>
            <p className="mt-1 text-sm text-text-muted">لجنة معتمدة رسميًا</p>
          </div>
        </div>
        {canViewSourceRequest && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/committees/requests/${committee.source_request_id}`)}
          >
            عرض طلب التشكيل الأصلي
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[
          {
            icon: <CalendarDays size={20} />,
            tone: 'bg-brand-teal/10 text-brand-teal',
            value: `${formatDate(committee.start_date)} — ${formatDate(committee.end_date)}`,
            label: 'فترة عمل اللجنة',
          },
          {
            icon: <UsersIcon size={20} />,
            tone: 'bg-brand-purple/10 text-brand-purple',
            value: String(committee.members.length),
            label: 'عدد الأعضاء',
          },
          {
            icon: <CalendarDays size={20} />,
            tone: 'bg-brand-primary/10 text-brand-primary',
            value: formatDate(committee.created_at),
            label: 'تاريخ الاعتماد',
          },
        ].map((item, i) => (
          <motion.div
            key={item.label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: i * 0.05, ease: 'easeOut' }}
          >
            <Card className="flex items-center gap-4">
              <div className={cn('flex h-12 w-12 shrink-0 items-center justify-center rounded-full', item.tone)}>
                {item.icon}
              </div>
              <div>
                <p className="text-sm font-semibold text-text-primary">{item.value}</p>
                <p className="mt-1 text-xs text-text-muted">{item.label}</p>
              </div>
            </Card>
          </motion.div>
        ))}
      </div>

      {committee.statement && (
        <Card>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <FileText size={15} />
            بيان/غرض اللجنة
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-text-secondary">{committee.statement}</p>
        </Card>
      )}

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <UsersIcon size={15} />
            أعضاء اللجنة
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-right text-sm">
            <thead>
              <tr className="border-b border-border-default bg-table-header">
                <th className="px-4 py-3 font-semibold text-text-secondary">العضو</th>
                <th className="px-4 py-3 font-semibold text-text-secondary">البريد الإلكتروني</th>
              </tr>
            </thead>
            <tbody>
              {committee.members.map((member, i) => (
                <motion.tr
                  key={member.user_id}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.15, delay: Math.min(i * 0.02, 0.2) }}
                  className="border-b border-border-default last:border-0"
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <Avatar firstName={member.first_name} lastName={member.last_name} />
                      <p className="font-medium text-text-primary">
                        {member.first_name} {member.last_name}
                      </p>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className="flex items-center gap-1.5 text-text-secondary">
                      <Mail size={13} />
                      {member.email}
                    </span>
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <p className="text-xs text-text-muted">أُنشئت اللجنة في {formatDateTime(committee.created_at)}</p>
    </div>
  )
}
