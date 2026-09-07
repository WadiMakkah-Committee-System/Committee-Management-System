import { useRef } from 'react'
import { Download, FileText, Paperclip, Trash2, Upload } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { Spinner } from '@/components/ui/Spinner'
import { useToast } from '@/components/ui/Toast'
import {
  useDeleteMeetingAttachment,
  useDownloadMeetingAttachment,
  useMeetingAttachments,
  useOpenMeetingAttachment,
  useUploadMeetingAttachment,
} from '@/hooks/useMeetings'
import { extractErrorMessage, formatFileSize } from '@/lib/utils'

export function AttachmentsPanel({ meetingId }: { meetingId: string }) {
  const { showToast } = useToast()
  const attachmentsQuery = useMeetingAttachments(meetingId)
  const uploadMutation = useUploadMeetingAttachment()
  const downloadMutation = useDownloadMeetingAttachment()
  const openMutation = useOpenMeetingAttachment()
  const deleteMutation = useDeleteMeetingAttachment()
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  function handleFilesSelected(files: FileList | null) {
    if (!files || files.length === 0) return
    Array.from(files).forEach((file) => {
      uploadMutation.mutate(
        { meetingId, file, kind: 'attachment', title: file.name },
        {
          onError: (err) => showToast(extractErrorMessage(err), 'error'),
          onSuccess: () => showToast(`تمت إضافة ${file.name}`),
        },
      )
    })
  }

  async function handleOpen(documentId: string) {
    try {
      await openMutation.mutateAsync({ meetingId, documentId })
    } catch (err) {
      showToast(extractErrorMessage(err), 'error')
    }
  }

  async function handleDownload(documentId: string) {
    try {
      await downloadMutation.mutateAsync({ meetingId, documentId })
    } catch (err) {
      showToast(extractErrorMessage(err), 'error')
    }
  }

  async function handleDelete(documentId: string) {
    try {
      await deleteMutation.mutateAsync({ meetingId, documentId })
      showToast('تم حذف المرفق')
    } catch (err) {
      showToast(extractErrorMessage(err), 'error')
    }
  }

  const attachments = attachmentsQuery.data ?? []

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border-default p-3">
        <p className="text-[13px] font-semibold text-text-primary">المرفقات ({attachments.length})</p>
        <Button size="sm" variant="secondary" icon={<Upload size={14} />} onClick={() => fileInputRef.current?.click()}>
          إضافة
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            handleFilesSelected(e.target.files)
            e.target.value = ''
          }}
        />
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {attachmentsQuery.isLoading ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : attachments.length === 0 ? (
          <EmptyState icon={<Paperclip size={22} />} title="لا توجد مرفقات بعد" />
        ) : (
          <ul className="flex flex-col gap-2">
            {attachments.map((attachment) => (
              <li
                key={attachment.document_id}
                className="flex items-center gap-2.5 rounded-md border border-border-default bg-bg-surface p-2.5"
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-sm bg-brand-primary/10 text-brand-primary">
                  <FileText size={15} />
                </div>
                <button
                  type="button"
                  onClick={() => handleOpen(attachment.document_id)}
                  className="min-w-0 flex-1 text-right"
                  title="فتح للمعاينة"
                >
                  <p className="truncate text-[12px] font-semibold text-text-primary hover:underline">
                    {attachment.file_name}
                  </p>
                  <p className="text-[10px] text-text-muted">
                    {formatFileSize(attachment.file_size_bytes)} · {attachment.uploaded_by.first_name}{' '}
                    {attachment.uploaded_by.last_name}
                  </p>
                </button>
                <div className="flex shrink-0 items-center gap-0.5">
                  <button
                    onClick={() => handleDownload(attachment.document_id)}
                    className="rounded-sm p-1.5 text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
                    aria-label="تحميل"
                    title="تحميل"
                  >
                    <Download size={13} />
                  </button>
                  <button
                    onClick={() => handleDelete(attachment.document_id)}
                    className="rounded-sm p-1.5 text-text-muted transition-colors hover:bg-danger-bg hover:text-danger"
                    aria-label="حذف"
                    title="حذف"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
