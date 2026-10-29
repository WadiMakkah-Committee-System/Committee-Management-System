import { formatDate } from '@/lib/utils'
import type { CommitteeDurationType } from '@/types'

/** خيارات نوع مدة اللجنة بنموذج طلب التشكيل — مطابقة لـ CommitteeDurationType بالباك-إند. */
export const COMMITTEE_DURATION_OPTIONS: { value: CommitteeDurationType; label: string }[] = [
  { value: 'temporary', label: 'مؤقتة' },
  { value: 'permanent', label: 'دائمة' },
]

/**
 * الهدف: نص موحّد لعرض فترة عمل اللجنة (أو طلب تشكيلها) بكل الشاشات.
 *
 * المدخلات: كائن فيه duration_type وstart_date/end_date (لجنة أو طلب تشكيل).
 *
 * المخرجات: "دائمة" للجنة الدائمة (بلا تواريخ — الهجرة 0037)، وإلا
 * "البداية — النهاية" بنفس تنسيق formatDate.
 *
 * بلا تأثيرات جانبية.
 */
export function formatCommitteePeriod(item: {
  duration_type: CommitteeDurationType
  start_date: string | null
  end_date: string | null
}): string {
  if (item.duration_type === 'permanent') return 'دائمة'
  return `${formatDate(item.start_date)} — ${formatDate(item.end_date)}`
}
