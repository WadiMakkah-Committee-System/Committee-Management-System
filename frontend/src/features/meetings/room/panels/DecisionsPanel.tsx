import { useState } from 'react'
import { Plus, Vote as VoteIcon } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { EmptyState } from '@/components/ui/EmptyState'
import { Spinner } from '@/components/ui/Spinner'
import { DecisionStatusBadge } from '@/components/ui/StatusBadge'
import { useToast } from '@/components/ui/Toast'
import {
  useApproveDecision,
  useCastVote,
  useCreateDecision,
  useMeetingDecisions,
  useOpenVoting,
} from '@/hooks/useDecisions'
import { cn, extractErrorMessage } from '@/lib/utils'
import type { Decision, DecisionClassification } from '@/types'

const CLASSIFICATION_OPTIONS = [
  { value: 'final', label: 'قرار نهائي (يُعتمد مباشرة)' },
  { value: 'voting', label: 'خاضع للتصويت' },
]

function todayIso(offsetDays = 0): string {
  const d = new Date()
  d.setDate(d.getDate() + offsetDays)
  return d.toISOString().slice(0, 10)
}

function DecisionCard({ decision, currentUserId }: { decision: Decision; currentUserId: string }) {
  const { showToast } = useToast()
  const castVoteMutation = useCastVote()
  const openVotingMutation = useOpenVoting()
  const approveMutation = useApproveDecision()

  const myVote = decision.votes.find((v) => v.voter.user_id === currentUserId)
  const approveCount = decision.votes.filter((v) => v.choice === 'approve').length
  const rejectCount = decision.votes.filter((v) => v.choice === 'reject').length
  const totalEligible = Math.max(decision.assignees.length, 1)

  async function vote(choice: 'approve' | 'reject') {
    try {
      await castVoteMutation.mutateAsync({ decisionId: decision.decision_id, choice })
    } catch (err) {
      showToast(extractErrorMessage(err), 'error')
    }
  }

  async function openVoting() {
    try {
      await openVotingMutation.mutateAsync({ decisionId: decision.decision_id })
      showToast('تم فتح التصويت على القرار')
    } catch (err) {
      showToast(extractErrorMessage(err), 'error')
    }
  }

  async function approve() {
    try {
      await approveMutation.mutateAsync(decision.decision_id)
      showToast('تم اعتماد القرار')
    } catch (err) {
      showToast(extractErrorMessage(err), 'error')
    }
  }

  return (
    <div className="rounded-md border border-border-default bg-bg-surface p-3">
      <div className="mb-2 flex items-start justify-between gap-2">
        <p className="text-[13px] font-semibold leading-relaxed text-text-primary">{decision.title}</p>
        <DecisionStatusBadge status={decision.status} />
      </div>

      {decision.status === 'pending' && decision.classification === 'voting' && (
        <Button size="sm" variant="secondary" onClick={openVoting} loading={openVotingMutation.isPending}>
          فتح التصويت
        </Button>
      )}

      {decision.status === 'pending' && decision.classification === 'final' && (
        <Button size="sm" onClick={approve} loading={approveMutation.isPending}>
          اعتماد القرار
        </Button>
      )}

      {decision.status === 'voting' && (
        <div className="flex flex-col gap-2">
          <p className="text-[11px] text-text-muted">
            {decision.votes.length} / {decision.assignees.length} صوّتوا
          </p>
          {(['approve', 'reject'] as const).map((choice) => {
            const count = choice === 'approve' ? approveCount : rejectCount
            const selected = myVote?.choice === choice
            return (
              <button
                key={choice}
                type="button"
                disabled={!!myVote || castVoteMutation.isPending}
                onClick={() => vote(choice)}
                className={cn(
                  'flex items-center justify-between rounded-sm border px-2.5 py-1.5 text-[12px] transition-colors',
                  selected
                    ? 'border-brand-primary bg-brand-primary/5 text-brand-primary'
                    : 'border-border-default text-text-secondary hover:border-border-strong disabled:cursor-not-allowed',
                )}
              >
                <span>{choice === 'approve' ? 'موافق' : 'غير موافق'}</span>
                <span className="flex items-center gap-2">
                  <span className="h-1.5 w-16 overflow-hidden rounded-full bg-bg-elevated">
                    <span
                      className={cn(
                        'block h-full',
                        choice === 'approve' ? 'bg-status-success-main' : 'bg-danger',
                      )}
                      style={{ width: `${(count / totalEligible) * 100}%` }}
                    />
                  </span>
                  <span className="font-mono">{count}</span>
                </span>
              </button>
            )
          })}
        </div>
      )}

      {decision.status === 'approved' && (
        <p className="rounded-sm bg-success-bg px-2.5 py-1.5 text-center text-[12px] font-semibold text-status-success-main">
          تم الاعتماد
        </p>
      )}
      {decision.status === 'rejected' && (
        <p className="rounded-sm bg-danger-bg px-2.5 py-1.5 text-center text-[12px] font-semibold text-danger">
          {decision.rejection_reason ?? 'تم الرفض'}
        </p>
      )}
    </div>
  )
}

export function DecisionsPanel({
  meetingId,
  committeeId,
  currentUserId,
}: {
  meetingId: string
  committeeId: string
  currentUserId: string
}) {
  const { showToast } = useToast()
  const decisionsQuery = useMeetingDecisions(meetingId)
  const createMutation = useCreateDecision()

  const [showForm, setShowForm] = useState(false)
  const [title, setTitle] = useState('')
  const [classification, setClassification] = useState<DecisionClassification>('voting')
  const [startDate, setStartDate] = useState(todayIso())
  const [endDate, setEndDate] = useState(todayIso(14))
  const [formError, setFormError] = useState<string | null>(null)

  async function handleCreate() {
    setFormError(null)
    if (title.trim().length < 2) {
      setFormError('اسم القرار يجب أن يكون حرفين على الأقل')
      return
    }
    try {
      await createMutation.mutateAsync({
        committee_id: committeeId,
        meeting_id: meetingId,
        title: title.trim(),
        classification,
        start_date: startDate,
        end_date: endDate,
      })
      showToast('تم إنشاء القرار')
      setTitle('')
      setShowForm(false)
    } catch (err) {
      setFormError(extractErrorMessage(err))
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border-default p-3">
        <p className="text-[13px] font-semibold text-text-primary">قرارات هذا الاجتماع</p>
        <Button size="sm" variant="secondary" icon={<Plus size={14} />} onClick={() => setShowForm((s) => !s)}>
          قرار جديد
        </Button>
      </div>

      {showForm && (
        <div className="flex flex-col gap-3 border-b border-border-default bg-bg-elevated p-3">
          <Input
            label="عنوان القرار"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="مثال: اعتماد المورد الجديد"
          />
          <Select
            label="التصنيف"
            options={CLASSIFICATION_OPTIONS}
            value={classification}
            onChange={(e) => setClassification(e.target.value as DecisionClassification)}
          />
          <div className="grid grid-cols-2 gap-2">
            <Input
              label="من"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
            <Input label="إلى" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
          {formError && <p className="text-xs font-medium text-danger">{formError}</p>}
          <Button size="sm" onClick={handleCreate} loading={createMutation.isPending}>
            نشر القرار
          </Button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-3">
        {decisionsQuery.isLoading ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : !decisionsQuery.data?.length ? (
          <EmptyState icon={<VoteIcon size={22} />} title="لا توجد قرارات لهذا الاجتماع بعد" />
        ) : (
          <div className="flex flex-col gap-2.5">
            {decisionsQuery.data.map((decision) => (
              <DecisionCard key={decision.decision_id} decision={decision} currentUserId={currentUserId} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
