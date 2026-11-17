import { useCallback, useState } from 'react'
import { useDropzone, type FileRejection } from 'react-dropzone'
import { ACCEPTED_FILE_TYPES, MAX_FILE_BYTES, MAX_FILE_MB, MAX_FILES_PER_MESSAGE } from './ticketContent'

/**
 * الهدف: رسالة عربية واضحة لملف رفضه react-dropzone قبل الإرسال.
 * المدخلات: الملف المرفوض وأسباب الرفض. المخرجات: نص يذكر اسم الملف والسبب.
 */
function rejectionMessage(rejection: FileRejection): string {
  const name = rejection.file.name
  const code = rejection.errors[0]?.code
  if (code === 'file-invalid-type') return `نوع الملف (${name}) غير مسموح — المسموح: PNG وJPG وPDF وDOCX وXLSX`
  if (code === 'file-too-large') return `حجم الملف (${name}) يتجاوز ${MAX_FILE_MB} ميجابايت`
  return `تعذّر إضافة الملف (${name})`
}

/**
 * الهدف:
 * اختيار مرفقات رسالة بالسحب والإفلات أو من الجهاز — react-dropzone (معتمدة
 * 2026-11-17) بدل بناء منطق السحب والإفلات من الصفر.
 *
 * المسؤولية:
 * - قبول الأنواع المسموحة فقط وحد الحجم (نفس حدود الباك-إند، القسم 5).
 * - حد 5 ملفات لكل رسالة شاملًا المختارة مسبقًا.
 * - تجاهل تكرار نفس الملف (نفس الاسم والحجم).
 * - رسالة خطأ عربية للمرفوض.
 *
 * المدخلات: files (المختارة حاليًا)، onFilesChange، disabled.
 * المخرجات: خصائص منطقة الإفلات وحقل الملفات، isDragActive، open() لفتح نافذة
 * اختيار الملفات من زر، والخطأ الحالي.
 * الأمان: فحص الواجهة للتجربة فقط — الباك-إند يفحص النوع من محتوى الملف نفسه.
 */
export function useTicketFilePicker(files: File[], onFilesChange: (next: File[]) => void, disabled = false) {
  const [error, setError] = useState<string | null>(null)

  const onDrop = useCallback(
    (accepted: File[], rejected: FileRejection[]) => {
      const fresh = accepted.filter(
        (file) => !files.some((existing) => existing.name === file.name && existing.size === file.size),
      )
      const room = MAX_FILES_PER_MESSAGE - files.length
      const messages = rejected.map(rejectionMessage)
      if (fresh.length > room) messages.push(`الحد الأقصى ${MAX_FILES_PER_MESSAGE} مرفقات لكل رسالة`)
      setError(messages[0] ?? null)
      if (room > 0 && fresh.length > 0) onFilesChange([...files, ...fresh.slice(0, room)])
    },
    [files, onFilesChange],
  )

  const dropzone = useDropzone({
    onDrop,
    accept: ACCEPTED_FILE_TYPES,
    maxSize: MAX_FILE_BYTES,
    multiple: true,
    disabled,
    // النقر على المنطقة كاملة ما يفتح نافذة الملفات (المنطقة فيها المحرر)؛ زر الإرفاق يستدعي open().
    noClick: true,
    noKeyboard: true,
  })

  return { ...dropzone, error, clearError: () => setError(null) }
}
