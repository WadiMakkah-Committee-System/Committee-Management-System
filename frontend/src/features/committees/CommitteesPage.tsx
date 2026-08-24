import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { CalendarDays, CheckCircle2, Users2 } from 'lucide-react'
import { useCommittees } from '@/hooks/useCommittees'
import { Card } from '@/components/ui/Card'
import { SearchInput } from '@/components/ui/SearchInput'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { CardSkeleton } from '@/components/ui/Skeleton'
import { StatCard } from '@/components/ui/StatCard'
import { cardToneClass, cn, formatDate } from '@/lib/utils'

/**
 * قائمة اللجان المعتمدة رسميًا — Phase 5 (حسب ترقيم Lama)، عرض فقط
 * (Read-only). لا زر إنشاء هنا: اللجنة تُنشأ تلقائيًا فقط عند اعتماد
 * طلب تشكيل لجنة (Phase 4)، وليس مباشرة من هذه الصفحة. لا إضافة/حذف
 * أعضاء ولا تعديل بيانات — قرار موثّق من Lama (راجعي project_memory:
 * phase2-committee-formation-requests.md).
 */
export function CommitteesPage() {
  const navigate = useNavigate()
  const { data: committees, isLoading, isError, refetch } = useCommittees()

  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    if (!committees) return []
    const q = search.trim().toLowerCase()
    if (!q) return committees
    return committees.filter(
      (c) => c.name.toLowerCase().includes(q) || c.statement?.toLowerCase().includes(q),
    )
  }, [committees, search])

  const totalMembers = useMemo(
    () => (committees ?? []).reduce((sum, c) => sum + c.members.length, 0),
    [committees],
  )

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-bold text-text-primary">اللجان المعتمدة</h1>
        <p className="mt-1 text-sm text-text-muted">اللجان التي تشكّلت رسميًا بعد اعتماد طلبات تشكيلها</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {[
          { label: 'عدد اللجان', value: committees?.length ?? 0, icon: <CheckCircle2 size={20} />, tone: 'success' as const },
          { label: 'إجمالي الأعضاء', value: totalMembers, icon: <Users2 size={20} />, tone: 'brand' as const },
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

      <SearchInput value={search} onChange={setSearch} placeholder="ابحث باسم اللجنة أو بيانها..." />

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
          icon={<Users2 size={26} />}
          title={search ? 'لا توجد نتائج مطابقة' : 'لا توجد لجان معتمدة بعد'}
          description={
            search
              ? 'جرّب كلمات بحث مختلفة'
              : 'تظهر اللجنة هنا تلقائيًا فور اعتماد طلب تشكيلها من الرئيس التنفيذي'
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((committee, i) => (
            <motion.div
              key={committee.committee_id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: Math.min(i * 0.03, 0.3) }}
            >
              <Card
                onClick={() => navigate(`/committees/approved/${committee.committee_id}`)}
                className={cn(
                  'flex h-full cursor-pointer flex-col gap-3 transition-shadow hover:shadow-md',
                  cardToneClass(i),
                )}
              >
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-sm bg-success-bg text-success">
                  <CheckCircle2 size={18} />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-text-primary">{committee.name}</h3>
                  <p className="mt-1 line-clamp-2 text-sm text-text-muted">
                    {committee.statement || 'لا يوجد بيان'}
                  </p>
                </div>
                <p className="flex items-center gap-1.5 text-xs text-text-secondary">
                  <CalendarDays size={12} />
                  {formatDate(committee.start_date)} — {formatDate(committee.end_date)}
                </p>
                <p className="flex items-center gap-1.5 text-xs text-text-secondary">
                  <Users2 size={12} />
                  {committee.members.length} أعضاء
                </p>
              </Card>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  )
}
