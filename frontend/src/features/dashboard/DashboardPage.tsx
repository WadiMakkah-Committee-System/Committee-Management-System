import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  CalendarClock,
  CheckSquare,
  ClipboardList,
  FileText,
  Gavel,
  Users2,
  Vote,
} from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { useDashboardSummary } from '@/hooks/useDashboard'
import { getGreeting, formatTodayLabel } from '@/lib/dashboardGreeting'
import { Card } from '@/components/ui/Card'
import { StatCard } from '@/components/ui/StatCard'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/ui/ErrorState'
import { EmptyState } from '@/components/ui/EmptyState'
import { MeetingStatusBadge } from '@/components/ui/StatusBadge'
import { formatDate, formatDateTime } from '@/lib/utils'
import type {
  DashboardDecisionItem,
  DashboardMeetingItem,
  DashboardSummary,
  DashboardTaskItem,
} from '@/types'

/**
 * لوحة التحكم — أول صفحة يشوفها أي مستخدم بعد تسجيل الدخول (App.tsx
 * يوجّه "/" إليها الآن، يطابق SRS حرفيًا: "توجيه المستخدم بعد تسجيل
 * الدخول إلى لوحة التحكم المناسبة لدوره وصلاحياته"). كل قسم هنا مجرّد
 * انعكاس لما تُرجعه كل وحدة أصلية فعليًا لهذا المستخدم تحديدًا (راجعي
 * رأس app/services/dashboard_service.py بالباك-إند) — لا صلاحية إضافية
 * تُفحص هنا، ولا بيانات تُخترَع أو تُقدَّر بالفرونت.
 *
 * "التقارير" (حالة استخدام رابعة بالـSRS) مؤجَّلة عمدًا لمرحلة منفصلة —
 * قرار صريح من صاحبة المشروع 2026-09-08.
 *
 * التصميم: هوية وادي مكة متعدّدة الألوان (Primary/Teal/Orange/Purple)
 * على بطاقات إحصاء مُلوَّنة الخلفية (tintCard، نفس نمط لاما بصفحة
 * الاجتماعات 2026-09-05)، مع شكلين عضويين (Blob) زخرفيين خافتين خلف
 * التحية فقط — لمسة واحدة جريئة، بلا تكرارها بكل قسم. كل قسم نشاط
 * (اجتماعات/قرارات/مهام) يحمل نفس لون بطاقته الإحصائية بخط جانبي رفيع،
 * لخلق تتبّع بصري بين العدّاد وتفاصيله دون الحاجة لتسمية إضافية.
 */
export function DashboardPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { data, isLoading, isError, refetch } = useDashboardSummary()

  const firstName = user?.first_name ?? ''

  return (
    <div className="flex flex-col gap-6">
      <HeroGreeting firstName={firstName} />

      {isLoading ? (
        <DashboardSkeleton />
      ) : isError || !data ? (
        <ErrorState onRetry={() => refetch()} />
      ) : (
        <DashboardContent data={data} onNavigate={navigate} />
      )}
    </div>
  )
}

function HeroGreeting({ firstName }: { firstName: string }) {
  return (
    <div className="relative overflow-hidden rounded-md border border-border-default bg-bg-surface px-6 py-8 sm:px-8">
      {/* شكلان عضويان زخرفيان خافتان — اللمسة الجريئة الوحيدة بالصفحة، لا تتكرر بأي قسم آخر. */}
      <svg
        aria-hidden
        className="pointer-events-none absolute -left-16 -top-20 h-64 w-64 text-brand-primary/[0.07]"
        viewBox="0 0 200 200"
      >
        <path
          fill="currentColor"
          d="M45.3,-58.5C58.2,-49.6,67.4,-34.5,71.6,-17.9C75.8,-1.3,75,17.8,66.6,32.6C58.2,47.4,42.2,57.9,25.1,64.5C8,71,-10.2,73.6,-26.8,68.7C-43.4,63.8,-58.3,51.4,-66.8,35.5C-75.2,19.6,-77.1,0.2,-72.4,-16.9C-67.7,-34,-56.4,-48.8,-42.1,-57.6C-27.8,-66.4,-13.9,-69.2,1.6,-71.5C17.1,-73.9,34.3,-67.4,45.3,-58.5Z"
          transform="translate(100 100)"
        />
      </svg>
      <svg
        aria-hidden
        className="pointer-events-none absolute -bottom-24 -right-10 h-72 w-72 text-brand-teal/[0.06]"
        viewBox="0 0 200 200"
      >
        <path
          fill="currentColor"
          d="M39.6,-51.2C52.5,-42.6,64.7,-31.4,69.8,-17.1C74.9,-2.8,72.9,14.6,64.9,28.6C56.9,42.6,42.9,53.2,27.4,60.1C11.9,67,-5.1,70.2,-21.1,66.5C-37.1,62.8,-52.1,52.2,-61.4,37.9C-70.7,23.6,-74.3,5.6,-70.6,-10.5C-66.9,-26.6,-55.9,-40.8,-42.5,-49.5C-29.1,-58.2,-14.6,-61.4,-0.1,-61.3C14.4,-61.1,26.7,-59.8,39.6,-51.2Z"
          transform="translate(100 100)"
        />
      </svg>

      <div className="relative flex flex-col gap-1">
        <p className="text-sm font-medium text-text-muted">{formatTodayLabel()}</p>
        <h1 className="text-2xl font-bold text-text-primary sm:text-3xl">
          {getGreeting()}
          {firstName ? `، ${firstName}` : ''}
        </h1>
        <p className="mt-1 text-sm text-text-secondary">هذا ملخص ما يخصّك اليوم عبر النظام.</p>
      </div>
    </div>
  )
}

function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-[88px]" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Skeleton className="h-72 lg:col-span-1" />
        <Skeleton className="h-72 lg:col-span-2" />
      </div>
    </div>
  )
}

function DashboardContent({
  data,
  onNavigate,
}: {
  data: DashboardSummary
  onNavigate: (path: string) => void
}) {
  const stats = [
    {
      key: 'committees',
      label: 'لجاني المصرح بها',
      value: data.committees_count,
      icon: <Users2 size={20} />,
      tone: 'brand' as const,
      path: '/committees/approved',
    },
    {
      key: 'meetings',
      label: 'اجتماعات قادمة',
      value: data.upcoming_meetings_count,
      icon: <CalendarClock size={20} />,
      tone: 'teal' as const,
      path: '/meetings',
    },
    {
      key: 'decisions',
      label: 'بانتظار تصويتي',
      value: data.pending_votes_count,
      icon: <Vote size={20} />,
      tone: 'orange' as const,
      path: '/decisions',
    },
    {
      key: 'tasks',
      label: 'مهامي المفتوحة',
      value: data.open_tasks_count,
      icon: <CheckSquare size={20} />,
      tone: 'purple' as const,
      path: '/tasks',
    },
    {
      key: 'documents',
      label: 'وثائق متاحة',
      value: data.documents_count,
      icon: <FileText size={20} />,
      tone: 'success' as const,
      path: '/documents',
    },
  ]

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {stats.map((stat, i) => (
          <motion.div
            key={stat.key}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: i * 0.05, ease: 'easeOut' }}
          >
            <button onClick={() => onNavigate(stat.path)} className="block w-full text-right">
              <StatCard label={stat.label} value={stat.value} icon={stat.icon} tone={stat.tone} tintCard />
            </button>
          </motion.div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <CommitteesWidget data={data} onNavigate={onNavigate} />

        <div className="flex flex-col gap-4 lg:col-span-2">
          <MeetingsWidget items={data.upcoming_meetings_preview} onNavigate={onNavigate} />
          <DecisionsWidget items={data.pending_votes_preview} onNavigate={onNavigate} />
          <TasksWidget items={data.open_tasks_preview} onNavigate={onNavigate} />
        </div>
      </div>
    </div>
  )
}

function WidgetShell({
  title,
  icon,
  toneClass,
  count,
  emptyIcon,
  emptyTitle,
  emptyDescription,
  children,
  hasItems,
}: {
  title: string
  icon: ReactNode
  toneClass: string
  count: number
  emptyIcon: ReactNode
  emptyTitle: string
  emptyDescription: string
  children: ReactNode
  hasItems: boolean
}) {
  return (
    <Card className="p-0">
      <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
          <span className={toneClass}>{icon}</span>
          {title}
        </h2>
        {count > 0 && <span className="text-xs text-text-muted">{count}</span>}
      </div>
      {hasItems ? (
        <ul>{children}</ul>
      ) : (
        <div className="px-4 py-6">
          <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />
        </div>
      )}
    </Card>
  )
}

function CommitteesWidget({
  data,
  onNavigate,
}: {
  data: DashboardSummary
  onNavigate: (path: string) => void
}) {
  return (
    <WidgetShell
      title="لجاني المصرح بها"
      icon={<Users2 size={15} />}
      toneClass="text-brand-primary"
      count={data.committees_count}
      hasItems={data.committees_preview.length > 0}
      emptyIcon={<Users2 size={22} />}
      emptyTitle="لا توجد لجان بعد"
      emptyDescription="اللجان التي أنت رئيسها أو عضو فيها تظهر هنا."
    >
      {data.committees_preview.map((c, i) => (
        <motion.li
          key={c.committee_id}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.15, delay: Math.min(i * 0.03, 0.3) }}
        >
          <button
            onClick={() => onNavigate(`/committees/approved/${c.committee_id}`)}
            className="flex w-full items-center gap-2.5 border-r-2 border-brand-primary/40 border-b border-b-border-default px-4 py-3 text-right text-sm text-text-primary transition-colors last:border-b-0 hover:bg-bg-elevated"
          >
            {c.name}
          </button>
        </motion.li>
      ))}
    </WidgetShell>
  )
}

function MeetingsWidget({
  items,
  onNavigate,
}: {
  items: DashboardMeetingItem[]
  onNavigate: (path: string) => void
}) {
  return (
    <WidgetShell
      title="اجتماعات قادمة"
      icon={<CalendarClock size={15} />}
      toneClass="text-brand-teal"
      count={items.length}
      hasItems={items.length > 0}
      emptyIcon={<CalendarClock size={22} />}
      emptyTitle="لا توجد اجتماعات قادمة"
      emptyDescription="اجتماعات لجانك القادمة ستظهر هنا."
    >
      {items.map((m, i) => (
        <motion.li
          key={m.meeting_id}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.15, delay: Math.min(i * 0.03, 0.3) }}
        >
          <button
            onClick={() => onNavigate(`/meetings/${m.meeting_id}`)}
            className="flex w-full items-center justify-between gap-3 border-r-2 border-brand-teal/40 border-b border-b-border-default px-4 py-3 text-right text-sm transition-colors last:border-b-0 hover:bg-bg-elevated"
          >
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium text-text-primary">{m.title}</span>
              <span className="mt-0.5 block text-xs text-text-muted">{m.committee_name}</span>
            </span>
            <span className="flex shrink-0 flex-col items-end gap-1">
              <span className="text-xs text-text-secondary">{formatDateTime(m.scheduled_at)}</span>
              <MeetingStatusBadge status="upcoming" />
            </span>
          </button>
        </motion.li>
      ))}
    </WidgetShell>
  )
}

function DecisionsWidget({
  items,
  onNavigate,
}: {
  items: DashboardDecisionItem[]
  onNavigate: (path: string) => void
}) {
  return (
    <WidgetShell
      title="قرارات بانتظار تصويتي"
      icon={<Vote size={15} />}
      toneClass="text-brand-orange"
      count={items.length}
      hasItems={items.length > 0}
      emptyIcon={<Gavel size={22} />}
      emptyTitle="لا توجد قرارات بانتظارك"
      emptyDescription="قرارات لجانك المطروحة للتصويت ولم تصوّتي عليها بعد تظهر هنا."
    >
      {items.map((d, i) => (
        <motion.li
          key={d.decision_id}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.15, delay: Math.min(i * 0.03, 0.3) }}
        >
          <button
            onClick={() => onNavigate(`/decisions/${d.decision_id}`)}
            className="flex w-full items-center justify-between gap-3 border-r-2 border-brand-orange/40 border-b border-b-border-default px-4 py-3 text-right text-sm transition-colors last:border-b-0 hover:bg-bg-elevated"
          >
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium text-text-primary">{d.title}</span>
              <span className="mt-0.5 block text-xs text-text-muted">{d.committee_name}</span>
            </span>
            {d.voting_deadline && (
              <span className="shrink-0 text-xs text-text-secondary">
                ينتهي {formatDateTime(d.voting_deadline)}
              </span>
            )}
          </button>
        </motion.li>
      ))}
    </WidgetShell>
  )
}

function TasksWidget({
  items,
  onNavigate,
}: {
  items: DashboardTaskItem[]
  onNavigate: (path: string) => void
}) {
  return (
    <WidgetShell
      title="مهامي المفتوحة"
      icon={<CheckSquare size={15} />}
      toneClass="text-brand-purple"
      count={items.length}
      hasItems={items.length > 0}
      emptyIcon={<ClipboardList size={22} />}
      emptyTitle="لا توجد مهام مفتوحة"
      emptyDescription="المهام المسندة لك وغير المكتملة تظهر هنا."
    >
      {items.map((t, i) => (
        <motion.li
          key={t.task_id}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.15, delay: Math.min(i * 0.03, 0.3) }}
        >
          <button
            onClick={() => onNavigate(`/tasks/${t.task_id}`)}
            className="flex w-full items-center justify-between gap-3 border-r-2 border-brand-purple/40 border-b border-b-border-default px-4 py-3 text-right text-sm transition-colors last:border-b-0 hover:bg-bg-elevated"
          >
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium text-text-primary">{t.title}</span>
              <span className="mt-0.5 block text-xs text-text-muted">{t.committee_name}</span>
            </span>
            <span className="shrink-0 text-xs text-text-secondary">
              يستحق {formatDate(t.end_date)}
            </span>
          </button>
        </motion.li>
      ))}
    </WidgetShell>
  )
}
