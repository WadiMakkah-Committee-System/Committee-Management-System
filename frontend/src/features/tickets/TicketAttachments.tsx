import { useState } from 'react'
import { Download, File as FileIcon, FileSpreadsheet, FileText, Image as ImageIcon, Loader2, X } from 'lucide-react'
import * as ticketsApi from '@/api/tickets'
import { useToast } from '@/components/ui/Toast'
import { cn, extractErrorMessage, formatFileSize } from '@/lib/utils'
import { ACCEPTED_FILES_HINT, fileExtension } from './ticketContent'
import type { TicketAttachment } from '@/types/tickets'

/** أيقونة حسب امتداد الملف — صور، PDF/Word، Excel، وغيرها. */
export function FileTypeIcon({ name, size = 16 }: { name: string; size?: number }) {
  const ext = fileExtension(name)
  if (ext === '.png' || ext === '.jpg' || ext === '.jpeg') return <ImageIcon size={size} />
  if (ext === '.xlsx') return <FileSpreadsheet size={size} />
  if (ext === '.pdf' || ext === '.docx') return <FileText size={size} />
  return <FileIcon size={size} />
}

/**
 * قائمة المرفقات المختارة قبل الإرسال، مع زر إزالة لكل ملف.
 * المدخلات: files، onRemove(index). لا تُعرض لو ما فيه ملفات.
 */
export function SelectedFilesList({ files, onRemove }: { files: File[]; onRemove: (index: number) => void }) {
  if (files.length === 0) return null
  return (
    <ul className="flex flex-wrap gap-2" aria-label="المرفقات المختارة">
      {files.map((file, index) => (
        <li
          key={`${file.name}-${file.size}-${index}`}
          className="flex max-w-full items-center gap-2 rounded-sm border border-border-default bg-bg-elevated/60 py-1 pe-1 ps-2.5 text-xs"
        >
          <span className="text-brand-primary">
            <FileTypeIcon name={file.name} size={14} />
          </span>
          <span className="max-w-48 truncate font-medium text-text-primary" title={file.name}>
            {file.name}
          </span>
          <span className="shrink-0 text-text-muted">{formatFileSize(file.size)}</span>
          <button
            type="button"
            onClick={() => onRemove(index)}
            aria-label={`إزالة ${file.name}`}
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-xs text-text-muted transition-colors hover:bg-danger-bg hover:text-danger"
          >
            <X size={13} />
          </button>
        </li>
      ))}
    </ul>
  )
}

/**
 * الهدف: مرفق داخل رسالة محفوظة — ينزل عبر المسار المحمي (فحص صلاحية بالباك-إند)
 * وليس رابطًا عامًا (القسم 9 بالمواصفات).
 * المدخلات: ticketId، attachment، tone (لون الفقاعة: رسالتي/غيري/ملاحظة داخلية).
 */
export function TicketAttachmentLink({
  ticketId,
  attachment,
  onDark,
}: {
  ticketId: string
  attachment: TicketAttachment
  /** الفقاعة بخلفية ملوّنة (رسالتي) — نص فاتح. */
  onDark?: boolean
}) {
  const { showToast } = useToast()
  const [downloading, setDownloading] = useState(false)

  async function download() {
    setDownloading(true)
    try {
      const { blob, fileName } = await ticketsApi.fetchTicketAttachmentBlob(ticketId, attachment.attachment_id)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = fileName || attachment.file_name
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      showToast(extractErrorMessage(err), 'error')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <button
      type="button"
      onClick={download}
      disabled={downloading}
      title={`تنزيل ${attachment.file_name}`}
      className={cn(
        'flex max-w-full items-center gap-2 rounded-sm border px-2.5 py-1.5 text-start text-xs transition-colors disabled:opacity-70',
        onDark
          ? 'border-white/25 bg-white/10 text-white hover:bg-white/20'
          : 'border-border-default bg-bg-surface text-text-primary hover:border-brand-primary/40 hover:bg-brand-primary/[0.04]',
      )}
    >
      <span className={onDark ? 'text-white' : 'text-brand-primary'}>
        <FileTypeIcon name={attachment.file_name} size={14} />
      </span>
      <span className="max-w-52 truncate font-medium">{attachment.file_name}</span>
      <span className={cn('shrink-0', onDark ? 'text-white/70' : 'text-text-muted')}>
        {formatFileSize(attachment.file_size_bytes)}
      </span>
      {downloading ? (
        <Loader2 size={13} className="shrink-0 animate-spin" />
      ) : (
        <Download size={13} className="shrink-0 opacity-70" />
      )}
    </button>
  )
}

/** غطاء "أفلت الملفات هنا" فوق منطقة الإفلات أثناء السحب. */
export function DropOverlay({ active }: { active: boolean }) {
  if (!active) return null
  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-1 rounded-md border-2 border-dashed border-brand-primary bg-brand-primary/[0.06] text-center backdrop-blur-[1px]">
      <span className="text-sm font-semibold text-brand-primary">أفلت الملفات هنا لإرفاقها</span>
      <span className="text-xs text-text-muted">{ACCEPTED_FILES_HINT}</span>
    </div>
  )
}
