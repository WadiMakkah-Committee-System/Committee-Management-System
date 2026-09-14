import { useState } from 'react'
import { Plus, Trash2, Vote as VoteIcon } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Avatar } from '@/components/ui/Avatar'
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
import type { Decision, DecisionClassification, DecisionVoteOptionInput } from '@/types'

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
  const totalEligible = Math.max(decision.assignees.length, 1)

  // بلاغ لاما 2026-09-13 (لايف): كانت خيارات التصويت هنا ثابتة (موافق/غير
  // موافق) رغم أن الباك-إند وDecisionDetailPage.tsx يدعمان خيارات رئيسة
  // اللجنة الحرة منذ 2026-09-07 — نفس القدرة الآن هنا (نسخة مختصرة تناسب
  // عرض اللوحة الجانبية 340px)، بدل الاضطرار للخروج من غرفة الاجتماع.
  const [showVotingForm, setShowVotingForm] = useState(false)
  const [optionInputs, setOptionInputs] = useState<DecisionVoteOptionInput[]>([
    { label: 'موافق', is_approving: true },
    { label: 'غير موافق', is_approving: false },
  ])
  const [optionsError, setOptionsError] = useState<string | null>(null)

  async function vote(optionId: string) {
    try {
      await castVoteMutation.mutateAsync({ decisionId: decision.decision_id, optionId })
    } catch (err) {
      showToast(extractErrorMessage(err), 'error')
    }
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

  async function openVoting() {
    setOptionsError(null)
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
    try {
      await openVotingMutation.mutateAsync({
        decisionId: decision.decision_id,
        payload: { options: cleaned },
      })
      showToast('تم فتح التصويت على القرار')
      setShowVotingForm(false)
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

      {decision.status === 'pending' && decision.classification === 'voting' && !showVotingForm && (
        <Button size="sm" variant="secondary" onClick={() => setShowVotingForm(true)}>
          فتح التصويت
        </Button>
      )}

      {decision.status === 'pending' && decision.classification === 'voting' && showVotingForm && (
        <div className="flex flex-col gap-2 rounded-sm border border-border-default bg-bg-elevated p-2.5">
          <p className="text-[11px] text-text-muted">حدّدي خيارات التصويت (خيارين على الأقل)</p>
          {optionInputs.map((opt, index) => (
            <div key={index} className="flex items-center gap-1.5">
              <Input
                placeholder={`الخيار ${index + 1}`}
                value={opt.label}
                onChange={(e) => updateOption(index, { label: e.target.value })}
                className="flex-1"
              />
              <label className="flex shrink-0 items-center gap-1 text-[10px] text-text-secondary">
                <input
                  type="checkbox"
                  checked={opt.is_approving}
                  onChange={(e) => updateOption(index, { is_approving: e.target.checked })}
                  className="h-3.5 w-3.5 rounded-xs border-border-default text-brand-primary focus:ring-brand-accent/40"
                />
                موافقة
              </label>
              {optionInputs.length > 2 && (
                <button
                  type="button"
                  onClick={() => removeOption(index)}
                  className="shrink-0 rounded-sm p-1 text-text-muted transition-colors hover:bg-danger-bg hover:text-danger"
                  aria-label="حذف الخيار"
                >
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            onClick={addOption}
            className="flex w-fit items-center gap-1 rounded-sm px-1.5 py-1 text-[11px] font-medium text-brand-primary transition-colors hover:bg-brand-primary/10"
          >
            <Plus size={12} /> إضافة خيار
          </button>
          {optionsError && <p className="text-[11px] font-medium text-danger">{optionsError}</p>}
          <div className="flex gap-1.5">
            <Button size="sm" onClick={openVoting} loading={openVotingMutation.isPending}>
              تأكيد فتح التصويت
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setShowVotingForm(false)}>
              إلغاء
            </Button>
          </div>
        </div>
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
          {decision.vote_options.map((opt) => {
            const count = decision.votes.filter((v) => v.option.option_id === opt.option_id).length
            const selected = myVote?.option.option_id === opt.option_id
            return (
              <button
                key={opt.option_id}
                type="button"
                disabled={!!myVote || castVoteMutation.isPending}
                onClick={() => vote(opt.option_id)}
                className={cn(
                  'flex items-center justify-between rounded-sm border px-2.5 py-1.5 text-[12px] transition-colors',
                  selected
                    ? 'border-brand-primary bg-brand-primary/5 text-brand-primary'
                    : 'border-border-default text-text-secondary hover:border-border-strong disabled:cursor-not-allowed',
                )}
              >
                <span>{opt.label}</span>
                <span className="flex items-center gap-2">
                  <span className="h-1.5 w-16 overflow-hidden rounded-full bg-bg-elevated">
                    <span
                      className={cn(
                        'block h-full',
                        opt.is_approving ? 'bg-status-success-main' : 'bg-danger',
                      )}
                      style={{ width: `${(count / totalEligible) * 100}%` }}
                    />
                  </span>
                  <span className="font-mono">{count}</span>
                </span>
              </button>
            )
          })}

          {/* إصلاح 2026-09-14 (بلاغ لاما — "عند التصويت ما يظهر مين اللي
             ضغط موافق ومين اللي ضغط غير موافق، سوي نفس اللي بواجهة
             القرارات"): نفس قائمة "مَن صوّت وبأي خيار" الموجودة أصلًا
             بـDecisionDetailPage.tsx، بنسخة مختصرة تناسب عرض 340px هنا.
             لا حاجة لفحص صلاحية إضافي بالواجهة — الباك-إند نفسه يحرّر
             (يحذف) تصويتات البقية من decision.votes لمن لا يملك
             decisions.vote.view_result (راجعي _redact_votes_if_unauthorized
             بـdecision_service.py)، فعضو اللجنة العادي يرى صوته فقط تلقائيًا
             هنا أيضًا — بلا أي تسريب خصوصية. */}
          {decision.votes.length > 0 && (
            <ul className="mt-1 flex flex-col gap-1 border-t border-border-default pt-2">
              {decision.votes.map((v) => (
                <li key={v.voter.user_id} className="flex items-center justify-between text-[11px]">
                  <span className="flex items-center gap-1.5 text-text-secondary">
                    <Avatar firstName={v.voter.first_name} lastName={v.voter.last_name} size={18} />
                    {v.voter.first_name} {v.voter.last_name}
                  </span>
                  <span className={v.option.is_approving ? 'text-status-success-main' : 'text-text-muted'}>
                    {v.option.label}
                  </span>
                </li>
              ))}
            </ul>
          )}
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
  canCreate,
  meetingScheduledAt,
  meetingScheduledEndAt,
}: {
  meetingId: string
  committeeId: string
  currentUserId: string
  /** بلاغ لاما 2026-09-13: زر "قرار جديد" يجب أن يتبع نفس صلاحية
   * DecisionsPage.tsx (canCreateAnyDecision) — رئيس اللجنة أو
   * decisions.create بنطاق 'all'، وليس أي مشارك بالاجتماع. */
  canCreate: boolean
  /** بلاغ لاما 2026-09-13: "شيلي حقلي التاريخ — المفترض القرار ينتهي
   * بانتهاء الاجتماع تلقائيًا". تُستخدَم لاشتقاق start_date/end_date
   * بدل إدخالهما يدويًا (راجعي handleCreate أدناه). */
  meetingScheduledAt: string
  meetingScheduledEndAt: string | null
}) {
  const { showToast } = useToast()
  const decisionsQuery = useMeetingDecisions(meetingId)
  const createMutation = useCreateDecision()

  const [showForm, setShowForm] = useState(false)
  const [title, setTitle] = useState('')
  const [classification, setClassification] = useState<DecisionClassification>('voting')
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
        // بلاغ لاما 2026-09-13: بلا اختيار يدوي — تاريخ البداية = اليوم
        // (لحظة الإنشاء)، والنهاية = تاريخ انتهاء هذا الاجتماع نفسه
        // (scheduled_end_at) — أو تاريخ بدايته لو اجتماع قديم بلا نهاية
        // مجدولة (نادر جدًا، قبل migration 0023).
        start_date: todayIso(),
        end_date: (meetingScheduledEndAt ?? meetingScheduledAt).slice(0, 10),
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
        {canCreate && (
          <Button size="sm" variant="secondary" icon={<Plus size={14} />} onClick={() => setShowForm((s) => !s)}>
            قرار جديد
          </Button>
        )}
      </div>

      {canCreate && showForm && (
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
          <p className="text-[11px] text-text-muted">
            ينتهي هذا القرار تلقائيًا بانتهاء الاجتماع الحالي.
          </p>
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
