import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowRight,
  CalendarClock,
  FileText,
  ListChecks,
  Mail,
  MapPin,
  Paperclip,
  Pencil,
  Plus,
  Presentation,
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
import { cn, extractErrorMessage, formatDateTime } from '@/lib/utils'

/**
 * تفاصيل اجتماع واحد + إدارة جدول أعماله. إجراءات التعديل/الحذف/إدارة
 * الأجندة تظهر فقط لرئيس اللجنة المرتبط بالاجتماع (أو سوبر أدمن) — نفس
 * القيد الهيكلي المفروض بالباك-إند (meeting_service._authorize_manage)،
 * وليس صلاحية عامة من الكتالوج (راجعي MeetingsPage.tsx لتفصيل السبب).
 */
export function MeetingDetailPage() {
  const { meetingId } = useParams<{ meetingId: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const user = useAuthStore((s) => s.user)
  const { showToast } = useToast()

  const { data: meeting, isLoading, isError, refetch } = useMeetingDetail(meetingId)
  const { data: committee } = useCommitteeDetail(meeting?.committee_id)
  const { data: attachments } = useMeetingAttachments(meetingId)
  const uploadAttachmentMutation = useUploadMeetingAttachment()
  const deleteAttachmentMutation = useDeleteMeetingAttachment()

  const agendaSectionRef = useRef<HTMLDivElement>(null)
  const attachmentsSectionRef = useRef<HTMLDivElement>(null)

  /** التمرير التلقائي حسب رابط الإجراء السريع بصفحة القائمة (?tab=agenda|attachments). */
  useEffect(() => {
    const tab = searchParams.get('tab')
    if (tab === 'agenda') {
      agendaSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    } else if (tab === 'attachments') {
      attachmentsSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [searchParams, meeting])

  const updateMeetingMutation = useUpdateMeeting()
  const deleteMeetingMutation = useDeleteMeeting()
  const addAgendaItemMutation = useAddAgendaItem()
  const updateAgendaItemMutation = useUpdateAgendaItem()
  const deleteAgendaItemMutation = useDeleteAgendaItem()

  const [editOpen, setEditOpen] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const [newItemTitle, setNewItemTitle] = useState('')
  const [addItemError, setAddItemError] = useState<string | null>(null)
  const [editingItemId, setEditingItemId] = useState<string | null>(null)
  const [editingItemTitle, setEditingItemTitle] = useState('')
  const [deletingItemId, setDeletingItemId] = useState<string | null>(null)

  const canManage =
    !!user?.role?.is_super_admin || (committee && committee.chair_user_id === user?.user_id)

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

  function handleUploadAttachment(file: File, kind: 'presentation' | 'attachment') {
    if (!meetingId) return
    uploadAttachmentMutation.mutate(
      { meetingId, file, kind },
      {
        onSuccess: () => showToast('تم رفع الملف بنجاح', 'success'),
        onError: (err) => showToast(extractErrorMessage(err), 'error'),
      },
    )
  }

  function handleDeleteAttachment(documentId: string) {
    if (!meetingId) return
    deleteAttachmentMutation.mutate(
      { meetingId, documentId },
      {
        onSuccess: () => showToast('تم حذف المرفق', 'success'),
        onError: (err) => showToast(extractErrorMessage(err), 'error'),
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
                onClick: () => {
                  setDeleteError(null)
                  setDeleteOpen(true)
                },
              },
            ]}
          />
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          {
            icon: <CalendarClock size={20} />,
            tone: 'bg-brand-teal/10 text-brand-teal',
            value: formatDateTime(meeting.scheduled_at),
            label: 'موعد الاجتماع',
          },
          meeting.mode === 'in_person'
            ? {
                icon: <MapPin size={20} />,
                tone: 'bg-brand-orange/10 text-brand-orange',
                value: meeting.location ?? '—',
                label: 'مكان الاجتماع (حضوري)',
              }
            : {
                icon: <Video size={20} />,
                tone: 'bg-brand-teal/10 text-brand-teal',
                value: 'عن بُعد',
                label: 'نوع الاجتماع',
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

      {meeting.description && (
        <Card>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <FileText size={15} />
            وصف الاجتماع
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-text-secondary">{meeting.description}</p>
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

      <div ref={agendaSectionRef}>
      <Card className="p-0">
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
      </div>

      <div ref={attachmentsSectionRef}>
      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <Paperclip size={15} />
            المرفقات
          </h2>
        </div>

        <div className="flex flex-col gap-4 p-4">
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <p className="flex items-center gap-2 text-sm font-medium text-text-primary">
                <Presentation size={14} className="text-text-muted" />
                العرض التقديمي
              </p>
              {canManage && (
                <label className="flex cursor-pointer items-center gap-1.5 rounded-sm border border-dashed border-border-default px-2.5 py-1.5 text-xs text-text-muted transition-colors hover:border-brand-primary hover:text-brand-primary">
                  <Upload size={12} />
                  رفع ملف
                  <input
                    type="file"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0]
                      if (file) handleUploadAttachment(file, 'presentation')
                    }}
                  />
                </label>
              )}
            </div>
            {(attachments ?? []).filter((a) => a.kind === 'presentation').length === 0 ? (
              <p className="text-xs text-text-muted">لا يوجد عرض تقديمي مرفوع بعد</p>
            ) : (
              <ul className="flex flex-col gap-1">
                {(attachments ?? [])
                  .filter((a) => a.kind === 'presentation')
                  .map((a) => (
                    <li
                      key={a.document_id}
                      className="flex items-center justify-between rounded-xs bg-bg-elevated px-2.5 py-2 text-sm text-text-secondary"
                    >
                      <span className="truncate">{a.file_name}</span>
                      {canManage && (
                        <button
                          onClick={() => handleDeleteAttachment(a.document_id)}
                          className="shrink-0 text-text-muted hover:text-danger"
                          aria-label={`حذف ${a.file_name}`}
                        >
                          <Trash2 size={13} />
                        </button>
                      )}
                    </li>
                  ))}
              </ul>
            )}
          </div>

          <div className="flex flex-col gap-2 border-t border-border-default pt-4">
            <div className="flex items-center justify-between">
              <p className="flex items-center gap-2 text-sm font-medium text-text-primary">
                <Paperclip size={14} className="text-text-muted" />
                مرفقات الاجتماع
              </p>
              {canManage && (
                <label className="flex cursor-pointer items-center gap-1.5 rounded-sm border border-dashed border-border-default px-2.5 py-1.5 text-xs text-text-muted transition-colors hover:border-brand-primary hover:text-brand-primary">
                  <Upload size={12} />
                  إضافة مرفق
                  <input
                    type="file"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0]
                      if (file) handleUploadAttachment(file, 'attachment')
                    }}
                  />
                </label>
              )}
            </div>
            {(attachments ?? []).filter((a) => a.kind === 'attachment').length === 0 ? (
              <p className="text-xs text-text-muted">لا توجد مرفقات بعد</p>
            ) : (
              <ul className="flex flex-col gap-1">
                {(attachments ?? [])
                  .filter((a) => a.kind === 'attachment')
                  .map((a) => (
                    <li
                      key={a.document_id}
                      className="flex items-center justify-between rounded-xs bg-bg-elevated px-2.5 py-2 text-sm text-text-secondary"
                    >
                      <span className="truncate">{a.file_name}</span>
                      {canManage && (
                        <button
                          onClick={() => handleDeleteAttachment(a.document_id)}
                          className="shrink-0 text-text-muted hover:text-danger"
                          aria-label={`حذف ${a.file_name}`}
                        >
                          <Trash2 size={13} />
                        </button>
                      )}
                    </li>
                  ))}
              </ul>
            )}
          </div>
        </div>
      </Card>
      </div>

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
        </>
      )}
    </div>
  )
}
