import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Building2, CalendarDays, CheckCircle2, Users2 } from 'lucide-react'
import { useCommittees, useDepartmentMembersElsewhere } from '@/hooks/useCommittees'
import { useAuthStore } from '@/store/authStore'
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

  // موظفو إدارتي بلجان أخرى — مراجعة لاما 2026-08-30 (الجولة الثالثة):
  // سطح خفيف منفصل عن القائمة الرئيسية، يظهر فقط لمستخدم له إدارة فعلية.
  const currentUser = useAuthStore((s) => s.user)
  const showElsewhereSection =
    !!currentUser?.dep_id && !!currentUser?.permissions.includes('committees.view')
  const [elsewhereSearch, setElsewhereSearch] = useState('')
  const {
    data: elsewhereMembers,
    isLoading: elsewhereLoading,
    isError: elsewhereError,
    refetch: refetchElsewhere,
  } = useDepartmentMembersElsewhere(elsewhereSearch, showElsewhereSection)

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
                interactive
                onClick={() => navigate(`/committees/approved/${committee.committee_id}`)}
                className={cn('flex h-full flex-col gap-3', cardToneClass(i))}
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

      {showElsewhereSection && (
        <div className="flex flex-col gap-3 rounded-sm border border-border-default bg-bg-surface p-4">
          <div className="flex items-center gap-2">
            <Building2 size={16} className="text-text-muted" />
            <h2 className="text-sm font-semibold text-text-primary">موظفو إدارتي بلجان أخرى</h2>
          </div>
          <p className="text-xs text-text-muted">
            موظفون من إدارتك أعضاء بلجان تتبع إدارات أخرى — معلومة تعريفية فقط (الموظف/اللجنة/الإدارة)، بدون تفاصيل اللجنة الكاملة
          </p>
          <SearchInput
            value={elsewhereSearch}
            onChange={setElsewhereSearch}
            placeholder="ابحث باسم الموظف أو اللجنة أو الإدارة..."
          />
          {elsewhereLoading ? (
            <CardSkeleton />
          ) : elsewhereError ? (
            <ErrorState onRetry={() => refetchElsewhere()} />
          ) : (elsewhereMembers?.length ?? 0) === 0 ? (
            <p className="py-4 text-center text-sm text-text-muted">
              {elsewhereSearch ? 'لا توجد نتائج مطابقة' : 'لا يوجد موظفون من إدارتك بلجان أخرى حاليًا'}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-right text-sm">
                <thead>
                  <tr className="border-b border-border-default text-xs text-text-muted">
                    <th className="px-3 py-2 font-medium">الموظف</th>
                    <th className="px-3 py-2 font-medium">اللجنة</th>
                    <th className="px-3 py-2 font-medium">الإدارة التابعة لها</th>
                  </tr>
                </thead>
                <tbody>
                  {elsewhereMembers?.map((row) => (
                    <tr
                      key={`${row.committee_id}-${row.member.user_id}`}
                      className="border-b border-border-default last:border-0"
                    >
                      <td className="px-3 py-2 text-text-primary">
                        {row.member.first_name} {row.member.middle_name} {row.member.last_name}
                      </td>
                      <td className="px-3 py-2 text-text-secondary">{row.committee_name}</td>
                      <td className="px-3 py-2 text-text-secondary">{row.department_name ?? 'غير محدد'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
