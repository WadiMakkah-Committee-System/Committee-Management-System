import { useEffect, useState } from 'react'
import { CalendarPlus, Crown, History, NotebookPen, Save, UserMinus, UserPlus } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { DateField } from '@/components/ui/DateField'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { EmptyState } from '@/components/ui/EmptyState'
import { TableSkeleton } from '@/components/ui/Skeleton'
import { useCommitteeChanges, useCommitteeMemberCandidates } from '@/hooks/useCommittees'
import { formatDate, formatDateTime } from '@/lib/utils'
import type { Committee, CommitteeChange, CommitteeMemberUser } from '@/types'

/**
 * أدوات تعديل عضوية اللجنة الدائمة بعد اعتمادها + تمديد الفترة + سجل
 * التغييرات (migration 0050 — طلب لاما 2026-11-16: "اللجان الدائمة تكون
 * بسنوات، فيلزم تعديل الأعضاء من داخلها مع سجل يوضح التغييرات").
 * الصلاحيات تُفحص بالباك-إند لكل عملية؛ ظهور الأزرار يتبع /capabilities.
 */

function fullName(u: CommitteeMemberUser | null | undefined): string {
  return u ? `${u.first_name} ${u.last_name}` : '—'
}

/** جملة عربية تصف تغييرًا واحدًا بالسجل. */
function describeChange(c: CommitteeChange): { icon: React.ReactNode; text: string } {
  switch (c.change_type) {
    case 'member_added':
      return { icon: <UserPlus size={14} />, text: `إضافة ${fullName(c.subject_user)} عضوًا في اللجنة` }
    case 'member_removed':
      return {
        icon: <UserMinus size={14} />,
        text: `حذف ${fullName(c.subject_user)} من اللجنة${c.details.was_secretary ? ' (كان أمين السر)' : ''}`,
      }
    case 'chair_changed':
      return {
        icon: <Crown size={14} />,
        text: c.previous_user
          ? `تغيير رئيس اللجنة من ${fullName(c.previous_user)} إلى ${fullName(c.subject_user)}`
          : `تعيين ${fullName(c.subject_user)} رئيسًا للجنة`,
      }
    case 'secretary_changed':
      if (!c.subject_user) return { icon: <NotebookPen size={14} />, text: `إلغاء تعيين ${fullName(c.previous_user)} أمينًا للسر` }
      return {
        icon: <NotebookPen size={14} />,
        text: c.previous_user
          ? `تغيير أمين السر من ${fullName(c.previous_user)} إلى ${fullName(c.subject_user)}`
          : `تعيين ${fullName(c.subject_user)} أمينًا للسر`,
      }
    case 'period_extended':
      return {
        icon: <CalendarPlus size={14} />,
        text: `تمديد فترة اللجنة من ${formatDate(c.details.previous_end_date ?? null)} إلى ${formatDate(c.details.new_end_date ?? null)}`,
      }
  }
}

/** بطاقة "سجل التغييرات" — الأحدث أولًا. */
export function CommitteeHistoryCard({ committeeId }: { committeeId: string }) {
  const { data: changes, isLoading, isError } = useCommitteeChanges(committeeId)

  return (
    <Card className="p-0">
      <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
          <History size={15} />
          سجل تغييرات اللجنة
        </h2>
        {changes && changes.length > 0 && <span className="text-xs text-text-muted">{changes.length} تغيير</span>}
      </div>
      {isLoading ? (
        <div className="p-4">
          <TableSkeleton />
        </div>
      ) : isError ? (
        <p className="p-4 text-center text-sm text-text-muted">تعذّر تحميل سجل التغييرات</p>
      ) : !changes || changes.length === 0 ? (
        <EmptyState
          icon={<History size={22} />}
          title="لا توجد تغييرات بعد"
          description="أي إضافة أو حذف عضو أو تغيير الرئيس/الأمين أو تمديد يظهر هنا"
        />
      ) : (
        <ul>
          {changes.map((c) => {
            const { icon, text } = describeChange(c)
            return (
              <li key={c.change_id} className="flex gap-3 border-b border-border-default px-4 py-3 last:border-0">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-primary/10 text-brand-primary">
                  {icon}
                </span>
                <div className="flex flex-col gap-0.5">
                  <p className="text-sm text-text-primary">{text}</p>
                  {c.reason && <p className="text-xs text-text-secondary">السبب: {c.reason}</p>}
                  <p className="text-xs text-text-muted">
                    بواسطة {fullName(c.changed_by_user)} · {formatDateTime(c.created_at)}
                  </p>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

/** نافذة تمديد فترة اللجنة — النهاية الجديدة لازم بعد الحالية. */
export function ExtendCommitteeModal({
  open,
  onClose,
  committee,
  onSubmit,
  loading,
  serverError,
}: {
  open: boolean
  onClose: () => void
  committee: Committee
  onSubmit: (values: { endDate: string; reason?: string }) => void
  loading?: boolean
  serverError?: string | null
}) {
  const [endDate, setEndDate] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setEndDate('')
      setReason('')
      setError(null)
    }
  }, [open])

  function submit() {
    if (!endDate) return setError('اختر تاريخ النهاية الجديد')
    if (committee.end_date && endDate <= committee.end_date) {
      return setError('تاريخ النهاية الجديد لازم يكون بعد النهاية الحالية')
    }
    setError(null)
    onSubmit({ endDate, reason: reason.trim() || undefined })
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="تمديد مدة اللجنة"
      description={`النهاية الحالية: ${formatDate(committee.end_date)}`}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button onClick={submit} loading={loading} icon={<Save size={16} />}>
            تمديد
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <DateField
          label="تاريخ النهاية الجديد"
          required
          value={endDate}
          onChange={setEndDate}
          min={committee.end_date ?? undefined}
          error={error ?? undefined}
        />
        <Input label="السبب" placeholder="اختياري — يظهر بسجل التغييرات" value={reason} onChange={(e) => setReason(e.target.value)} />
        {serverError && (
          <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
            {serverError}
          </p>
        )}
      </div>
    </Modal>
  )
}

/** نافذة إضافة عضو للجنة الدائمة — من المستخدمين النشطين غير الأعضاء. */
export function AddCommitteeMemberModal({
  open,
  onClose,
  committeeId,
  onSubmit,
  loading,
  serverError,
}: {
  open: boolean
  onClose: () => void
  committeeId: string
  onSubmit: (values: { userId: string; reason?: string }) => void
  loading?: boolean
  serverError?: string | null
}) {
  const { data: candidates, isLoading } = useCommitteeMemberCandidates(committeeId, { enabled: open })
  const [userId, setUserId] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setUserId('')
      setReason('')
      setError(null)
    }
  }, [open])

  const options = (candidates ?? []).map((u) => ({
    value: u.user_id,
    label: [`${u.first_name} ${u.last_name}`, u.department, u.job_title].filter(Boolean).join(' — '),
  }))

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="إضافة عضو للجنة"
      description="يُضاف بدور عضو، ويُسجَّل بسجل تغييرات اللجنة"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button
            onClick={() => {
              if (!userId) return setError('اختر العضو')
              setError(null)
              onSubmit({ userId, reason: reason.trim() || undefined })
            }}
            loading={loading}
            icon={<UserPlus size={16} />}
          >
            إضافة
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Select
          label="العضو"
          required
          placeholder={isLoading ? 'جارِ التحميل...' : 'اختر العضو'}
          options={options}
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          error={error ?? undefined}
        />
        <Input label="السبب" placeholder="اختياري — يظهر بسجل التغييرات" value={reason} onChange={(e) => setReason(e.target.value)} />
        {serverError && (
          <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
            {serverError}
          </p>
        )}
      </div>
    </Modal>
  )
}
