import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowRight,
  CalendarRange,
  CheckCircle2,
  Gavel,
  Pencil,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  UserCheck,
  Vote,
  XCircle,
} from 'lucide-react'
import {
  useApproveDecision,
  useCastVote,
  useDecisionDetail,
  useDeleteDecision,
  useOpenVoting,
  useUpdateDecision,
} from '@/hooks/useDecisions'
import { useCommitteeDetail } from '@/hooks/useCommittees'
import { useAuthStore } from '@/store/authStore'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { ErrorState } from '@/components/ui/ErrorState'
import { Skeleton, TableSkeleton } from '@/components/ui/Skeleton'
import { Avatar } from '@/components/ui/Avatar'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { ActionMenu } from '@/components/ui/ActionMenu'
import { DecisionStatusBadge } from '@/components/ui/StatusBadge'
import { useToast } from '@/components/ui/Toast'
import { DecisionFormModal, type DecisionFormSubmitValues } from './DecisionFormModal'
import { cn, extractErrorMessage, formatDate, formatDateTime } from '@/lib/utils'

/**
 * تفاصيل قرار واحد + التصويت والاعتماد. راجعي رأس decision_service.py
 * بالباك-إند للاجتهادات الموثّقة (إغلاق التصويت الكسلي، منع التعديل بعد
 * فتح التصويت، الاعتماد فعل صريح دائمًا حتى بعد تحقق الأغلبية).
 */
export function DecisionDetailPage() {
  const { decisionId } = useParams<{ decisionId: string }>()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { showToast } = useToast()

  const { data: decision, isLoading, isError, refetch } = useDecisionDetail(decisionId)
  const { data: committee } = useCommitteeDetail(decision?.committee_id)

  const updateMutation = useUpdateDecision()
  const deleteMutation = useDeleteDecision()
  const openVotingMutation = useOpenVoting()
  const castVoteMutation = useCastVote()
  const approveMutation = useApproveDecision()

  const [editOpen, setEditOpen] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [votingDeadline, setVotingDeadline] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)

  const canManage =
    !!user?.role?.is_super_admin || (committee && committee.chair_user_id === user?.user_id)

  const isVoter =
    !!user &&
    !!committee &&
    (committee.chair_user_id === user.user_id ||
      committee.members.some((m) => m.user_id === user.user_id))

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

  if (isError || !decision) {
    return <ErrorState onRetry={() => refetch()} />
  }

  const myVote = decision.votes.find((v) => v.voter.user_id === user?.user_id)
  const canVoteNow = decision.status === 'voting' && isVoter
  const canOpenVoting = canManage && decision.status === 'pending' && decision.classification === 'voting'
  const canApproveFinal = canManage && decision.status === 'pending' && decision.classification === 'final'
  const canApproveAfterVote =
    canManage && decision.status === 'voting' && decision.voting_closed_at !== null

  function handleUpdate(values: DecisionFormSubmitValues) {
    if (!decisionId) return
    setEditError(null)
    updateMutation.mutate(
      {
        decisionId,
        payload: {
          title: values.title,
          classification: values.classification,
          start_date: values.start_date,
          end_date: values.end_date,
        },
      },
      {
        onSuccess: () => {
          setEditOpen(false)
          showToast('تم حفظ التعديلات', 'success')
        },
        onError: (err) => setEditError(extractErrorMessage(err)),
      },
    )
  }

  function handleDelete() {
    if (!decisionId) return
    setDeleteError(null)
    deleteMutation.mutate(decisionId, {
      onSuccess: () => {
        showToast('تم حذف القرار', 'success')
        navigate('/decisions')
      },
      onError: (err) => setDeleteError(extractErrorMessage(err)),
    })
  }

  function handleOpenVoting() {
    if (!decisionId) return
    setActionError(null)
    openVotingMutation.mutate(
      {
        decisionId,
        votingDeadline: votingDeadline ? new Date(votingDeadline).toISOString() : null,
      },
      {
        onSuccess: () => showToast('تم طرح القرار للتصويت', 'success'),
        onError: (err) => setActionError(extractErrorMessage(err)),
      },
    )
  }

  function handleVote(choice: 'approve' | 'reject') {
    if (!decisionId) return
    setActionError(null)
    castVoteMutation.mutate(
      { decisionId, choice },
      {
        onSuccess: () => showToast('تم تسجيل تصويتك', 'success'),
        onError: (err) => setActionError(extractErrorMessage(err)),
      },
    )
  }

  function handleApprove() {
    if (!decisionId) return
    setActionError(null)
    approveMutation.mutate(decisionId, {
      onSuccess: () => showToast('تم اعتماد القرار', 'success'),
      onError: (err) => setActionError(extractErrorMessage(err)),
    })
  }

  const approveCount = decision.votes.filter((v) => v.choice === 'approve').length
  const rejectCount = decision.votes.filter((v) => v.choice === 'reject').length

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-start gap-3">
          <button
            onClick={() => navigate('/decisions')}
            className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="العودة إلى القرارات"
          >
            <ArrowRight size={18} />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-text-primary">{decision.title}</h1>
              <DecisionStatusBadge status={decision.status} />
            </div>
            {committee && <p className="mt-1 text-sm text-text-muted">لجنة: {committee.name}</p>}
          </div>
        </div>
        {canManage && decision.status === 'pending' && (
          <ActionMenu
            items={[
              {
                label: 'تعديل القرار',
                icon: <Pencil size={14} />,
                onClick: () => {
                  setEditError(null)
                  setEditOpen(true)
                },
              },
              {
                label: 'حذف القرار',
                icon: <Trash2 size={14} />,
                tone: 'danger',
                onClick: () => {
                  setDeleteError(null)
                  setDeleteOpen(true)
                },
              },
            ]}
          />
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[
          {
            icon: <Gavel size={20} />,
            tone: 'bg-brand-primary/10 text-brand-primary',
            value: decision.classification === 'final' ? 'قرار نهائي' : 'خاضع للتصويت',
            label: 'تصنيف القرار',
          },
          {
            icon: <CalendarRange size={20} />,
            tone: 'bg-brand-teal/10 text-brand-teal',
            value: `${formatDate(decision.start_date)} — ${formatDate(decision.end_date)}`,
            label: 'فترة التنفيذ',
          },
          {
            icon: <UserCheck size={20} />,
            tone: 'bg-brand-purple/10 text-brand-purple',
            value: String(decision.assignees.length),
            label: 'عدد المنفذين',
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

      {decision.rejection_reason && (
        <Card className="border-danger-border/30 bg-danger-bg">
          <p className="flex items-center gap-2 text-sm font-semibold text-danger">
            <XCircle size={15} />
            سبب الرفض
          </p>
          <p className="mt-1 text-sm text-danger">{decision.rejection_reason}</p>
        </Card>
      )}

      {/* التصويت — يظهر فقط لقرار خاضع للتصويت */}
      {decision.classification === 'voting' && decision.status !== 'pending' && (
        <Card className="p-0">
          <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
              <Vote size={15} />
              التصويت
            </h2>
            {decision.voting_deadline && (
              <span className="text-xs text-text-muted">
                ينتهي: {formatDateTime(decision.voting_deadline)}
              </span>
            )}
          </div>

          <div className="flex flex-col gap-4 p-4">
            <div className="flex items-center gap-4 text-sm">
              <span className="flex items-center gap-1.5 text-success">
                <ThumbsUp size={14} /> {approveCount} موافق
              </span>
              <span className="flex items-center gap-1.5 text-danger">
                <ThumbsDown size={14} /> {rejectCount} غير موافق
              </span>
              <span className="text-text-muted">
                من أصل {(committee?.members.length ?? 0) + (committee?.chair ? 1 : 0)} مصوّتين
              </span>
            </div>

            {canVoteNow && (
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant={myVote?.choice === 'approve' ? 'primary' : 'secondary'}
                  icon={<ThumbsUp size={14} />}
                  onClick={() => handleVote('approve')}
                  loading={castVoteMutation.isPending}
                >
                  موافق
                </Button>
                <Button
                  size="sm"
                  variant={myVote?.choice === 'reject' ? 'danger' : 'secondary'}
                  icon={<ThumbsDown size={14} />}
                  onClick={() => handleVote('reject')}
                  loading={castVoteMutation.isPending}
                >
                  غير موافق
                </Button>
                {myVote && <span className="text-xs text-text-muted">يمكنك تغيير تصويتك قبل إغلاق التصويت</span>}
              </div>
            )}

            <ul className="flex flex-col gap-1.5">
              {decision.votes.map((v) => (
                <li key={v.voter.user_id} className="flex items-center justify-between text-sm">
                  <span className="flex items-center gap-2">
                    <Avatar firstName={v.voter.first_name} lastName={v.voter.last_name} size={24} />
                    {v.voter.first_name} {v.voter.last_name}
                  </span>
                  <span className={v.choice === 'approve' ? 'text-success' : 'text-danger'}>
                    {v.choice === 'approve' ? 'موافق' : 'غير موافق'}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </Card>
      )}

      {canOpenVoting && (
        <Card>
          <h2 className="text-sm font-semibold text-text-primary">طرح القرار للتصويت</h2>
          <p className="mt-1 text-xs text-text-muted">
            موعد انتهاء اختياري — بدونه يُغلق التصويت فقط عند اكتمال تصويت جميع الأعضاء.
          </p>
          <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
            <Input
              type="datetime-local"
              label="موعد انتهاء التصويت (اختياري)"
              value={votingDeadline}
              onChange={(e) => setVotingDeadline(e.target.value)}
              className="sm:max-w-xs"
            />
            <Button
              icon={<Vote size={16} />}
              onClick={handleOpenVoting}
              loading={openVotingMutation.isPending}
            >
              طرح للتصويت
            </Button>
          </div>
        </Card>
      )}

      {(canApproveFinal || canApproveAfterVote) && (
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-text-primary">اعتماد القرار</h2>
              <p className="mt-1 text-xs text-text-muted">
                {canApproveAfterVote
                  ? 'تحقّقت الأغلبية المطلوبة — الاعتماد يبقى بحاجة تأكيدك الصريح'
                  : 'قرار نهائي — الاعتماد يرسل إشعارًا مباشرًا للمنفذين'}
              </p>
            </div>
            <Button icon={<CheckCircle2 size={16} />} onClick={handleApprove} loading={approveMutation.isPending}>
              اعتماد القرار
            </Button>
          </div>
        </Card>
      )}

      {actionError && (
        <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
          {actionError}
        </p>
      )}

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <UserCheck size={15} />
            المنفذون
          </h2>
        </div>
        <ul>
          {decision.assignees.map((a, i) => (
            <motion.li
              key={a.user_id}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.15, delay: Math.min(i * 0.02, 0.2) }}
              className="flex items-center gap-3 border-b border-border-default px-4 py-3 last:border-0"
            >
              <Avatar firstName={a.first_name} lastName={a.last_name} />
              <p className="font-medium text-text-primary">
                {a.first_name} {a.last_name}
              </p>
            </motion.li>
          ))}
        </ul>
      </Card>

      <p className="text-xs text-text-muted">أُنشئ القرار في {formatDateTime(decision.created_at)}</p>

      {canManage && (
        <>
          <DecisionFormModal
            open={editOpen}
            onClose={() => setEditOpen(false)}
            committees={committee ? [committee] : []}
            decision={decision}
            onSubmit={handleUpdate}
            loading={updateMutation.isPending}
            serverError={editError}
          />
          <ConfirmDialog
            open={deleteOpen}
            onClose={() => setDeleteOpen(false)}
            onConfirm={handleDelete}
            title="حذف القرار"
            description={`سيتم حذف قرار "${decision.title}" نهائيًا. هل أنتِ متأكدة؟`}
            confirmLabel="حذف"
            loading={deleteMutation.isPending}
            errorMessage={deleteError}
          />
        </>
      )}
    </div>
  )
}
