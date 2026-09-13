import { useEffect, useState } from 'react'
import { CalendarRange, Save } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { DateField } from '@/components/ui/DateField'
import { Button } from '@/components/ui/Button'
import type { Committee } from '@/types'

interface CommitteeDatesEditModalProps {
  open: boolean
  onClose: () => void
  committee: Committee
  onSubmit: (values: { start_date: string; end_date: string }) => void
  loading?: boolean
  serverError?: string | null
}

/**
 * تعديل فترة عمل لجنة معتمدة (start_date/end_date فقط) — قرار صاحبة
 * المشروع 2026-09-13 ("قاعدة فترة اللجنة"). متاح فقط لمن يملك
 * committees.update (المكتب التنفيذي، راجعي CommitteeDetailPage.tsx).
 *
 * لا حدّ أدنى/أقصى مفروض هنا على الحقلين أنفسهما (بخلاف نماذج الاجتماع/
 * المهمة/القرار التي تُقيَّد بفترة لجنتها) — هذا النموذج بالذات *يُعرِّف*
 * فترة اللجنة نفسها. التحقق الفعلي (النهاية بعد البداية، وعدم وجود
 * اجتماعات/مهام/قرارات مرتبطة تقع خارج النطاق الجديد) بالكامل من
 * الـbackend (committee_service.update_committee) — serverError يعرض
 * رسالته الصريحة مباشرة.
 */
export function CommitteeDatesEditModal({
  open,
  onClose,
  committee,
  onSubmit,
  loading,
  serverError,
}: CommitteeDatesEditModalProps) {
  const [startDate, setStartDate] = useState(committee.start_date)
  const [endDate, setEndDate] = useState(committee.end_date)

  useEffect(() => {
    if (open) {
      setStartDate(committee.start_date)
      setEndDate(committee.end_date)
    }
  }, [open, committee.start_date, committee.end_date])

  const clientError = endDate && startDate && endDate < startDate
    ? 'تاريخ النهاية يجب أن يكون بعد تاريخ البداية'
    : null

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="تعديل فترة عمل اللجنة"
      description={`${committee.name} — تعديل تاريخي البداية والنهاية فقط`}
      size="sm"
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2 border-b border-border-default pb-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-xs bg-brand-primary/10 text-brand-primary">
            <CalendarRange size={13} />
          </span>
          <h3 className="text-xs font-bold uppercase tracking-wide text-text-secondary">فترة عمل اللجنة</h3>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <DateField label="تاريخ البداية" required value={startDate} onChange={setStartDate} />
          <DateField
            label="تاريخ النهاية"
            required
            value={endDate}
            onChange={setEndDate}
            error={clientError ?? undefined}
          />
        </div>

        <p className="text-xs text-text-muted">
          تنبيه: تضييق الفترة سيُرفَض تلقائيًا لو كان هناك اجتماعات أو مهام أو قرارات مرتبطة باللجنة تقع خارج
          النطاق الجديد.
        </p>

        {serverError && (
          <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
            {serverError}
          </p>
        )}

        <div className="flex items-center justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button
            icon={<Save size={15} />}
            loading={loading}
            disabled={!!clientError || !startDate || !endDate}
            onClick={() => onSubmit({ start_date: startDate, end_date: endDate })}
          >
            حفظ
          </Button>
        </div>
      </div>
    </Modal>
  )
}
