import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  CalendarClock,
  CalendarDays,
  Eye,
  ListChecks,
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
import { MeetingStatusBadge } from '@/components/ui/StatusBadge'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/components/ui/Toast'
import { MeetingFormModal, type MeetingFormSubmitValues } from './MeetingFormModal'
import { cardToneClass, extractErrorMessage, formatDateTime } from '@/lib/utils'
import type { Meeting } from '@/types'

/**
 * قائمة الاجتماعات — بدون تكامل Teams فعلي بعد.
 *
 * ملاحظة تصميم (قرار توحيد سلوك القائمة الجانبية بين "اللجان"
 * و"الاجتماعات"، 2026-09-01): المسار محجوب خلف
 * ProtectedRoute anyPermission={['meetings.view']} بـApp.tsx، مع بديل
 * (Bypass) لأي عضو/رئيس لجنة عبر has_any_committee_membership — راجعي
 * ProtectedRoute.tsx وSidebar.tsx. القائمة قد ترجع فارغة رغم ظهور
 * الرابط، إن لم تُمنح meetings.view بعد لدور اللجنة.
 */
export function MeetingsPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { data: meetings, isLoading, isError, refetch } = useMeetings()
  const { data: committees } = useCommittees()
  const createMutation = useCreateMeeting()
  const uploadAttachmentMutation = useUploadMeetingAttachment()
  const deleteMutation = useDeleteMeeting()
  const { showToast } = useToast()

  const [search, setSearch] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Meeting | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  /**
   * اللجان التي يقدر المستخدم الحالي ينشئ لها اجتماعًا — رئيسها فقط
   * (القيد الفعلي محكوم بالباك-إند عبر صلاحية meetings.schedule، هذا مجرد
   * تخمين متفائل لإظهار الزر — راجعي meeting_service._require_access).
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

  /**
   * الإنشاء يحتاج خطوتين متتاليتين: 1) إنشاء الاجتماع نفسه (JSON)، ثم
   * 2) رفع ملفات العرض التقديمي/المرفقات المؤجَّلة (multipart) — تحتاج
   * meeting_id الفعلي الناتج من الخطوة الأولى. فشل الرفع لا يُلغي الاجتماع
   * نفسه (أُنشئ بنجاح فعلًا) — يُعرض تحذيرًا فقط بدل استرجاع كامل.
   */
  async function handleCreate(values: MeetingFormSubmitValues) {
    setFormError(null)
    try {
      const created = await createMutation.mutateAsync(values)

      const uploads: Promise<unknown>[] = []
      if (values.presentationFile) {
        uploads.push(
          uploadAttachmentMutation.mutateAsync({
            meetingId: created.meeting_id,
            file: values.presentationFile,
            kind: 'presentation',
          }),
        )
      }
      for (const file of values.attachmentFiles) {
        uploads.push(
          uploadAttachmentMutation.mutateAsync({
            meetingId: created.meeting_id,
            file,
            kind: 'attachment',
          }),
        )
      }

      setFormOpen(false)
      if (uploads.length > 0) {
        const results = await Promise.allSettled(uploads)
        const failed = results.filter((r) => r.status === 'rejected').length
        if (failed > 0) {
          showToast(`تم إنشاء الاجتماع، لكن تعذّر رفع ${failed} من المرفقات`, 'error')
        } else {
          showToast('تم إنشاء الاجتماع ورفع المرفقات بنجاح', 'success')
        }
      } else {
        showToast('تم إنشاء الاجتماع بنجاح', 'success')
      }
      navigate(`/meetings/${created.meeting_id}`)
    } catch (err) {
      setFormError(extractErrorMessage(err))
    }
  }

  function canDelete(meeting: Meeting): boolean {
    return new Date(meeting.scheduled_at).getTime() > Date.now()
  }

  function handleDeleteConfirm() {
    if (!deleteTarget) return
    setDeleteError(null)
    deleteMutation.mutate(deleteTarget.meeting_id, {
      onSuccess: () => {
        setDeleteTarget(null)
        showToast('تم حذف الاجتماع', 'success')
      },
      onError: (err) => setDeleteError(extractErrorMessage(err)),
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
              <Card className={cardToneClass(i)}>
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

                {/* إجراءات سريعة — راجعي طلب صاحبة المشروع 2026-09-01: تفاصيل/
                    جدول أعمال/مرفقات/حذف بجانب كل اجتماع مباشرة. */}
                <div className="mt-3 flex items-center gap-1 border-t border-border-default pt-3">
                  <button
                    onClick={() => navigate(`/meetings/${meeting.meeting_id}`)}
                    className="flex h-8 w-8 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-brand-primary"
                    aria-label="تفاصيل الاجتماع"
                    title="تفاصيل الاجتماع"
                  >
                    <Eye size={16} />
                  </button>
                  <button
                    onClick={() => navigate(`/meetings/${meeting.meeting_id}?tab=agenda`)}
                    className="flex h-8 w-8 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-brand-primary"
                    aria-label="جدول الأعمال"
                    title="جدول الأعمال"
                  >
                    <ListChecks size={16} />
                  </button>
                  <button
                    onClick={() => navigate(`/meetings/${meeting.meeting_id}?tab=attachments`)}
                    className="flex h-8 w-8 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-brand-primary"
                    aria-label="المرفقات"
                    title="المرفقات"
                  >
                    <Paperclip size={16} />
                  </button>
                  <button
                    onClick={() => {
                      setDeleteError(null)
                      setDeleteTarget(meeting)
                    }}
                    disabled={!canDelete(meeting)}
                    className="flex h-8 w-8 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-danger-bg hover:text-danger disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-text-muted"
                    aria-label="حذف الاجتماع"
                    title={canDelete(meeting) ? 'حذف الاجتماع' : 'لا يمكن الحذف بعد حلول موعد الاجتماع'}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
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
        loading={createMutation.isPending || uploadAttachmentMutation.isPending}
        serverError={formError}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDeleteConfirm}
        title="حذف الاجتماع"
        description={`سيتم حذف اجتماع "${deleteTarget?.title}" نهائيًا. هل أنتِ متأكدة؟`}
        confirmLabel="حذف"
        loading={deleteMutation.isPending}
        errorMessage={deleteError}
      />
    </div>
  )
}
