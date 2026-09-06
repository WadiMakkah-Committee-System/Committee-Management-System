import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowRight,
  CalendarClock,
  Download,
  FileText,
  ListChecks,
  Mail,
  MapPin,
  Paperclip,
  Pencil,
  Plus,
  Presentation,
  Radio,
  Trash2,
  Upload,
  Users as UsersIcon,
  Video,
} from 'lucide-react'
import {
  useAddAgendaItem,
  useDeleteAgendaItem,
  useDeleteMeeting,
  useDeleteMeetingAttachment,
  useDownloadMeetingAttachment,
  useOpenMeetingAttachment,
  useMeetingAttachments,
  useMeetingDetail,
  useUpdateAgendaItem,
  useUpdateMeeting,
  useUploadMeetingAttachment,
} from '@/hooks/useMeetings'
import { useCommitteeDetail } from '@/hooks/useCommittees'
import { useAuthStore } from '@/store/authStore'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { ErrorState } from '@/components/ui/ErrorState'
import { Skeleton, TableSkeleton } from '@/components/ui/Skeleton'
import { Avatar } from '@/components/ui/Avatar'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { ActionMenu } from '@/components/ui/ActionMenu'
import { MeetingStatusBadge } from '@/components/ui/StatusBadge'
import { useToast } from '@/components/ui/Toast'
import { MeetingFormModal, type MeetingFormSubmitValues } from './MeetingFormModal'
import { MeetingRoom } from './MeetingRoom'
import { cn, extractErrorMessage, formatDateTime, formatFileSize } from '@/lib/utils'
import type { MeetingAttachment, MeetingAttachmentLinkRole } from '@/types'

/**
 * تفاصيل اجتماع واحد + إدارة جدول أعماله ومرفقاته. إجراءات التعديل/الحذف/
 * إدارة الأجندة والمرفقات تظهر فقط لرئيس اللجنة المرتبط بالاجتماع (أو
 * سوبر أدمن) — نفس القيد الهيكلي المفروض بالباك-إند
 * (meeting_service._require_access مقابل meetings.update/attachments.*)،
 * وليس صلاحية عامة من الكتالوج (راجعي MeetingsPage.tsx لتفصيل السبب).
 *
 * تحديث 2026-09-01 (قرار موثّق مع لاما): قسم "المرفقات" الجديد (بقسمَين:
 * العرض التقديمي، ومرفقات الاجتماع) — أول استخدام فعلي لـdocument_links
 * بالواجهة (راجعي رأس db/migrations/0021 بالباك-إند). كذلك id="agenda-section"/
 * id="attachments-section" + تمرير تلقائي (Scroll) عند فتح الصفحة بـ
 * #agenda أو #attachments بالرابط — تدعم أيقونات الوصول السريع بـ
 * MeetingsPage.tsx.
 */
/** سطر مرفق واحد — قسم فرعي واحد (عرض تقديمي/مرفقات عامة) بصفحة التفاصيل. مرفوعة لمستوى الملف (وليست معرَّفة داخل MeetingDetailPage) لتفادي إعادة تعريفها بكل Render. */
function AttachmentRow({
  attachment,
  canManage,
  onOpen,
  onDownload,
  onDeleteRequest,
}: {
  attachment: MeetingAttachment
  canManage: boolean
  onOpen: () => void
  onDownload: () => void
  onDeleteRequest: () => void
}) {
  return (
    <li className="flex items-center justify-between gap-3 border-b border-border-default px-3 py-2 last:border-0">
      <button
        type="button"
        onClick={onOpen}
        className="flex min-w-0 flex-1 items-center gap-2 text-start"
        title="فتح المرفق"
      >
        <FileText size={14} className="shrink-0 text-text-muted" />
        <div className="min-w-0">
          <p className="truncate text-sm text-text-primary hover:underline">{attachment.file_name}</p>
          <p className="text-[11px] text-text-muted">
            {formatFileSize(attachment.file_size_bytes)} · {attachment.uploaded_by.first_name}{' '}
            {attachment.uploaded_by.last_name}
          </p>
        </div>
      </button>
      <div className="flex shrink-0 items-center gap-1">
        <button
          onClick={onDownload}
          className="rounded-sm p-1.5 text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          aria-label="تحميل المرفق"
          title="تحميل"
        >
          <Download size={14} />
        </button>
        {canManage && (
          <button
            onClick={onDeleteRequest}
            className="rounded-sm p-1.5 text-text-muted transition-colors hover:bg-danger-bg hover:text-danger"
            aria-label="حذف المرفق"
            title="حذف"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>
    </li>
  )
}

export function MeetingDetailPage() {
  const { meetingId } = useParams<{ meetingId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const { showToast } = useToast()

  const { data: meeting, isLoading, isError, refetch } = useMeetingDetail(meetingId)
  const { data: committee } = useCommitteeDetail(meeting?.committee_id)
  const { data: attachments, isLoading: attachmentsLoading } = useMeetingAttachments(meetingId)

  const updateMeetingMutation = useUpdateMeeting()
  const deleteMeetingMutation = useDeleteMeeting()
  const addAgendaItemMutation = useAddAgendaItem()
  const updateAgendaItemMutation = useUpdateAgendaItem()
  const deleteAgendaItemMutation = useDeleteAgendaItem()
  const uploadAttachmentMutation = useUploadMeetingAttachment()
  const deleteAttachmentMutation = useDeleteMeetingAttachment()
  const downloadAttachmentMutation = useDownloadMeetingAttachment()
  const openAttachmentMutation = useOpenMeetingAttachment()

  const [editOpen, setEditOpen] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const [newItemTitle, setNewItemTitle] = useState('')
  const [addItemError, setAddItemError] = useState<string | null>(null)
  const [editingItemId, setEditingItemId] = useState<string | null>(null)
  const [editingItemTitle, setEditingItemTitle] = useState('')
  const [deletingItemId, setDeletingItemId] = useState<string | null>(null)

  const [deletingAttachmentId, setDeletingAttachmentId] = useState<string | null>(null)
  const [attachmentError, setAttachmentError] = useState<string | null>(null)
  const presentationInputRef = useRef<HTMLInputElement>(null)
  const attachmentInputRef = useRef<HTMLInputElement>(null)

  const canManage =
    !!user?.role?.is_super_admin || (committee && committee.chair_user_id === user?.user_id)

  const canDeleteMeeting = !!meeting && new Date(meeting.scheduled_at).getTime() > Date.now()

  const [roomOpen, setRoomOpen] = useState(false)

  // "الوقت الحالي" التفاعلي — يُحدَّث كل 15 ثانية لتقييم isMeetingLive أدناه
  // بدون الحاجة لإعادة تحميل الصفحة (Date.now() وحده لا يُعيد Render تلقائيًا).
  const [nowTick, setNowTick] = useState(() => Date.now())
  useEffect(() => {
    const interval = window.setInterval(() => setNowTick(Date.now()), 15_000)
    return () => window.clearInterval(interval)
  }, [])

  // زر "دخول الاجتماع" النابض يظهر فقط: اجتماع عن بُعد (mode='remote') +
  // وصل موعده فعليًا (scheduled_at <= الآن) + لم يُغلَق بعد (status !== 'finished').
  // نعتمد الوقت المجدوَل وليس started_at لأن started_at لا يُضبط إلا بعد أول
  // /join فعلي (الباك-إند، migration 0022) — لو اعتمدنا عليه لن يظهر الزر
  // لأول شخص يحاول الدخول أصلًا (معضلة الدجاجة والبيضة). راجعي رأس
  // meeting_service.py لقرار عدم ربط status تلقائيًا بهذا الحدث.
  const isMeetingLive =
    !!meeting &&
    meeting.mode === 'remote' &&
    meeting.status !== 'finished' &&
    new Date(meeting.scheduled_at).getTime() <= nowTick &&
    (!meeting.scheduled_end_at || new Date(meeting.scheduled_end_at).getTime() > nowTick)

  // تمرير تلقائي لقسم الأجندة/المرفقات عند فتح الصفحة برابط يحمل
  // #agenda أو #attachments (أيقونات الوصول السريع بـMeetingsPage.tsx).
  useEffect(() => {
    if (!meeting) return
    const hash = location.hash.replace('#', '')
    if (!hash) return
    const el = document.getElementById(`${hash}-section`)
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [meeting, location.hash])

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-8 w-56" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <div className="overflow-hidden rounded-md border border-border-default bg-bg-surface">
          <TableSkeleton />
        </div>
      </div>
    )
  }

  if (isError || !meeting) {
    return <ErrorState onRetry={() => refetch()} />
  }

  function handleUpdate(values: MeetingFormSubmitValues) {
    if (!meetingId) return
    setEditError(null)
    updateMeetingMutation.mutate(
      {
        meetingId,
        payload: {
          title: values.title,
          description: values.description,
          mode: values.mode,
          location: values.location,
          scheduled_at: values.scheduled_at,
          scheduled_end_at: values.scheduled_end_at,
          participant_ids: values.participant_ids,
        },
      },
      {
        onSuccess: () => {
          setEditOpen(false)
          showToast('تم حفظ التعديلات', 'success')
        },
        onError: (err) => setEditError(extractErrorMessage(err)),
      },
    )
  }

  function handleDelete() {
    if (!meetingId) return
    setDeleteError(null)
    deleteMeetingMutation.mutate(meetingId, {
      onSuccess: () => {
        showToast('تم حذف الاجتماع', 'success')
        navigate('/meetings')
      },
      onError: (err) => setDeleteError(extractErrorMessage(err)),
    })
  }

  function handleAddItem() {
    if (!meetingId || !newItemTitle.trim()) return
    setAddItemError(null)
    addAgendaItemMutation.mutate(
      {
        meetingId,
        payload: { title: newItemTitle.trim(), sort_order: meeting!.agenda_items.length },
      },
      {
        onSuccess: () => setNewItemTitle(''),
        onError: (err) => setAddItemError(extractErrorMessage(err)),
      },
    )
  }

  function startEditItem(itemId: string, currentTitle: string) {
    setEditingItemId(itemId)
    setEditingItemTitle(currentTitle)
  }

  function saveEditItem() {
    if (!editingItemId || !meetingId || !editingItemTitle.trim()) return
    updateAgendaItemMutation.mutate(
      { agendaItemId: editingItemId, meetingId, payload: { title: editingItemTitle.trim() } },
      { onSuccess: () => setEditingItemId(null) },
    )
  }

  function confirmDeleteItem() {
    if (!deletingItemId || !meetingId) return
    deleteAgendaItemMutation.mutate(
      { agendaItemId: deletingItemId, meetingId },
      { onSuccess: () => setDeletingItemId(null) },
    )
  }

  function handleUploadAttachment(files: FileList | null, linkRole: MeetingAttachmentLinkRole) {
    if (!meetingId || !files || files.length === 0) return
    setAttachmentError(null)
    Array.from(files).forEach((file) => {
      uploadAttachmentMutation.mutate(
        { meetingId, file, linkRole },
        { onError: (err) => setAttachmentError(extractErrorMessage(err)) },
      )
    })
  }

  function confirmDeleteAttachment() {
    if (!deletingAttachmentId || !meetingId) return
    deleteAttachmentMutation.mutate(
      { meetingId, documentId: deletingAttachmentId },
      { onSuccess: () => setDeletingAttachmentId(null) },
    )
  }

  const presentationAttachments = (attachments ?? []).filter((a) => a.link_role === 'presentation')
  const generalAttachments = (attachments ?? []).filter((a) => a.link_role === 'attachment')

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-start gap-3">
          <button
            onClick={() => navigate('/meetings')}
            className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="العودة إلى الاجتماعات"
          >
            <ArrowRight size={18} />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-text-primary">{meeting.title}</h1>
              <MeetingStatusBadge status={meeting.status} />
            </div>
            {committee && <p className="mt-1 text-sm text-text-muted">لجنة: {committee.name}</p>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isMeetingLive && (
            <button
              type="button"
              onClick={() => setRoomOpen(true)}
              className="animate-live-pulse-ring flex items-center gap-2 rounded-sm bg-success px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-all hover:brightness-95 active:scale-[0.98]"
            >
              <Radio size={15} />
              دخول الاجتماع
            </button>
          )}
          {canManage && (
            <ActionMenu
              items={[
                {
                  label: 'تعديل الاجتماع',
                  icon: <Pencil size={14} />,
                  onClick: () => {
                    setEditError(null)
                    setEditOpen(true)
                  },
                },
                {
                  label: 'حذف الاجتماع',
                  icon: <Trash2 size={14} />,
                  tone: 'danger',
                  disabled: !canDeleteMeeting,
                  onClick: () => {
                    setDeleteError(null)
                    setDeleteOpen(true)
                  },
                },
              ]}
            />
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[
          {
            icon: <CalendarClock size={20} />,
            tone: 'bg-brand-teal/10 text-brand-teal',
            value: formatDateTime(meeting.scheduled_at),
            label: 'موعد الاجتماع',
          },
          {
            icon: <UsersIcon size={20} />,
            tone: 'bg-brand-purple/10 text-brand-purple',
            value: String(meeting.participants.length),
            label: 'عدد المشاركين',
          },
          {
            icon: <ListChecks size={20} />,
            tone: 'bg-brand-primary/10 text-brand-primary',
            value: String(meeting.agenda_items.length),
            label: 'بنود جدول الأعمال',
          },
        ].map((item, i) => (
          <motion.div
            key={item.label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: i * 0.05, ease: 'easeOut' }}
          >
            <Card className="flex items-center gap-4">
              <div className={cn('flex h-12 w-12 shrink-0 items-center justify-center rounded-full', item.tone)}>
                {item.icon}
              </div>
              <div>
                <p className="text-sm font-semibold text-text-primary">{item.value}</p>
                <p className="mt-1 text-xs text-text-muted">{item.label}</p>
              </div>
            </Card>
          </motion.div>
        ))}
      </div>

      {(meeting.description || meeting.mode) && (
        <Card>
          {meeting.description && (
            <>
              <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
                <FileText size={15} />
                وصف الاجتماع
              </h2>
              <p className="mt-2 text-sm leading-relaxed text-text-secondary">{meeting.description}</p>
            </>
          )}
          {meeting.mode && (
            <p
              className={cn(
                'flex items-center gap-1.5 text-sm text-text-secondary',
                meeting.description && 'mt-3 border-t border-border-default pt-3',
              )}
            >
              {meeting.mode === 'remote' ? <Video size={14} /> : <MapPin size={14} />}
              {meeting.mode === 'in_person'
                ? `اجتماع حضوري${meeting.location ? ` — ${meeting.location}` : ''}`
                : 'اجتماع عن بُعد'}
            </p>
          )}
        </Card>
      )}

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <UsersIcon size={15} />
            المشاركون
          </h2>
        </div>
        <ul>
          {meeting.participants.map((p, i) => (
            <motion.li
              key={p.user_id}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.15, delay: Math.min(i * 0.02, 0.2) }}
              className="flex flex-col gap-1.5 border-b border-border-default px-4 py-3 last:border-0 sm:flex-row sm:items-center sm:justify-between sm:gap-3"
            >
              <div className="flex items-center gap-3">
                <Avatar firstName={p.first_name} lastName={p.last_name} />
                <p className="font-medium text-text-primary">
                  {p.first_name} {p.last_name}
                </p>
              </div>
              <span className="flex items-center gap-1.5 text-sm text-text-secondary">
                <Mail size={13} className="shrink-0" />
                {p.email}
              </span>
            </motion.li>
          ))}
        </ul>
      </Card>

      <Card id="agenda-section" className="scroll-mt-4 p-0">
        <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <ListChecks size={15} />
            جدول الأعمال
          </h2>
        </div>

        {meeting.agenda_items.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-text-muted">لا توجد بنود بعد</p>
        ) : (
          <ul>
            {meeting.agenda_items.map((item, i) => (
              <motion.li
                key={item.agenda_item_id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.15, delay: Math.min(i * 0.02, 0.2) }}
                className="flex items-center justify-between gap-3 border-b border-border-default px-4 py-3 last:border-0"
              >
                {editingItemId === item.agenda_item_id ? (
                  <div className="flex flex-1 items-center gap-2">
                    <Input
                      value={editingItemTitle}
                      onChange={(e) => setEditingItemTitle(e.target.value)}
                      className="h-8"
                    />
                    <Button size="sm" onClick={saveEditItem} loading={updateAgendaItemMutation.isPending}>
                      حفظ
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditingItemId(null)}>
                      إلغاء
                    </Button>
                  </div>
                ) : (
                  <>
                    <span className="text-sm text-text-primary">
                      {i + 1}. {item.title}
                    </span>
                    {canManage && (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => startEditItem(item.agenda_item_id, item.title)}
                          className="rounded-sm p-1.5 text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
                          aria-label="تعديل البند"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          onClick={() => setDeletingItemId(item.agenda_item_id)}
                          className="rounded-sm p-1.5 text-text-muted transition-colors hover:bg-danger-bg hover:text-danger"
                          aria-label="حذف البند"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    )}
                  </>
                )}
              </motion.li>
            ))}
          </ul>
        )}

        {canManage && (
          <div className="flex items-center gap-2 border-t border-border-default px-4 py-3">
            <Input
              value={newItemTitle}
              onChange={(e) => setNewItemTitle(e.target.value)}
              placeholder="عنوان بند جديد..."
              className="h-9"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  handleAddItem()
                }
              }}
            />
            <Button
              size="sm"
              icon={<Plus size={14} />}
              onClick={handleAddItem}
              loading={addAgendaItemMutation.isPending}
              disabled={!newItemTitle.trim()}
            >
              إضافة
            </Button>
          </div>
        )}
        {addItemError && (
          <p className="border-t border-border-default px-4 py-2 text-xs font-medium text-danger">
            {addItemError}
          </p>
        )}
      </Card>

      <Card id="attachments-section" className="scroll-mt-4 p-0">
        <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <Paperclip size={15} />
            المرفقات
          </h2>
        </div>

        <div className="flex flex-col gap-4 p-4">
          <div className="rounded-sm border border-border-default">
            <div className="flex items-center justify-between gap-2 border-b border-border-default px-3 py-2">
              <h3 className="flex items-center gap-2 text-xs font-semibold text-text-primary">
                <Presentation size={14} className="text-text-muted" />
                العرض التقديمي
              </h3>
              {canManage && (
                <button
                  onClick={() => presentationInputRef.current?.click()}
                  className="flex items-center gap-1 text-xs font-medium text-brand-primary hover:underline"
                >
                  <Upload size={12} />
                  رفع ملف
                </button>
              )}
              <input
                ref={presentationInputRef}
                type="file"
                className="hidden"
                onChange={(e) => {
                  handleUploadAttachment(e.target.files, 'presentation')
                  e.target.value = ''
                }}
              />
            </div>
            {attachmentsLoading ? (
              <p className="px-3 py-4 text-center text-xs text-text-muted">جارِ التحميل...</p>
            ) : presentationAttachments.length === 0 ? (
              <p className="px-3 py-4 text-center text-xs text-text-muted">لا يوجد عرض تقديمي بعد</p>
            ) : (
              <ul>
                {presentationAttachments.map((a) => (
                  <AttachmentRow
                    key={a.document_id}
                    attachment={a}
                    canManage={!!canManage}
                    onOpen={() =>
                      openAttachmentMutation.mutate({ meetingId: meetingId!, documentId: a.document_id })
                    }
                    onDownload={() =>
                      downloadAttachmentMutation.mutate({ meetingId: meetingId!, documentId: a.document_id })
                    }
                    onDeleteRequest={() => setDeletingAttachmentId(a.document_id)}
                  />
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-sm border border-border-default">
            <div className="flex items-center justify-between gap-2 border-b border-border-default px-3 py-2">
              <h3 className="flex items-center gap-2 text-xs font-semibold text-text-primary">
                <Paperclip size={14} className="text-text-muted" />
                مرفقات الاجتماع
              </h3>
              {canManage && (
                <button
                  onClick={() => attachmentInputRef.current?.click()}
                  className="flex items-center gap-1 text-xs font-medium text-brand-primary hover:underline"
                >
                  <Upload size={12} />
                  رفع ملف
                </button>
              )}
              <input
                ref={attachmentInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(e) => {
                  handleUploadAttachment(e.target.files, 'attachment')
                  e.target.value = ''
                }}
              />
            </div>
            {attachmentsLoading ? (
              <p className="px-3 py-4 text-center text-xs text-text-muted">جارِ التحميل...</p>
            ) : generalAttachments.length === 0 ? (
              <p className="px-3 py-4 text-center text-xs text-text-muted">لا توجد مرفقات بعد</p>
            ) : (
              <ul>
                {generalAttachments.map((a) => (
                  <AttachmentRow
                    key={a.document_id}
                    attachment={a}
                    canManage={!!canManage}
                    onOpen={() =>
                      openAttachmentMutation.mutate({ meetingId: meetingId!, documentId: a.document_id })
                    }
                    onDownload={() =>
                      downloadAttachmentMutation.mutate({ meetingId: meetingId!, documentId: a.document_id })
                    }
                    onDeleteRequest={() => setDeletingAttachmentId(a.document_id)}
                  />
                ))}
              </ul>
            )}
          </div>

          {attachmentError && <p className="text-xs font-medium text-danger">{attachmentError}</p>}
        </div>
      </Card>

      <p className="text-xs text-text-muted">أُنشئ الاجتماع في {formatDateTime(meeting.created_at)}</p>

      {canManage && (
        <>
          <MeetingFormModal
            open={editOpen}
            onClose={() => setEditOpen(false)}
            committees={committee ? [committee] : []}
            meeting={meeting}
            onSubmit={handleUpdate}
            loading={updateMeetingMutation.isPending}
            serverError={editError}
          />
          <ConfirmDialog
            open={deleteOpen}
            onClose={() => setDeleteOpen(false)}
            onConfirm={handleDelete}
            title="حذف الاجتماع"
            description={`سيتم حذف اجتماع "${meeting.title}" نهائيًا، وسيُرسَل إشعار لكل المشاركين. هل أنتِ متأكدة؟`}
            confirmLabel="حذف"
            loading={deleteMeetingMutation.isPending}
            errorMessage={deleteError}
          />
          <ConfirmDialog
            open={!!deletingItemId}
            onClose={() => setDeletingItemId(null)}
            onConfirm={confirmDeleteItem}
            title="حذف بند جدول الأعمال"
            description="سيتم حذف هذا البند نهائيًا من جدول الأعمال. هل أنتِ متأكدة؟"
            confirmLabel="حذف"
            loading={deleteAgendaItemMutation.isPending}
          />
          <ConfirmDialog
            open={!!deletingAttachmentId}
            onClose={() => setDeletingAttachmentId(null)}
            onConfirm={confirmDeleteAttachment}
            title="حذف المرفق"
            description="سيتم حذف هذا المرفق نهائيًا. هل أنتِ متأكدة؟"
            confirmLabel="حذف"
            loading={deleteAttachmentMutation.isPending}
          />
        </>
      )}

      {roomOpen && meetingId && (
        <MeetingRoom meetingId={meetingId} meetingTitle={meeting.title} onClose={() => setRoomOpen(false)} />
      )}
    </div>
  )
}
