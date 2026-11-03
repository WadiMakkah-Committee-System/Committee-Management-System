import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Vote as VoteIcon, X } from 'lucide-react'
import { useToast } from '@/components/ui/Toast'
import { useCastVote, useMeetingDecisions } from '@/hooks/useDecisions'
import { cn, extractErrorMessage } from '@/lib/utils'
import type { Decision, DecisionVoteOption } from '@/types'

/**
 * نافذة التصويت فوق الفيديو (قرار لاما 2026-11-03):
 * أول ما يفتح الرئيس التصويت على قرار بهالاجتماع، تطلع لكل عضو مكلّف بالتصويت
 * وما صوّت بعد. يصوت منها مباشرة، أو يسكّرها ويصوت بعدين من تبويب "القرارات".
 * قواعد التصويت نفسها (الخيارات، خيار "ممتنع" بسبب إلزامي، النتيجة بالأغلبية —
 * FR-DEC-009..012) يطبّقها الباك-إند كما هي — هذي واجهة ثانية لنفس العملية.
 *
 * المدخلات: meetingId، currentUserId، onOpenDecisions (فتح تبويب القرارات).
 */
export function VotingOverlay({
  meetingId,
  currentUserId,
  onOpenDecisions,
}: {
  meetingId: string
  currentUserId: string
  onOpenDecisions: () => void
}) {
  const { data: decisions } = useMeetingDecisions(meetingId)
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  // أول قرار مفتوح للتصويت: أنا مكلّف فيه، ما صوّتت، وما سكّرت نافذته.
  const pending = useMemo<Decision | undefined>(
    () =>
      decisions?.find(
        (d) =>
          d.status === 'voting' &&
          !dismissed.has(d.decision_id) &&
          d.assignees.some((a) => a.user_id === currentUserId) &&
          !d.votes.some((v) => v.voter.user_id === currentUserId),
      ),
    [decisions, dismissed, currentUserId],
  )

  return (
    <AnimatePresence>
      {pending && (
        <motion.div
          key={pending.decision_id}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 16 }}
          className="pointer-events-auto absolute inset-x-0 bottom-4 z-20 mx-auto w-[min(440px,calc(100%-2rem))]"
        >
          <VoteCard
            decision={pending}
            onClose={() => setDismissed((prev) => new Set(prev).add(pending.decision_id))}
            onOpenDecisions={() => {
              setDismissed((prev) => new Set(prev).add(pending.decision_id))
              onOpenDecisions()
            }}
          />
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function VoteCard({
  decision,
  onClose,
  onOpenDecisions,
}: {
  decision: Decision
  onClose: () => void
  onOpenDecisions: () => void
}) {
  const { showToast } = useToast()
  const castVote = useCastVote()
  const [abstainOption, setAbstainOption] = useState<DecisionVoteOption | null>(null)
  const [reason, setReason] = useState('')

  async function vote(option: DecisionVoteOption, abstainReason?: string) {
    try {
      await castVote.mutateAsync({ decisionId: decision.decision_id, optionId: option.option_id, reason: abstainReason })
      showToast('تم تسجيل صوتك', 'success')
    } catch (err) {
      showToast(extractErrorMessage(err), 'error')
    }
  }

  const options = [...decision.vote_options].sort((a, b) => a.sort_order - b.sort_order)

  return (
    <div className="rounded-lg bg-bg-surface p-4 shadow-2xl ring-1 ring-border-default">
      <div className="mb-3 flex items-start gap-2">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-primary/10 text-brand-primary">
          <VoteIcon size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold text-brand-primary">تصويت مفتوح الآن</p>
          <p className="text-[14px] font-semibold leading-relaxed text-text-primary">{decision.title}</p>
          <p className="text-[11px] text-text-muted">
            {decision.votes.length} / {decision.assignees.length} صوّتوا
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="إغلاق — أصوّت لاحقًا"
          title="إغلاق — أصوّت لاحقًا من تبويب القرارات"
          className="shrink-0 rounded-sm p-1 text-text-muted hover:bg-bg-elevated hover:text-text-primary"
        >
          <X size={16} />
        </button>
      </div>

      {abstainOption ? (
        <div className="flex flex-col gap-2">
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            placeholder="سبب الامتناع (إلزامي)"
            className="rounded-sm border border-border-default bg-bg-app p-2 text-[13px] text-text-primary focus:border-brand-primary focus:outline-none"
          />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={!reason.trim() || castVote.isPending}
              onClick={() => void vote(abstainOption, reason.trim())}
              className="h-9 flex-1 rounded-sm bg-brand-primary text-[13px] font-semibold text-white disabled:opacity-50"
            >
              تأكيد الامتناع
            </button>
            <button
              type="button"
              onClick={() => setAbstainOption(null)}
              className="h-9 rounded-sm px-3 text-[13px] text-text-secondary hover:text-text-primary"
            >
              رجوع
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {options.map((opt) => (
            <button
              key={opt.option_id}
              type="button"
              disabled={castVote.isPending}
              onClick={() => (opt.is_abstain ? setAbstainOption(opt) : void vote(opt))}
              className={cn(
                'h-10 min-w-[90px] flex-1 rounded-sm border px-3 text-[13px] font-semibold transition-colors disabled:opacity-60',
                opt.is_abstain
                  ? 'border-border-default text-text-secondary hover:bg-bg-elevated'
                  : opt.is_approving
                    ? 'border-status-success-main text-status-success-main hover:bg-success-bg'
                    : 'border-danger text-danger hover:bg-danger-bg',
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={onOpenDecisions}
        className="mt-3 text-[11px] font-medium text-brand-primary hover:underline"
      >
        فتح تبويب القرارات
      </button>
    </div>
  )
}
