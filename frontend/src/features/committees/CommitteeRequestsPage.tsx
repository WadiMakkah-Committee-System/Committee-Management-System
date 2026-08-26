import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { CheckCircle2, ChevronLeft, Clock3, FileEdit, Plus, Users2 } from 'lucide-react'
import {
  useCreateCommitteeRequest,
  useCommitteeRequests,
  useSubmitCommitteeRequest,
} from '@/hooks/useCommitteeRequests'
import { useAuthStore } from '@/store/authStore'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { SearchInput } from '@/components/ui/SearchInput'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { TableSkeleton } from '@/components/ui/Skeleton'
import { StatCard } from '@/components/ui/StatCard'
import { CommitteeRequestStatusBadge } from '@/components/ui/StatusBadge'
import { useToast } from '@/components/ui/Toast'
import { CommitteeRequestFormModal, type CommitteeRequestFormSubmitValues } from './CommitteeRequestFormModal'
import { extractErrorMessage, formatDate } from '@/lib/utils'

export function CommitteeRequestsPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { data: requests, isLoading, isError, refetch } = useCommitteeRequests()
  const createMutation = useCreateCommitteeRequest()
  const submitMutation = useSubmitCommitteeRequest()
  const { showToast } = useToast()

  const [search, setSearch] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)

  const canCreate =
    !!user?.role.is_super_admin || !!user?.permissions.includes('committees.request.create')

  const filtered = useMemo(() => {
    if (!requests) return []
    const q = search.trim().toLowerCase()
    if (!q) return requests
    return requests.filter(
      (r) =>
        r.committee_name.toLowerCase().includes(q) ||
        `${r.requester.first_name} ${r.requester.last_name}`.toLowerCase().includes(q),
    )
  }, [requests, search])

  const stats = useMemo(() => {
    const all = requests ?? []
    return {
      total: all.length,
      draftOrReturned: all.filter((r) => r.status === 'draft' || r.status === 'returned').length,
      inProgress: all.filter((r) => r.status === 'submitted' || r.status === 'under_review' || r.status === 'pending_approval').length,
      approved: all.filter((r) => r.status === 'approved').length,
    }
  }, [requests])

  function handleCreate(values: CommitteeRequestFormSubmitValues) {
    setFormError(null)
    createMutation.mutate(values, {
      onSuccess: (created) => {
        setFormOpen(false)
        showToast('تم حفظ طلب تشكيل اللجنة كمسودة', 'success')
        navigate(`/committees/requests/${created.request_id}`)
      },
      onError: (err) => setFormError(extractErrorMessage(err)),
    })
  }

  /**
   * الهدف: إنشاء طلب تشكيل اللجنة وإرساله مباشرة بضغطة واحدة ("حفظ وإرسال")
   * بدل تركه كمسودة، دون الحاجة لفتح تفاصيل الطلب بعد إنشائه ثم الضغط على
   * زر الإرسال المنفصل هناك.
   *
   * التأثيرات الجانبية: تنشئ الطلب (createMutation) ثم ترسله فورًا
   * (submitMutation) — عمليتان متتاليتان عبر mutateAsync؛ عند فشل أي
   * منهما تُعرض رسالة الخطأ بالنموذج ويبقى مفتوحًا.
   */
  async function handleCreateAndSend(values: CommitteeRequestFormSubmitValues) {
    setFormError(null)
    setSending(true)
    try {
      const created = await createMutation.mutateAsync(values)
      await submitMutation.mutateAsync(created.request_id)
      setFormOpen(false)
      showToast('تم حفظ طلب تشكيل اللجنة وإرساله بنجاح', 'success')
      navigate(`/committees/requests/${created.request_id}`)
    } catch (err) {
      setFormError(extractErrorMessage(err))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-xl font-bold text-text-primary">طلبات تشكيل اللجان</h1>
          <p className="mt-1 text-sm text-text-muted">
            {canCreate ? 'إنشاء ومتابعة طلبات تشكيل اللجان الخاصة بك' : 'متابعة طلبات تشكيل اللجان المُرسَلة'}
          </p>
        </div>
        {canCreate && (
          <Button
            icon={<Plus size={16} />}
            onClick={() => {
              setFormError(null)
              setFormOpen(true)
            }}
          >
            طلب تشكيل لجنة جديد
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: 'إجمالي الطلبات', value: stats.total, icon: <Users2 size={20} />, tone: 'brand' as const },
          { label: 'مسودات ومُعادة للتعديل', value: stats.draftOrReturned, icon: <FileEdit size={20} />, tone: 'orange' as const },
          { label: 'قيد الإجراء', value: stats.inProgress, icon: <Clock3 size={20} />, tone: 'purple' as const },
          { label: 'معتمدة', value: stats.approved, icon: <CheckCircle2 size={20} />, tone: 'success' as const },
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

      <SearchInput value={search} onChange={setSearch} placeholder="ابحث باسم اللجنة أو مقدّم الطلب..." />

      {isLoading ? (
        <Card className="p-0">
          <TableSkeleton />
        </Card>
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Users2 size={26} />}
          title={search ? 'لا توجد نتائج مطابقة' : 'لا توجد طلبات تشكيل لجان بعد'}
          description={
            search ? 'جرّب كلمات بحث مختلفة' : canCreate ? 'ابدأ بإنشاء أول طلب تشكيل لجنة' : undefined
          }
          action={
            !search &&
            canCreate && (
              <Button size="sm" icon={<Plus size={14} />} onClick={() => setFormOpen(true)}>
                طلب تشكيل لجنة جديد
              </Button>
            )
          }
        />
      ) : (
        <>
          {/* سطح المكتب / التابلت: جدول */}
          <Card className="hidden p-0 sm:block">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-right text-sm">
                <thead>
                  <tr className="border-b border-border-default bg-table-header">
                    <th className="px-4 py-3 font-semibold text-text-secondary">اسم اللجنة</th>
                    <th className="px-4 py-3 font-semibold text-text-secondary">مقدّم الطلب</th>
                    <th className="px-4 py-3 font-semibold text-text-secondary">عدد الأعضاء المقترحين</th>
                    <th className="px-4 py-3 font-semibold text-text-secondary">الحالة</th>
                    <th className="px-4 py-3 font-semibold text-text-secondary">تاريخ الإنشاء</th>
                    <th className="w-10 px-2 py-3" aria-hidden="true" />
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((req, i) => (
                    <motion.tr
                      key={req.request_id}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ duration: 0.15, delay: Math.min(i * 0.02, 0.2) }}
                      onClick={() => navigate(`/committees/requests/${req.request_id}`)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          navigate(`/committees/requests/${req.request_id}`)
                        }
                      }}
                      className="group cursor-pointer border-b border-border-default transition-colors last:border-0 hover:bg-table-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-accent"
                    >
                      <td className="px-4 py-3 font-medium text-text-primary">{req.committee_name}</td>
                      <td className="px-4 py-3 text-text-secondary">
                        {req.requester.first_name} {req.requester.last_name}
                      </td>
                      <td className="px-4 py-3 text-text-secondary">{req.proposed_members.length}</td>
                      <td className="px-4 py-3">
                        <CommitteeRequestStatusBadge status={req.status} />
                      </td>
                      <td className="px-4 py-3 text-text-muted">{formatDate(req.created_at)}</td>
                      <td className="px-2 py-3 text-text-muted opacity-0 transition-opacity group-hover:opacity-100">
                        <ChevronLeft size={16} />
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* الجوال: بطاقات بدل جدول أفقي التمرير */}
          <div className="flex flex-col gap-3 sm:hidden">
            {filtered.map((req, i) => (
              <motion.div
                key={req.request_id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2, delay: Math.min(i * 0.03, 0.3) }}
              >
                <Card
                  interactive
                  onClick={() => navigate(`/committees/requests/${req.request_id}`)}
                  className="flex flex-col gap-2.5 active:scale-[0.99]"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-semibold text-text-primary">{req.committee_name}</p>
                    <CommitteeRequestStatusBadge status={req.status} />
                  </div>
                  <div className="flex items-center justify-between text-xs text-text-muted">
                    <span>
                      {req.requester.first_name} {req.requester.last_name}
                    </span>
                    <span>{req.proposed_members.length} أعضاء</span>
                  </div>
                  <div className="flex items-center justify-between border-t border-border-default pt-2 text-xs text-text-muted">
                    <span>{formatDate(req.created_at)}</span>
                    <ChevronLeft size={14} />
                  </div>
                </Card>
              </motion.div>
            ))}
          </div>
        </>
      )}

      <CommitteeRequestFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSubmit={handleCreate}
        onSubmitAndSend={canCreate ? handleCreateAndSend : undefined}
        loading={createMutation.isPending && !sending}
        sendLoading={sending}
        serverError={formError}
      />
    </div>
  )
}
