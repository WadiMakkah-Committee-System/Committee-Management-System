import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowRight,
  CalendarRange,
  CheckCircle2,
  Gavel,
  Pencil,
  Plus,
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
import { cn, extractErrorMessage, formatDate, formatDateTime, scopeFor } from '@/lib/utils'
import type { DecisionVoteOptionInput } from '@/types'

/**
 * تفاصيل قرار واحد + التصويت والاعتماد. راجعي رأس decision_service.py
 * بالباك-إند للاجتهادات الموثّقة (إغلاق التصويت الكسلي، منع التعديل بعد
 * فتح التصويت، الاعتماد فعل صريح دائمًا حتى بعد تحقق الأغلبية).
 *
 * تحديث 2026-09-07 (قرار صريح: "الي يحدد بيانات التصويت رئيس اللجنة بس
 * والأعضاء يقررون"): خيارات التصويت لم تعد ثابتة (موافق/غير موافق) —
 * رئيسة اللجنة تكتبها بنفسها عند فتح التصويت (قسم "طرح للتصويت" أدناه)،
 * والأعضاء يصوّتون لأحد هذه الخيارات المحدَّدة. الافتراضي المعروض عند
 * فتح النموذج هو موافق/غير موافق (الحالة الأكثر شيوعًا)، وقابل للتعديل
 * أو الاستبدال بالكامل بأي خيارات أخرى قبل الإرسال.
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
  const [optionInputs, setOptionInputs] = useState<DecisionVoteOptionInput[]>([
    { label: 'موافق', is_approving: true },
    { label: 'غير موافق', is_approving: false },
  ])
  const [optionsError, setOptionsError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  /**
   * تصحيح 2026-09-02 — نفس إصلاح MeetingDetailPage.tsx.canManage بالضبط.
   */
  const canManage =
    scopeFor(
      user,
      'decisions.update',
      'decisions.delete',
      'decisions.vote.open',
      'decisions.approve',
    ) === 'all' || (committee && committee.chair_user_id === user?.user_id)

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

  function updateOption(index: number, patch: Partial<DecisionVoteOptionInput>) {
    setOptionInputs((prev) => prev.map((opt, i) => (i === index ? { ...opt, ...patch } : opt)))
  }

  function addOption() {
    setOptionInputs((prev) => [...prev, { label: '', is_approving: false }])
  }

  function removeOption(index: number) {
    setOptionInputs((prev) => prev.filter((_, i) => i !== index))
  }

  function handleOpenVoting() {
    if (!decisionId) return
    setOptionsError(null)
    setActionError(null)

    const cleaned = optionInputs.map((o) => ({ ...o, label: o.label.trim() })).filter((o) => o.label)
    if (cleaned.length < 2) {
      setOptionsError('أدخلي خيارين على الأقل')
      return
    }
    const labels = cleaned.map((o) => o.label)
    if (new Set(labels).size !== labels.length) {
      setOptionsError('لا يمكن تكرار نفس نص الخيار')
      return
    }

    openVotingMutation.mutate(
      {
        decisionId,
        payload: {
          options: cleaned,
          voting_deadline: votingDeadline ? new Date(votingDeadline).toISOString() : null,
        },
      },
      {
        onSuccess: () => showToast('تم طرح القرار للتصويت', 'success'),
        onError: (err) => setActionError(extractErrorMessage(err)),
      },
    )
  }

  function handleVote(optionId: string) {
    if (!decisionId) return
    setActionError(null)
    castVoteMutation.mutate(
      { decisionId, optionId },
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

  const voteCountsByOption = new Map<string, number>()
  for (const v of decision.votes) {
    voteCountsByOption.set(v.option.option_id, (voteCountsByOption.get(v.option.option_id) ?? 0) + 1)
  }
  const totalVoters = (committee?.members.length ?? 0) + (committee?.chair ? 1 : 0)

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

      {/* التصويت — يظهر فقط لقرار خاضع للتصويت وبعد فتحه فعليًا */}
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
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
              {decision.vote_options.map((opt) => (
                <span
                  key={opt.option_id}
                  className={cn(
                    'flex items-center gap-1.5',
                    opt.is_approving ? 'text-success' : 'text-text-secondary',
                  )}
                >
                  {opt.label}: {voteCountsByOption.get(opt.option_id) ?? 0}
                </span>
              ))}
              <span className="text-text-muted">من أصل {totalVoters} مصوّتين</span>
            </div>

            {canVoteNow && (
              <div className="flex flex-wrap items-center gap-2">
                {decision.vote_options.map((opt) => (
                  <Button
                    key={opt.option_id}
                    size="sm"
                    variant={myVote?.option.option_id === opt.option_id ? 'primary' : 'secondary'}
                    onClick={() => handleVote(opt.option_id)}
                    loading={castVoteMutation.isPending}
                  >
                    {opt.label}
                  </Button>
                ))}
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
                  <span className={v.option.is_approving ? 'text-success' : 'text-text-secondary'}>
                    {v.option.label}
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
            حدّدي خيارات التصويت بنفسك (موافق/غير موافق افتراضيًا، ويمكنك تعديلها أو إضافة خيارات أخرى).
            علّمي "تُحسب موافقة" على أي خيار يُعتبر تأييدًا للقرار — تُستخدم لحساب الأغلبية تلقائيًا.
          </p>

          <div className="mt-3 flex flex-col gap-2">
            {optionInputs.map((opt, index) => (
              <div key={index} className="flex items-center gap-2">
                <Input
                  placeholder={`الخيار ${index + 1}`}
                  value={opt.label}
                  onChange={(e) => updateOption(index, { label: e.target.value })}
                  className="flex-1"
                />
                <label className="flex shrink-0 items-center gap-1.5 text-xs text-text-secondary">
                  <input
                    type="checkbox"
                    checked={opt.is_approving}
                    onChange={(e) => updateOption(index, { is_approving: e.target.checked })}
                    className="h-4 w-4 rounded-xs border-border-default text-brand-primary focus:ring-brand-accent/40"
                  />
                  تُحسب موافقة
                </label>
                {optionInputs.length > 2 && (
                  <button
                    type="button"
                    onClick={() => removeOption(index)}
                    className="shrink-0 rounded-sm p-1.5 text-text-muted transition-colors hover:bg-danger-bg hover:text-danger"
                    aria-label="حذف الخيار"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              onClick={addOption}
              className="flex w-fit items-center gap-1.5 rounded-sm px-2 py-1.5 text-xs font-medium text-brand-primary transition-colors hover:bg-brand-primary/10"
            >
              <Plus size={13} /> إضافة خيار
            </button>
            {optionsError && <p className="text-xs font-medium text-danger">{optionsError}</p>}
          </div>

          <p className="mt-4 text-xs text-text-muted">
            موعد انتهاء اختياري — بدونه يُغلق التصويت فقط عند اكتمال تصويت جميع الأعضاء.
          </p>
          <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-end">
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
                  ? 'التصويت انتهى — الاعتماد يبقى بحاجة تأكيدك الصريح بناءً على النتائج'
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
