import { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import {
  CalendarDays,
  ChevronLeft,
  ClipboardList,
  Download,
  FileText,
  FolderOpen,
  ListTodo,
  Paperclip,
  ScrollText,
  Users2,
} from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { CardSkeleton } from '@/components/ui/Skeleton'
import { Spinner } from '@/components/ui/Spinner'
import { useToast } from '@/components/ui/Toast'
import {
  useAttachmentCommitteeMeetings,
  useAttachmentCommittees,
  useAttachmentMeetingBundle,
  useDownloadMinutesPdf,
} from '@/hooks/useCommitteeAttachments'
import { useDownloadMeetingAttachment, useOpenMeetingAttachment } from '@/hooks/useMeetings'
import { cardToneClass, cn, extractErrorMessage, formatDate, formatDateTime, formatFileSize } from '@/lib/utils'
import type {
  CommitteeAttachmentsBundleFile,
  CommitteeAttachmentsCommittee,
  CommitteeAttachmentsMeeting,
  MeetingMinutesStage,
} from '@/types'

type Section = 'meetings' | 'tasks'

const MINUTES_STAGE_LABELS: Record<MeetingMinutesStage, string> = {
  none: 'لم يبدأ',
  preparing: 'قيد الإعداد',
  review: 'المراجعة',
  approval: 'الاعتماد',
  signature: 'التوقيع الإلكتروني',
  completed: 'مكتمل',
}

/**
 * الهدف:
 * تصنيف "مرفقات اللجنة" بصفحة الوثائق (طلب لاما 2026-11-01): تصفّح هرمي
 * لجنة ← قسم (مرفقات الاجتماعات / مرفقات المهام) ← اجتماع ← مرفقاته ومحضره.
 *
 * الأداء (شرط لاما الصريح): كل مستوى يجلب بياناته فقط لما يُفتح —
 * - فتح التصنيف: طلب اللجان فقط.
 * - اختيار لجنة: لا طلب إطلاقًا (القسمان ثابتان بالواجهة).
 * - "مرفقات الاجتماعات": أسماء الاجتماعات فقط. "مرفقات المهام": لا طلب (فاضي حاليًا).
 * - اختيار اجتماع: مرفقاته + حالة المحضر. ملف المحضر نفسه يُولَّد عند الضغط فقط.
 * الرجوع بالمسار (breadcrumb) يعيد استخدام الكاش (staleTime دقيقة) بلا طلب جديد.
 */
export function CommitteeAttachmentsBrowser() {
  const [committee, setCommittee] = useState<CommitteeAttachmentsCommittee | null>(null)
  const [section, setSection] = useState<Section | null>(null)
  const [meeting, setMeeting] = useState<CommitteeAttachmentsMeeting | null>(null)

  const crumbs: { label: string; onClick?: () => void }[] = [
    {
      label: 'لجاني',
      onClick: committee
        ? () => {
            setCommittee(null)
            setSection(null)
            setMeeting(null)
          }
        : undefined,
    },
  ]
  if (committee) {
    crumbs.push({
      label: committee.name,
      onClick: section
        ? () => {
            setSection(null)
            setMeeting(null)
          }
        : undefined,
    })
  }
  if (section) {
    crumbs.push({
      label: section === 'meetings' ? 'مرفقات الاجتماعات' : 'مرفقات المهام',
      onClick: meeting ? () => setMeeting(null) : undefined,
    })
  }
  if (meeting) crumbs.push({ label: meeting.title })

  return (
    <div className="flex flex-col gap-4">
      <nav aria-label="مسار مرفقات اللجنة" className="flex flex-wrap items-center gap-1 text-sm">
        {crumbs.map((crumb, i) => (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <ChevronLeft size={14} className="text-text-muted" />}
            {crumb.onClick ? (
              <button
                type="button"
                onClick={crumb.onClick}
                className="rounded-xs px-1 font-semibold text-brand-primary hover:underline"
              >
                {crumb.label}
              </button>
            ) : (
              <span className="px-1 font-semibold text-text-primary">{crumb.label}</span>
            )}
          </span>
        ))}
      </nav>

      {!committee ? (
        <CommitteesLevel onSelect={setCommittee} />
      ) : !section ? (
        <SectionsLevel onSelect={setSection} />
      ) : section === 'tasks' ? (
        <EmptyState
          icon={<ListTodo size={26} />}
          title="لا توجد مرفقات مهام بعد"
          description="مرفقات مهام اللجنة ستظهر هنا"
        />
      ) : !meeting ? (
        <MeetingsLevel committeeId={committee.committee_id} onSelect={setMeeting} />
      ) : (
        <MeetingLevel meetingId={meeting.meeting_id} />
      )}
    </div>
  )
}

function LevelGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">{children}</div>
}

function LevelSkeleton() {
  return (
    <LevelGrid>
      {Array.from({ length: 3 }).map((_, i) => (
        <CardSkeleton key={i} />
      ))}
    </LevelGrid>
  )
}

function FolderCard({
  index,
  icon,
  title,
  subtitle,
  badge,
  onClick,
}: {
  index: number
  icon: React.ReactNode
  title: string
  subtitle?: string
  badge?: React.ReactNode
  onClick: () => void
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: Math.min(index * 0.03, 0.3) }}
    >
      <Card interactive onClick={onClick} className={cn('flex h-full items-center gap-3', cardToneClass(index))}>
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-sm bg-brand-primary/10 text-brand-primary">
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold text-text-primary">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-text-muted">{subtitle}</p>}
        </div>
        {badge}
        <ChevronLeft size={16} className="shrink-0 text-text-muted" />
      </Card>
    </motion.div>
  )
}

function CommitteesLevel({ onSelect }: { onSelect: (c: CommitteeAttachmentsCommittee) => void }) {
  const { data, isLoading, isError, refetch } = useAttachmentCommittees(true)
  const groups = useMemo(
    () => ({
      active: (data ?? []).filter((c) => !c.is_ended),
      ended: (data ?? []).filter((c) => c.is_ended),
    }),
    [data],
  )

  if (isLoading) return <LevelSkeleton />
  if (isError) return <ErrorState onRetry={() => refetch()} />
  if (!data || data.length === 0) {
    return (
      <EmptyState icon={<Users2 size={26} />} title="لا توجد لجان" description="اللجان اللي أنت عضو فيها بتظهر هنا" />
    )
  }

  return (
    <div className="flex flex-col gap-6">
      {(
        [
          ['active', 'لجان جارية'],
          ['ended', 'لجان منتهية'],
        ] as const
      ).map(([key, label]) =>
        groups[key].length === 0 ? null : (
          <section key={key} className="flex flex-col gap-3">
            <h2 className="text-sm font-bold text-text-secondary">
              {label} <span className="font-normal text-text-muted">({groups[key].length})</span>
            </h2>
            <LevelGrid>
              {groups[key].map((c, i) => (
                <FolderCard
                  key={c.committee_id}
                  index={i}
                  icon={<Users2 size={18} />}
                  title={c.name}
                  subtitle={c.end_date ? `${c.is_ended ? 'انتهت' : 'تنتهي'} ${formatDate(c.end_date)}` : 'لجنة دائمة'}
                  badge={
                    <span
                      className={cn(
                        'shrink-0 rounded-xs px-1.5 py-0.5 text-[11px] font-semibold',
                        c.is_ended ? 'bg-bg-elevated text-text-muted' : 'bg-success-bg text-success',
                      )}
                    >
                      {c.is_ended ? 'منتهية' : 'جارية'}
                    </span>
                  }
                  onClick={() => onSelect(c)}
                />
              ))}
            </LevelGrid>
          </section>
        ),
      )}
    </div>
  )
}

function SectionsLevel({ onSelect }: { onSelect: (s: Section) => void }) {
  return (
    <LevelGrid>
      <FolderCard
        index={0}
        icon={<CalendarDays size={18} />}
        title="مرفقات الاجتماعات"
        subtitle="ملفات الاجتماعات ومحاضرها"
        onClick={() => onSelect('meetings')}
      />
      <FolderCard
        index={1}
        icon={<ClipboardList size={18} />}
        title="مرفقات المهام"
        subtitle="ملفات مهام اللجنة"
        onClick={() => onSelect('tasks')}
      />
    </LevelGrid>
  )
}

function MeetingsLevel({
  committeeId,
  onSelect,
}: {
  committeeId: string
  onSelect: (m: CommitteeAttachmentsMeeting) => void
}) {
  const { data, isLoading, isError, refetch } = useAttachmentCommitteeMeetings(committeeId)
  if (isLoading) return <LevelSkeleton />
  if (isError) return <ErrorState onRetry={() => refetch()} />
  if (!data || data.length === 0) {
    return (
      <EmptyState
        icon={<CalendarDays size={26} />}
        title="لا توجد اجتماعات"
        description="ما فيه اجتماعات لهذي اللجنة بعد"
      />
    )
  }
  return (
    <LevelGrid>
      {data.map((m, i) => (
        <FolderCard
          key={m.meeting_id}
          index={i}
          icon={<FolderOpen size={18} />}
          title={m.title}
          subtitle={formatDateTime(m.scheduled_at)}
          onClick={() => onSelect(m)}
        />
      ))}
    </LevelGrid>
  )
}

function MeetingLevel({ meetingId }: { meetingId: string }) {
  const { showToast } = useToast()
  const { data, isLoading, isError, refetch } = useAttachmentMeetingBundle(meetingId)
  const downloadMutation = useDownloadMeetingAttachment()
  const openMutation = useOpenMeetingAttachment()
  const minutesMutation = useDownloadMinutesPdf()

  const groups = useMemo(() => {
    const general: CommitteeAttachmentsBundleFile[] = []
    const byItem = new Map<string, { title: string; files: CommitteeAttachmentsBundleFile[] }>()
    for (const file of data?.attachments ?? []) {
      if (file.kind === 'agenda' && file.agenda_item_id) {
        const group = byItem.get(file.agenda_item_id) ?? {
          title: file.agenda_item_title ?? 'بند',
          files: [],
        }
        group.files.push(file)
        byItem.set(file.agenda_item_id, group)
      } else {
        general.push(file)
      }
    }
    return { general, byItem: [...byItem.values()] }
  }, [data])

  if (isLoading) return <LevelSkeleton />
  if (isError || !data) return <ErrorState onRetry={() => refetch()} />

  const onError = (err: unknown) => showToast(extractErrorMessage(err), 'error')
  const fileRow = (file: CommitteeAttachmentsBundleFile) => (
    <li
      key={file.document_id}
      className="flex items-center justify-between gap-3 border-b border-border-default py-2 last:border-0"
    >
      <button
        type="button"
        onClick={() => openMutation.mutate({ meetingId, documentId: file.document_id }, { onError })}
        className="flex min-w-0 flex-1 items-center gap-2 text-start"
        title="فتح المرفق"
      >
        <FileText size={14} className="shrink-0 text-text-muted" />
        <div className="min-w-0">
          <p className="truncate text-sm text-text-primary hover:underline">{file.file_name}</p>
          <p className="text-[11px] text-text-muted">
            {file.kind === 'presentation' ? 'عرض تقديمي · ' : ''}
            {formatFileSize(file.file_size_bytes)} · {file.uploaded_by.first_name} {file.uploaded_by.last_name}
          </p>
        </div>
      </button>
      <button
        type="button"
        onClick={() => downloadMutation.mutate({ meetingId, documentId: file.document_id }, { onError })}
        className="rounded-sm p-1.5 text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
        aria-label="تحميل المرفق"
        title="تحميل"
      >
        <Download size={14} />
      </button>
    </li>
  )

  return (
    <div className="flex flex-col gap-4">
      {data.can_view_minutes && (
        <Card className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-sm bg-brand-primary/10 text-brand-primary">
            <ScrollText size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-text-primary">محضر الاجتماع</h3>
            <p className="mt-0.5 text-xs text-text-muted">
              {data.minutes_available && data.minutes_stage
                ? `المرحلة: ${MINUTES_STAGE_LABELS[data.minutes_stage]} · PDF`
                : 'لم يبدأ إعداد المحضر بعد'}
            </p>
          </div>
          {data.minutes_available && (
            <button
              type="button"
              onClick={() => minutesMutation.mutate(meetingId, { onError })}
              disabled={minutesMutation.isPending}
              className="flex items-center gap-1.5 rounded-sm bg-brand-primary px-3 py-1.5 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {minutesMutation.isPending ? <Spinner size={13} /> : <Download size={13} />}
              تحميل المحضر
            </button>
          )}
        </Card>
      )}

      {data.can_view_attachments &&
        (data.attachments.length === 0 ? (
          <EmptyState
            icon={<Paperclip size={26} />}
            title="لا توجد مرفقات"
            description="ما فيه ملفات مرفوعة لهذا الاجتماع"
          />
        ) : (
          <>
            {groups.general.length > 0 && (
              <Card className="flex flex-col gap-1">
                <h3 className="text-sm font-bold text-text-secondary">مرفقات الاجتماع</h3>
                <ul>{groups.general.map(fileRow)}</ul>
              </Card>
            )}
            {groups.byItem.map((group) => (
              <Card key={group.title + group.files[0].document_id} className="flex flex-col gap-1">
                <h3 className="flex items-center gap-1.5 text-sm font-bold text-text-secondary">
                  <Paperclip size={13} />
                  بند: {group.title}
                </h3>
                <ul>{group.files.map(fileRow)}</ul>
              </Card>
            ))}
          </>
        ))}
    </div>
  )
}
