import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { CheckCircle2, Clock3, Eye, Gavel, Plus, Trash2, Vote } from 'lucide-react'
import { useCommittees } from '@/hooks/useCommittees'
import { useCreateDecision, useDecisions, useDeleteDecision, useOpenVoting } from '@/hooks/useDecisions'
import { useAuthStore } from '@/store/authStore'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { SearchInput } from '@/components/ui/SearchInput'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { CardSkeleton } from '@/components/ui/Skeleton'
import { StatCard } from '@/components/ui/StatCard'
import { DecisionStatusBadge } from '@/components/ui/StatusBadge'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/components/ui/Toast'
import { DecisionFormModal, type DecisionFormSubmitValues } from './DecisionFormModal'
import { cardToneClass, extractErrorMessage, formatDate, scopeFor } from '@/lib/utils'
import type { Decision } from '@/types'

/**
 * قائمة القرارات — القرارات المستقلة فقط (بدون قرارات مستخرجة من اجتماع
 * بالذكاء الاصطناعي — تُبنى لاحقًا). راجعي رأس MeetingsPage.tsx لتفصيل
 * سبب عدم حجب هذا المسار خلف صلاحية عامة ثابتة (نفس مبدأ has_any_committee_membership).
 */
export function DecisionsPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { data: decisions, isLoading, isError, refetch } = useDecisions()
  const { data: committees } = useCommittees()
  const createMutation = useCreateDecision()
  const openVotingMutation = useOpenVoting()
  const deleteMutation = useDeleteDecision()
  const { showToast } = useToast()

  const [search, setSearch] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Decision | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  /**
   * اللجان التي يقدر المستخدم الحالي يصدر لها قرارًا — رئيسها، أو أي
   * لجنة إطلاقًا لو يملك decisions.create بنطاق 'all' فعليًا.
   *
   * تصحيح 2026-09-02 (بلاغ خطأ من صاحبة المشروع): نفس إصلاح
   * MeetingsPage.tsx.chairableCommittees بالضبط — راجعي التعليق هناك
   * للتفصيل الكامل. كان يعتمد على user.role?.is_super_admin مباشرة
   * (تجاوز ثابت مخالف لمبدأ النظام)، بدل قراءة الصلاحيات الفعلية.
   */
  const chairableCommittees = useMemo(() => {
    if (!committees || !user) return []
    if (scopeFor(user, 'decisions.create') === 'all') return committees
    return committees.filter((c) => c.chair_user_id === user.user_id)
  }, [committees, user])

  const canCreateAnyDecision = chairableCommittees.length > 0

  const filtered = useMemo(() => {
    if (!decisions) return []
    const q = search.trim().toLowerCase()
    if (!q) return decisions
    return decisions.filter((d) => d.title.toLowerCase().includes(q))
  }, [decisions, search])

  const stats = useMemo(() => {
    const all = decisions ?? []
    return {
      total: all.length,
      pending: all.filter((d) => d.status === 'pending').length,
      voting: all.filter((d) => d.status === 'voting').length,
      approved: all.filter((d) => d.status === 'approved').length,
    }
  }, [decisions])

  /**
   * بلاغ خطأ 2026-09-08: إنشاء قرار "خاضع للتصويت" ثم الحاجة للتنقّل
   * لصفحة تفاصيل منفصلة وفتح قسم "طرح للتصويت" هناك يدويًا كان يُحسّ
   * "خطوة زايدة" — الآن خطوة واحدة من نظر المستخدمة: إنشاء القرار، ثم
   * (لو أُدخلت خيارات تصويت بنفس النموذج) طرحه للتصويت تلقائيًا خلف
   * الكواليس بنداء ثانٍ متسلسل. فشل النداء الثاني لا يُلغي الأول (القرار
   * منشأ فعلًا بحالة pending) — تُعرض رسالة توضيحية وتُفتَح صفحة التفاصيل
   * بأي الحالتين ليكمل المستخدم يدويًا لو احتاج.
   */
  async function handleCreate(values: DecisionFormSubmitValues) {
    setFormError(null)
    const { votingOptions, ...payload } = values
    try {
      const created = await createMutation.mutateAsync(payload)
      if (votingOptions && votingOptions.length >= 2) {
        try {
          await openVotingMutation.mutateAsync({
            decisionId: created.decision_id,
            payload: { options: votingOptions, voting_deadline: null },
          })
          showToast('تم إنشاء القرار وطرحه للتصويت بنجاح', 'success')
        } catch (err) {
          showToast(
            `تم إنشاء القرار، لكن تعذّر طرحه للتصويت تلقائيًا: ${extractErrorMessage(err)}`,
            'error',
          )
        }
      } else {
        showToast('تم إنشاء القرار بنجاح', 'success')
      }
      setFormOpen(false)
      navigate(`/decisions/${created.decision_id}`)
    } catch (err) {
      setFormError(extractErrorMessage(err))
    }
  }

  function handleDeleteConfirm() {
    if (!deleteTarget) return
    setDeleteError(null)
    deleteMutation.mutate(deleteTarget.decision_id, {
      onSuccess: () => {
        setDeleteTarget(null)
        showToast('تم حذف القرار', 'success')
      },
      onError: (err) => setDeleteError(extractErrorMessage(err)),
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-xl font-bold text-text-primary">القرارات</h1>
          <p className="mt-1 text-sm text-text-muted">
            {canCreateAnyDecision
              ? 'إصدار ومتابعة قرارات اللجان التي ترأسها'
              : 'متابعة قرارات اللجان التي أنت عضو فيها'}
          </p>
        </div>
        {canCreateAnyDecision && (
          <Button
            icon={<Plus size={16} />}
            onClick={() => {
              setFormError(null)
              setFormOpen(true)
            }}
          >
            قرار جديد
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: 'إجمالي القرارات', value: stats.total, icon: <Gavel size={20} />, tone: 'brand' as const },
          { label: 'بانتظار الاعتماد', value: stats.pending, icon: <Clock3 size={20} />, tone: 'neutral' as const },
          { label: 'قيد التصويت', value: stats.voting, icon: <Vote size={20} />, tone: 'teal' as const },
          { label: 'معتمَدة', value: stats.approved, icon: <CheckCircle2 size={20} />, tone: 'success' as const },
        ].map((stat, i) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: i * 0.05, ease: 'easeOut' }}
          >
            <StatCard label={stat.label} value={stat.value} icon={stat.icon} tone={stat.tone} />
          </motion.div>
        ))}
      </div>

      <SearchInput value={search} onChange={setSearch} placeholder="ابحث باسم القرار..." />

      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Gavel size={26} />}
          title={search ? 'لا توجد نتائج مطابقة' : 'لا توجد قرارات بعد'}
          description={
            search
              ? 'جرّب كلمات بحث مختلفة'
              : canCreateAnyDecision
                ? 'ابدأ بإصدار أول قرار للجنتك'
                : 'تظهر قرارات لجنتك هنا فور إصدارها من رئيس اللجنة'
          }
          action={
            !search &&
            canCreateAnyDecision && (
              <Button size="sm" icon={<Plus size={14} />} onClick={() => setFormOpen(true)}>
                قرار جديد
              </Button>
            )
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((decision, i) => (
            <motion.div
              key={decision.decision_id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: Math.min(i * 0.03, 0.3) }}
            >
              <Card className={cardToneClass(i)}>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-sm bg-brand-primary/10 text-brand-primary">
                    <Gavel size={18} />
                  </div>
                  <DecisionStatusBadge status={decision.status} />
                </div>
                <h3 className="mt-3 text-sm font-semibold text-text-primary">{decision.title}</h3>
                <p className="mt-1 text-xs text-text-secondary">
                  {decision.classification === 'final' ? 'قرار نهائي' : 'خاضع للتصويت'}
                </p>
                <p className="mt-3 text-xs text-text-secondary">
                  التنفيذ: {formatDate(decision.start_date)} — {formatDate(decision.end_date)}
                </p>
                <p className="mt-1.5 text-xs text-text-secondary">
                  {decision.assignees.length} منفّذين
                </p>

                <div className="mt-3 flex items-center gap-1 border-t border-border-default pt-3">
                  <button
                    onClick={() => navigate(`/decisions/${decision.decision_id}`)}
                    className="flex h-8 w-8 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-brand-primary"
                    aria-label="تفاصيل القرار"
                    title="تفاصيل القرار"
                  >
                    <Eye size={16} />
                  </button>
                  {/*
                    بلاغ خطأ 2026-09-08: زر الحذف كان يعتمد فقط على حالة
                    القرار (pending)، بدون فحص هل المستخدم فعليًا يديره —
                    الباك-إند كان يرفض المحاولة (403) لكن الزر نفسه ما كان
                    يجب أن يظهر أصلًا لغير من يقدر على decisions.delete.
                    chairableCommittees أعلاه تعكس هذا تحديدًا (رئيسة
                    اللجنة، أو من يملك النطاق 'all' نظاميًا).
                  */}
                  {decision.status === 'pending' &&
                    chairableCommittees.some((c) => c.committee_id === decision.committee_id) && (
                      <button
                        onClick={() => {
                          setDeleteError(null)
                          setDeleteTarget(decision)
                        }}
                        className="flex h-8 w-8 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-danger-bg hover:text-danger"
                        aria-label="حذف القرار"
                        title="حذف القرار"
                      >
                        <Trash2 size={16} />
                      </button>
                    )}
                </div>
              </Card>
            </motion.div>
          ))}
        </div>
      )}

      <DecisionFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        committees={chairableCommittees}
        onSubmit={handleCreate}
        loading={createMutation.isPending || openVotingMutation.isPending}
        serverError={formError}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDeleteConfirm}
        title="حذف القرار"
        description={`سيتم حذف قرار "${deleteTarget?.title}" نهائيًا. هل أنتِ متأكدة؟`}
        confirmLabel="حذف"
        loading={deleteMutation.isPending}
        errorMessage={deleteError}
      />
    </div>
  )
}
