import { useEffect, useState } from 'react'
import { Save } from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import type { CommitteeMemberUser, DecisionClassification, MeetingExtractedItem } from '@/types'
import type { AssignAsDecisionPayload, AssignAsTaskPayload } from '@/api/meetingExtractedItems'

/**
 * "تعيين بند" (FR-TASK-010/011 + FR-DEC-004، UC7/UC8) — نافذة واحدة
 * لخطوتي "تصنيف البند" (مهمة/قرار) و"إدخال بياناته"، بدل شاشتين
 * منفصلتين. العنوان معبَّأ مسبقًا من نص البند (قابل للتعديل) — بقية
 * الحقول (التواريخ/المسؤول/التصنيف) تُدخَل يدويًا من رئيس اللجنة دائمًا
 * (لا يقترحها الذكاء الاصطناعي — راجعي رأس app/models/meeting_extracted_item.py).
 */

interface AssignExtractedItemModalProps {
  open: boolean
  onClose: () => void
  item: MeetingExtractedItem | null
  committeeMembers: CommitteeMemberUser[]
  onSubmitTask: (payload: AssignAsTaskPayload) => void
  onSubmitDecision: (payload: AssignAsDecisionPayload) => void
  loading?: boolean
  serverError?: string | null
}

const CLASSIFICATION_OPTIONS: { value: DecisionClassification; label: string; hint: string }[] = [
  { value: 'final', label: 'قرار نهائي', hint: 'يُعتمد مباشرة بدون تصويت' },
  { value: 'voting', label: 'خاضع للتصويت', hint: 'يُطرح لتصويت أعضاء اللجنة' },
]

export function AssignExtractedItemModal({
  open,
  onClose,
  item,
  committeeMembers,
  onSubmitTask,
  onSubmitDecision,
  loading,
  serverError,
}: AssignExtractedItemModalProps) {
  const [type, setType] = useState<'task' | 'decision'>('task')
  const [title, setTitle] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [assigneeId, setAssigneeId] = useState('')
  const [classification, setClassification] = useState<DecisionClassification>('final')
  const [formError, setFormError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setType('task')
      setTitle(item?.text ?? '')
      setStartDate('')
      setEndDate('')
      setAssigneeId('')
      setClassification('final')
      setFormError(null)
    }
  }, [open, item])

  function submit() {
    if (!title.trim()) {
      setFormError('العنوان مطلوب')
      return
    }
    if (!startDate || !endDate) {
      setFormError('التواريخ مطلوبة')
      return
    }
    if (endDate < startDate) {
      setFormError('تاريخ النهاية يجب أن يكون بعد تاريخ البداية أو يساويه')
      return
    }
    if (type === 'task') {
      if (!assigneeId) {
        setFormError('يجب اختيار المسؤول')
        return
      }
      setFormError(null)
      onSubmitTask({
        title: title.trim(),
        start_date: startDate,
        end_date: endDate,
        assignee_user_id: assigneeId,
      })
    } else {
      setFormError(null)
      onSubmitDecision({
        title: title.trim(),
        classification,
        start_date: startDate,
        end_date: endDate,
      })
    }
  }

  const memberOptions = committeeMembers.map((m) => ({
    value: m.user_id,
    label: `${m.first_name} ${m.last_name}`,
  }))

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="تعيين البند"
      description={item ? `تحويل البند: "${item.text}"` : undefined}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            إلغاء
          </Button>
          <Button type="button" onClick={submit} loading={loading} icon={<Save size={16} />}>
            {type === 'task' ? 'إنشاء المهمة' : 'إنشاء القرار'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-text-primary">
            نوع البند<span className="text-danger"> *</span>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => setType('task')}
              className={cn(
                'rounded-sm border p-3 text-sm font-medium transition-colors',
                type === 'task'
                  ? 'border-brand-primary bg-brand-primary/5 text-text-primary'
                  : 'border-border-default text-text-muted hover:bg-bg-elevated',
              )}
            >
              مهمة
            </button>
            <button
              type="button"
              onClick={() => setType('decision')}
              className={cn(
                'rounded-sm border p-3 text-sm font-medium transition-colors',
                type === 'decision'
                  ? 'border-brand-primary bg-brand-primary/5 text-text-primary'
                  : 'border-border-default text-text-muted hover:bg-bg-elevated',
              )}
            >
              قرار
            </button>
          </div>
        </div>

        <Input
          label="العنوان"
          required
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="عنوان المهمة أو القرار"
        />

        {type === 'task' ? (
          <Select
            label="المسؤول"
            required
            placeholder="اختاري المسؤول"
            options={memberOptions}
            value={assigneeId}
            onChange={(e) => setAssigneeId(e.target.value)}
          />
        ) : (
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-text-primary">
              تصنيف القرار<span className="text-danger"> *</span>
            </label>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {CLASSIFICATION_OPTIONS.map((opt) => (
                <label
                  key={opt.value}
                  className={cn(
                    'flex cursor-pointer flex-col gap-0.5 rounded-sm border p-3 text-sm transition-colors',
                    classification === opt.value
                      ? 'border-brand-primary bg-brand-primary/5'
                      : 'border-border-default hover:bg-bg-elevated',
                  )}
                >
                  <span className="flex items-center gap-2 font-medium text-text-primary">
                    <input
                      type="radio"
                      checked={classification === opt.value}
                      onChange={() => setClassification(opt.value)}
                      className="h-4 w-4 text-brand-primary focus:ring-brand-accent/40"
                    />
                    {opt.label}
                  </span>
                  <span className="pr-6 text-xs text-text-muted">{opt.hint}</span>
                </label>
              ))}
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input
            type="date"
            label="تاريخ البداية"
            required
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
          <Input
            type="date"
            label="تاريخ النهاية"
            required
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
          />
        </div>

        {(formError || serverError) && (
          <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
            {formError || serverError}
          </p>
        )}
      </div>
    </Modal>
  )
}
