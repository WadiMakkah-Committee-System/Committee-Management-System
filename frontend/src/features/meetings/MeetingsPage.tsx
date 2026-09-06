import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  CalendarClock,
  CalendarDays,
  CalendarRange,
  Info,
  LayoutList,
  ListChecks,
  MapPin,
  Paperclip,
  Plus,
  Trash2,
  Users2,
  Video,
} from 'lucide-react'
import { useCommittees } from '@/hooks/useCommittees'
import {
  useCreateMeeting,
  useDeleteMeeting,
  useMeetings,
  useUploadMeetingAttachment,
} from '@/hooks/useMeetings'
import { useAuthStore } from '@/store/authStore'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { SearchInput } from '@/components/ui/SearchInput'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { CardSkeleton } from '@/components/ui/Skeleton'
import { StatCard } from '@/components/ui/StatCard'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { MeetingStatusBadge } from '@/components/ui/StatusBadge'
import { useToast } from '@/components/ui/Toast'
import { MeetingFormModal, type MeetingFormSubmitValues } from './MeetingFormModal'
import { MeetingCalendarView } from './MeetingCalendarView'
import { cardToneClass, cn, dayGroupKey, extractErrorMessage, formatDayHeading, formatTime, iconToneClass } from '@/lib/utils'
import type { Meeting } from '@/types'

/**
 * قائمة الاجتماعات — إعادة تصميم شاملة 2026-09-05 (طلب لاما 14 بندًا) فوق
 * الأساس القائم من مرحلة 2026-09-01 (بدون Teams/AI — Phase 1).
 *
 * التعديلات بهذه المرحلة (تفصيل كامل بالتعليقات أسفل كل قسم):
 *   1) عرضان قابلان للتبديل: زمني/جدول (Timeline — الافتراضي) وتقويم
 *      (Calendar، عبر MeetingCalendarView.tsx الجديد — react-big-calendar).
 *   2) شرائح فلترة (Filter Chips) بحالة الاجتماع مع عدّاد حي لكل حالة —
 *      "منتهية" لا "مسجَّلة" (recorded محجوزة لمرحلة قادمة، لا يوجد أي
 *      اجتماع بهذه الحالة فعليًا الآن — راجعي meeting_service.py).
 *   3) العرض الزمني الآن قائمة مُجمَّعة باليوم بترتيب زمني تصاعدي (خط
 *      رأسي + نقاط) بدل شبكة بطاقات ثابتة الترتيب — نفس بيانات ومنطق
 *      الإجراءات (تفاصيل/أجندة/مرفقات/حذف) بلا أي تغيير بمن يقدر يحذف.
 *
 * ملاحظة تصميم (محدَّثة 2026-09-01 — قرار توحيد سلوك القائمة الجانبية بين
 * "اللجان" و"الاجتماعات"): المسار الآن محجوب فعليًا خلف
 * ProtectedRoute anyPermission={['meetings.view']} بـApp.tsx، بنفس نمط
 * committees.view تمامًا — لكن مع بديل (Bypass) لأي عضو/رئيس لجنة عبر
 * حقل has_any_committee_membership الجديد (راجعي ProtectedRoute.tsx
 * وSidebar.tsx)، بما أن "رئيس اللجنة"/"عضو اللجنة" أدوار لجنة (Committee
 * Role) وليست أدوارًا عامة بجدول roles تُفحص بمعزل عن اللجنة نفسها.
 * القائمة قد ترجع فارغة رغم ظهور الرابط، إن لم تُمنح meetings.view بعد
 * لدور اللجنة من شاشة الأدوار والصلاحيات — هذا سلوك مقصود ومطابق تمامًا
 * لما يحدث بقسم اللجان أصلًا (راجعي committee_service.list_committees).
 *
 * تحديث 2026-09-01 (قرار موثّق مع لاما): أيقونات وصول سريع لكل بطاقة
 * اجتماع (تفاصيل/أجندة/مرفقات/حذف) — بدل الاعتماد فقط على النقر على
 * البطاقة نفسها. أيقونتا الأجندة/المرفقات تنتقلان لصفحة التفاصيل مع
 * hash-anchor (#agenda/#attachments) تُنزّل الصفحة تلقائيًا لذلك القسم
 * (راجعي MeetingDetailPage.tsx). الحذف مسموح فقط قبل موعد الاجتماع
 * (نفس القيد المفروض بالباك-إند — meeting_service.delete_meeting) —
 * تنبيه 2026-09-05: لاما راجعت طلب عكس هذا الشرط بمواصفة إعادة التصميم
 * وتراجعت عنه صراحة ("لا تصلح التناقضات غلط مني ما انتبهت") — القيد هنا
 * وبالباك-إند يبقى كما هو تمامًا، بلا أي تعديل.
 */

/**
 * 'recorded' (MeetingStatus) عمدًا غير موجودة هنا — محجوزة لمرحلة تسجيل
 * الاجتماعات القادمة، ولا يوجد أي اجتماع بهذه الحالة فعليًا بهذه المرحلة
 * (راجعي app/services/meeting_service.py بالباك-إند)، فإضافة شريحة لها
 * تعني شريحة ميتة دائمًا بصفر — تعقيد بلا فائدة.
 */
type StatusFilter = 'all' | 'upcoming' | 'ongoing' | 'finished'

const STATUS_FILTERS: { key: StatusFilter; label: string }[] = [
  { key: 'all', label: 'الكل' },
  { key: 'upcoming', label: 'قادمة' },
  { key: 'ongoing', label: 'جارية' },
  { key: 'finished', label: 'منتهية' },
]

const CHIP_ACTIVE_CLASSES: Record<StatusFilter, string> = {
  all: 'bg-brand-primary text-white border-brand-primary',
  upcoming: 'bg-info-bg text-info border-info-border/40',
  ongoing: 'bg-success-bg text-success border-success-border/40',
  finished: 'bg-neutral-bg text-neutral border-neutral-border/40',
}

/** ألوان الشرائح غير المُفعَّلة — بحدّ ونص بلون الحالة نفسه (خفيف) بدل رمادي موحّد،
 * حتى تبقى الألوان ظاهرة بالواجهة قبل الضغط لا فقط بعده. */
const CHIP_INACTIVE_CLASSES: Record<StatusFilter, string> = {
  all: 'border-border-default text-text-secondary hover:bg-bg-elevated hover:text-text-primary',
  upcoming: 'border-info-border/30 text-info hover:bg-info-bg',
  ongoing: 'border-success-border/30 text-success hover:bg-success-bg',
  finished: 'border-neutral-border/40 text-neutral hover:bg-neutral-bg',
}

export function MeetingsPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { data: meetings, isLoading, isError, refetch } = useMeetings()
  const { data: committees } = useCommittees()
  const createMutation = useCreateMeeting()
  const deleteMutation = useDeleteMeeting()
  const uploadAttachmentMutation = useUploadMeetingAttachment()
  const { showToast } = useToast()

  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [viewMode, setViewMode] = useState<'timeline' | 'calendar'>('timeline')
  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [deletingMeeting, setDeletingMeeting] = useState<Meeting | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

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

  /** نتائج البحث النصي فقط — أساس بطاقات الإحصاء وعدّادات شرائح الفلترة. */
  const searched = useMemo(() => {
    if (!meetings) return []
    const q = search.trim().toLowerCase()
    if (!q) return meetings
    return meetings.filter(
      (m) => m.title.toLowerCase().includes(q) || m.description?.toLowerCase().includes(q),
    )
  }, [meetings, search])

  /** نتائج البحث + شريحة الحالة المختارة — أساس ما يُعرض فعليًا بالقائمة/التقويم. */
  const visible = useMemo(() => {
    if (statusFilter === 'all') return searched
    return searched.filter((m) => m.status === statusFilter)
  }, [searched, statusFilter])

  const stats = useMemo(() => {
    const all = meetings ?? []
    return {
      total: all.length,
      upcoming: all.filter((m) => m.status === 'upcoming').length,
      ongoing: all.filter((m) => m.status === 'ongoing').length,
      finished: all.filter((m) => m.status === 'finished').length,
    }
  }, [meetings])

  /** عدّادات شرائح الفلترة — حيّة (تتحدّث مع كل من البحث النصي والحالة الفعلية للاجتماعات). */
  const chipCounts = useMemo(() => {
    return {
      all: searched.length,
      upcoming: searched.filter((m) => m.status === 'upcoming').length,
      ongoing: searched.filter((m) => m.status === 'ongoing').length,
      finished: searched.filter((m) => m.status === 'finished').length,
    }
  }, [searched])

  /** تجميع العرض الزمني حسب اليوم (توقيت المتصفح المحلي) — ترتيب تصاعدي كامل عبر كل المجموعات. */
  const timelineGroups = useMemo(() => {
    const sorted = [...visible].sort(
      (a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime(),
    )
    const order: string[] = []
    const map = new Map<string, Meeting[]>()
    for (const m of sorted) {
      const key = dayGroupKey(m.scheduled_at)
      if (!map.has(key)) {
        map.set(key, [])
        order.push(key)
      }
      map.get(key)!.push(m)
    }
    return order.map((key) => ({
      key,
      heading: formatDayHeading(map.get(key)![0].scheduled_at),
      items: map.get(key)!,
    }))
  }, [visible])

  function handleCreate(values: MeetingFormSubmitValues) {
    setFormError(null)
    // scheduled_end_at اختياري بنوع MeetingFormSubmitValues (يبقى undefined فقط
    // عند تعديل اجتماع قديم بلا وقت نهاية — راجعي MeetingFormModal.tsx)، لكنه
    // إلزامي دائمًا هنا لأن buildSchema(isEdit=false) بالنموذج يفرضه قبل نجاح
    // onSubmit أصلًا — الـ non-null assertion هنا مطابقة لضمان النموذج، لا تحايل عليه.
    createMutation.mutate({ ...values, scheduled_end_at: values.scheduled_end_at! }, {
      onSuccess: async (created) => {
        setFormOpen(false)
        showToast('تم إنشاء الاجتماع بنجاح', 'success')

        // رفع المرفقات المرحَّلة (Staged) الآن بعد توفر meeting_id فعليًا —
        // راجعي رأس MeetingFormModal.tsx. تسلسليًا (وليس Promise.all) حتى
        // لا يفشل رفع كل الملفات معًا لو رفض الباك-إند واحدًا منها (حجم مثلًا).
        for (const staged of values.attachments) {
          try {
            await uploadAttachmentMutation.mutateAsync({
              meetingId: created.meeting_id,
              file: staged.file,
              linkRole: staged.link_role,
            })
          } catch (err) {
            showToast(`تعذّر رفع "${staged.file.name}": ${extractErrorMessage(err)}`, 'error')
          }
        }

        navigate(`/meetings/${created.meeting_id}`)
      },
      onError: (err) => setFormError(extractErrorMessage(err)),
    })
  }

  /**
   * الحذف مسموح فقط قبل موعد الاجتماع — قيد قائم من قبل هذه المرحلة
   * (راجعي رأس الملف وmeeting_service.delete_meeting)، لم يُمسّ إطلاقًا
   * بإعادة التصميم هذه بناءً على توضيح لاما الصريح 2026-09-05.
   */
  function canDelete(meeting: Meeting): boolean {
    return new Date(meeting.scheduled_at).getTime() > Date.now()
  }

  function handleConfirmDelete() {
    if (!deletingMeeting) return
    setDeleteError(null)
    deleteMutation.mutate(deletingMeeting.meeting_id, {
      onSuccess: () => {
        showToast('تم حذف الاجتماع', 'success')
        setDeletingMeeting(null)
      },
      onError: (err) => setDeleteError(extractErrorMessage(err)),
    })
  }

  const emptyDescription = search
    ? 'جرّب كلمات بحث مختلفة'
    : statusFilter !== 'all'
      ? 'لا توجد اجتماعات بهذه الحالة حاليًا'
      : canCreateAnyMeeting
        ? 'ابدأ بإنشاء أول اجتماع للجنتك'
        : 'تظهر اجتماعاتك هنا فور إنشائها من رئيس اللجنة'

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

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { label: 'إجمالي الاجتماعات', value: stats.total, icon: <Users2 size={20} />, tone: 'brand' as const },
          { label: 'قادمة', value: stats.upcoming, icon: <CalendarClock size={20} />, tone: 'teal' as const },
          { label: 'جارية الآن', value: stats.ongoing, icon: <Video size={20} />, tone: 'success' as const },
          { label: 'منتهية', value: stats.finished, icon: <ListChecks size={20} />, tone: 'purple' as const },
        ].map((stat, i) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: i * 0.05, ease: 'easeOut' }}
          >
            <StatCard label={stat.label} value={stat.value} icon={stat.icon} tone={stat.tone} tintCard />
          </motion.div>
        ))}
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex-1">
          <SearchInput value={search} onChange={setSearch} placeholder="ابحث بعنوان الاجتماع أو وصفه..." />
        </div>

        {/* مفتاح تبديل العرض — زمني (افتراضي) / تقويم. */}
        <div className="flex w-fit shrink-0 items-center gap-0.5 rounded-sm border border-border-default bg-bg-app p-0.5">
          <button
            onClick={() => setViewMode('timeline')}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-xs px-3 py-1.5 text-xs font-semibold transition-colors',
              viewMode === 'timeline'
                ? 'bg-brand-primary text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary',
            )}
          >
            <LayoutList size={14} /> عرض زمني
          </button>
          <button
            onClick={() => setViewMode('calendar')}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-xs px-3 py-1.5 text-xs font-semibold transition-colors',
              viewMode === 'calendar'
                ? 'bg-brand-primary text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary',
            )}
          >
            <CalendarRange size={14} /> عرض التقويم
          </button>
        </div>
      </div>

      {/* شرائح فلترة الحالة — عدّاد حي بجانب كل شريحة، يعكس البحث النصي الحالي. */}
      <div className="flex flex-wrap items-center gap-2">
        {STATUS_FILTERS.map((f) => {
          const active = statusFilter === f.key
          return (
            <button
              key={f.key}
              onClick={() => setStatusFilter(f.key)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition-all duration-150',
                active ? CHIP_ACTIVE_CLASSES[f.key] : CHIP_INACTIVE_CLASSES[f.key],
              )}
            >
              {f.label}
              <span
                className={cn(
                  'rounded-full px-1.5 py-0.5 text-[10px] leading-none',
                  active ? 'bg-white/25' : 'bg-bg-elevated text-text-muted',
                )}
              >
                {chipCounts[f.key]}
              </span>
            </button>
          )
        })}
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : visible.length === 0 ? (
        <EmptyState
          icon={<CalendarDays size={26} />}
          title={search || statusFilter !== 'all' ? 'لا توجد نتائج مطابقة' : 'لا توجد اجتماعات بعد'}
          description={emptyDescription}
          action={
            !search &&
            statusFilter === 'all' &&
            canCreateAnyMeeting && (
              <Button size="sm" icon={<Plus size={14} />} onClick={() => setFormOpen(true)}>
                اجتماع جديد
              </Button>
            )
          }
        />
      ) : (
        <AnimatePresence mode="wait">
          {viewMode === 'calendar' ? (
            <motion.div
              key="calendar"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
            >
              <MeetingCalendarView
                meetings={visible}
                onSelectMeeting={(m) => navigate(`/meetings/${m.meeting_id}`)}
              />
            </motion.div>
          ) : (
            <motion.div
              key="timeline"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="flex flex-col gap-6"
            >
              {timelineGroups.map((group) => (
                <div key={group.key}>
                  <div className="mb-3 flex items-center gap-3">
                    <span className="shrink-0 text-xs font-bold text-text-secondary">{group.heading}</span>
                    <span className="h-px flex-1 bg-border-default" />
                  </div>

                  <div className="border-s-2 border-border-default ps-6">
                    {group.items.map((meeting, i) => {
                      const deletable = canDelete(meeting)
                      const dotColor =
                        meeting.status === 'ongoing'
                          ? 'var(--status-success-main)'
                          : meeting.status === 'upcoming'
                            ? 'var(--status-info-main)'
                            : 'var(--status-neutral-main)'
                      return (
                        <motion.div
                          key={meeting.meeting_id}
                          initial={{ opacity: 0, x: 8 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ duration: 0.2, delay: Math.min(i * 0.03, 0.3) }}
                          className="relative pb-4 last:pb-0"
                        >
                          <span
                            className="absolute -start-[29px] top-5 h-3 w-3 rounded-full ring-4 ring-bg-app"
                            style={{ backgroundColor: dotColor }}
                          />
                          <Card
                            interactive
                            onClick={() => navigate(`/meetings/${meeting.meeting_id}`)}
                            className={cn(cardToneClass(i), 'flex flex-col gap-3 sm:flex-row sm:items-center')}
                          >
                            <div className="flex shrink-0 flex-row items-center gap-2 sm:w-20 sm:flex-col sm:items-center sm:gap-0.5">
                              <span className="text-sm font-bold text-text-primary">
                                {formatTime(meeting.scheduled_at)}
                              </span>
                              {meeting.scheduled_end_at && (
                                <span className="text-[11px] text-text-muted">
                                  حتى {formatTime(meeting.scheduled_end_at)}
                                </span>
                              )}
                            </div>

                            {/* دائرة أيقونة ملوّنة بحسب هوية الشركة (نمط الاجتماع: عن بُعد/حضوري) —
                                تعيد عنصر الهوية اللونية القوي الذي كان بالبطاقات الأصلية قبل إعادة
                                تصميم القائمة الزمنية (ملاحظة لاما 2026-09-05 على خفوت الألوان). */}
                            <div
                              className={cn(
                                'flex h-9 w-9 shrink-0 items-center justify-center rounded-full',
                                iconToneClass(i),
                              )}
                            >
                              {meeting.mode === 'remote' ? <Video size={16} /> : <MapPin size={16} />}
                            </div>

                            <div className="hidden h-10 w-px shrink-0 bg-border-default sm:block" />

                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <h3 className="truncate text-sm font-semibold text-text-primary">
                                  {meeting.title}
                                </h3>
                                <MeetingStatusBadge status={meeting.status} />
                              </div>
                              {meeting.description && (
                                <p className="mt-1 line-clamp-1 text-xs text-text-muted">
                                  {meeting.description}
                                </p>
                              )}
                              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-text-secondary">
                                <span className="flex items-center gap-1">
                                  <Users2 size={12} /> {meeting.participants.length} مشاركين
                                </span>
                                <span className="flex items-center gap-1">
                                  {meeting.mode === 'remote' ? (
                                    <>
                                      <Video size={12} /> عن بُعد
                                    </>
                                  ) : (
                                    <>
                                      <MapPin size={12} /> {meeting.location ?? 'حضوري'}
                                    </>
                                  )}
                                </span>
                              </div>
                            </div>

                            <div className="flex items-center gap-1 border-t border-border-default pt-2.5 sm:border-t-0 sm:border-s sm:ps-3 sm:pt-0">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  navigate(`/meetings/${meeting.meeting_id}`)
                                }}
                                className="rounded-sm p-1.5 text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
                                aria-label="تفاصيل الاجتماع"
                                title="تفاصيل الاجتماع"
                              >
                                <Info size={15} />
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  navigate(`/meetings/${meeting.meeting_id}#agenda`)
                                }}
                                className="rounded-sm p-1.5 text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
                                aria-label="جدول الأعمال"
                                title="جدول الأعمال"
                              >
                                <ListChecks size={15} />
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  navigate(`/meetings/${meeting.meeting_id}#attachments`)
                                }}
                                className="rounded-sm p-1.5 text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
                                aria-label="المرفقات"
                                title="المرفقات"
                              >
                                <Paperclip size={15} />
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  if (!deletable) return
                                  setDeleteError(null)
                                  setDeletingMeeting(meeting)
                                }}
                                disabled={!deletable}
                                className="mr-auto rounded-sm p-1.5 text-text-muted transition-colors hover:bg-danger-bg hover:text-danger disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-text-muted"
                                aria-label="حذف الاجتماع"
                                title={deletable ? 'حذف الاجتماع' : 'لا يمكن حذف الاجتماع بعد بدء موعده'}
                              >
                                <Trash2 size={15} />
                              </button>
                            </div>
                          </Card>
                        </motion.div>
                      )
                    })}
                  </div>
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      )}

      <MeetingFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        committees={chairableCommittees}
        onSubmit={handleCreate}
        loading={createMutation.isPending}
        serverError={formError}
      />

      <ConfirmDialog
        open={!!deletingMeeting}
        onClose={() => setDeletingMeeting(null)}
        onConfirm={handleConfirmDelete}
        title="حذف الاجتماع"
        description={`سيتم حذف اجتماع "${deletingMeeting?.title}" نهائيًا، وسيُرسَل إشعار لكل المشاركين. هل أنتِ متأكدة؟`}
        confirmLabel="حذف"
        loading={deleteMutation.isPending}
        errorMessage={deleteError}
      />
    </div>
  )
}
