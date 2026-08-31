import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { CalendarClock, CalendarDays, Plus, Users2, Video } from 'lucide-react'
import { useCommittees } from '@/hooks/useCommittees'
import { useCreateMeeting, useMeetings } from '@/hooks/useMeetings'
import { useAuthStore } from '@/store/authStore'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { SearchInput } from '@/components/ui/SearchInput'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { CardSkeleton } from '@/components/ui/Skeleton'
import { StatCard } from '@/components/ui/StatCard'
import { MeetingStatusBadge } from '@/components/ui/StatusBadge'
import { useToast } from '@/components/ui/Toast'
import { MeetingFormModal, type MeetingFormSubmitValues } from './MeetingFormModal'
import { cardToneClass, extractErrorMessage, formatDateTime } from '@/lib/utils'

/**
 * قائمة الاجتماعات — بدون Teams/AI (Phase 1 من وحدة "إدارة الاجتماعات").
 *
 * ملاحظة تصميم مهمة (لماذا لا يوجد requiredPermission على هذه الصفحة/المسار
 * في Sidebar.tsx وApp.tsx): "رئيس اللجنة" و"عضو اللجنة" ليسا دورين بجدول
 * roles (راجعي 0013_committee_chair.sql بالباك-إند)، فلا صلاحية meetings.*
 * تُمنح لهما عبر الكتالوج إطلاقًا — فقط ادمن (قراءة فقط لاجتماعات لجان
 * إدارته) وسوبر أدمن يملكانها فعليًا. تفويض الوصول الفعلي هيكلي بالكامل
 * (meeting_service.py بالباك-إند)، فحجب هذه الصفحة خلف صلاحية عامة كما هو
 * متّبع بصفحات أخرى (اللجان المعتمدة مثلًا) كان سيمنع أي رئيس/عضو لجنة لا
 * يحمل دور ادمن من الوصول لاجتماعاته الخاصة تمامًا.
 */
export function MeetingsPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { data: meetings, isLoading, isError, refetch } = useMeetings()
  const { data: committees } = useCommittees()
  const createMutation = useCreateMeeting()
  const { showToast } = useToast()

  const [search, setSearch] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  /**
   * اللجان التي يقدر المستخدم الحالي ينشئ لها اجتماعًا — رئيسها فقط
   * (نفس القيد الهيكلي المفروض بالباك-إند: meeting_service._authorize_manage).
   * سوبر أدمن يملك meetings.schedule بالكتالوج فعليًا (منح شامل تلقائي)،
   * فيُتاح له إنشاء اجتماع لأي لجنة، حتى لو لم يكن رئيسها.
   */
  const chairableCommittees = useMemo(() => {
    if (!committees || !user) return []
    if (user.role?.is_super_admin) return committees
    return committees.filter((c) => c.chair_user_id === user.user_id)
  }, [committees, user])

  const canCreateAnyMeeting = chairableCommittees.length > 0

  const filtered = useMemo(() => {
    if (!meetings) return []
    const q = search.trim().toLowerCase()
    if (!q) return meetings
    return meetings.filter(
      (m) => m.title.toLowerCase().includes(q) || m.description?.toLowerCase().includes(q),
    )
  }, [meetings, search])

  const stats = useMemo(() => {
    const all = meetings ?? []
    return {
      total: all.length,
      upcoming: all.filter((m) => m.status === 'upcoming').length,
      ongoing: all.filter((m) => m.status === 'ongoing').length,
    }
  }, [meetings])

  function handleCreate(values: MeetingFormSubmitValues) {
    setFormError(null)
    createMutation.mutate(values, {
      onSuccess: (created) => {
        setFormOpen(false)
        showToast('تم إنشاء الاجتماع بنجاح', 'success')
        navigate(`/meetings/${created.meeting_id}`)
      },
      onError: (err) => setFormError(extractErrorMessage(err)),
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-xl font-bold text-text-primary">الاجتماعات</h1>
          <p className="mt-1 text-sm text-text-muted">
            {canCreateAnyMeeting
              ? 'إنشاء ومتابعة اجتماعات اللجان التي ترأسها'
              : 'متابعة الاجتماعات التي أنت مشارك أو عضو فيها'}
          </p>
        </div>
        {canCreateAnyMeeting && (
          <Button
            icon={<Plus size={16} />}
            onClick={() => {
              setFormError(null)
              setFormOpen(true)
            }}
          >
            اجتماع جديد
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[
          { label: 'إجمالي الاجتماعات', value: stats.total, icon: <Users2 size={20} />, tone: 'brand' as const },
          { label: 'قادمة', value: stats.upcoming, icon: <CalendarClock size={20} />, tone: 'teal' as const },
          { label: 'جارية الآن', value: stats.ongoing, icon: <Video size={20} />, tone: 'success' as const },
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

      <SearchInput value={search} onChange={setSearch} placeholder="ابحث بعنوان الاجتماع أو وصفه..." />

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
          icon={<CalendarDays size={26} />}
          title={search ? 'لا توجد نتائج مطابقة' : 'لا توجد اجتماعات بعد'}
          description={
            search
              ? 'جرّب كلمات بحث مختلفة'
              : canCreateAnyMeeting
                ? 'ابدأ بإنشاء أول اجتماع للجنتك'
                : 'تظهر اجتماعاتك هنا فور إنشائها من رئيس اللجنة'
          }
          action={
            !search &&
            canCreateAnyMeeting && (
              <Button size="sm" icon={<Plus size={14} />} onClick={() => setFormOpen(true)}>
                اجتماع جديد
              </Button>
            )
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((meeting, i) => (
            <motion.div
              key={meeting.meeting_id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: Math.min(i * 0.03, 0.3) }}
            >
              <Card
                interactive
                onClick={() => navigate(`/meetings/${meeting.meeting_id}`)}
                className={cardToneClass(i)}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-sm bg-brand-primary/10 text-brand-primary">
                    <CalendarDays size={18} />
                  </div>
                  <MeetingStatusBadge status={meeting.status} />
                </div>
                <h3 className="mt-3 text-sm font-semibold text-text-primary">{meeting.title}</h3>
                {meeting.description && (
                  <p className="mt-1 line-clamp-2 text-sm text-text-muted">{meeting.description}</p>
                )}
                <p className="mt-3 flex items-center gap-1.5 text-xs text-text-secondary">
                  <CalendarClock size={12} />
                  {formatDateTime(meeting.scheduled_at)}
                </p>
                <p className="mt-1.5 flex items-center gap-1.5 text-xs text-text-secondary">
                  <Users2 size={12} />
                  {meeting.participants.length} مشاركين
                </p>
              </Card>
            </motion.div>
          ))}
        </div>
      )}

      <MeetingFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        committees={chairableCommittees}
        onSubmit={handleCreate}
        loading={createMutation.isPending}
        serverError={formError}
      />
    </div>
  )
}
