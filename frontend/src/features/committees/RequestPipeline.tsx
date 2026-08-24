import { Fragment } from 'react'
import { motion } from 'framer-motion'
import {
  Briefcase,
  CheckCircle2,
  Crown,
  Flag,
  Send,
  Undo2,
  Workflow,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { CommitteeRequestStatus } from '@/types'

type StepTone = 'complete' | 'current' | 'upcoming' | 'warning' | 'success' | 'danger'

interface PipelineStep {
  key: string
  label: string
  party: string
  icon: LucideIcon
  tone: StepTone
  note?: string
}

const TONE_NODE_CLASSES: Record<StepTone, string> = {
  complete: 'border-brand-primary bg-brand-primary text-white',
  current: 'border-brand-primary bg-bg-surface text-brand-primary',
  upcoming: 'border-border-default bg-bg-surface text-text-muted',
  warning: 'border-warning bg-warning-bg text-warning',
  success: 'border-success bg-success text-white',
  danger: 'border-danger bg-danger text-white',
}

const TONE_RING_CLASSES: Record<StepTone, string> = {
  complete: '',
  current: 'ring-brand-primary/35',
  upcoming: '',
  warning: 'ring-warning/35',
  success: '',
  danger: '',
}

const TONE_LABEL_CLASSES: Record<StepTone, string> = {
  complete: 'text-text-primary',
  current: 'text-brand-primary',
  upcoming: 'text-text-muted',
  warning: 'text-warning',
  success: 'text-success',
  danger: 'text-danger',
}

const TONE_NOTE_CLASSES: Record<StepTone, string> = {
  complete: 'text-text-muted',
  current: 'text-brand-primary',
  upcoming: 'text-text-muted',
  warning: 'text-warning',
  success: 'text-success',
  danger: 'text-danger',
}

/**
 * يبني مراحل الـ Pipeline الأربع من حالة الطلب الفعلية القادمة من
 * الباك-إند (CommitteeRequestStatus بالضبط، دون أي حالة مُختلَقة). يُبسّط
 * 7 حالات الباك-إند الى 4 مراحل مرئية لأن "under_review" و"submitted"
 * كلاهما فعليًا "الطلب لدى المكتب التنفيذي" — الفرق الوحيد بينهما أن
 * under_review لا تُصل إليها الحالة إلا عبر إرجاع الرئيس التنفيذي
 * (return_to_office_request بالباك-إند)، وليست مرحلة أولى مستقلة. راجعي
 * project_memory: phase2-committee-formation-requests.md لآلة الحالة
 * الكاملة قبل تعديل هذا التبسيط.
 *
 * "returned" (إرجاع المكتب التنفيذي لمقدّم الطلب) تُعامَل بصريًا كرجوع
 * لمرحلة الإرسال (تنبيه/warning) لا كمرحلة خامسة منفصلة — لأن الإجراء
 * التالي المطلوب فعليًا هو إعادة الإرسال (submit_request) تمامًا كما لو
 * كانت مسودة، وهذا ما تعكسه القواعد الفعلية بـ committee_service.py
 * (isDraftLike = draft || returned بصفحة التفاصيل).
 */
function buildSteps(status: CommitteeRequestStatus, returnReason: string | null): PipelineStep[] {
  const submission: PipelineStep = { key: 'submit', label: 'إرسال الطلب', party: 'مقدّم الطلب', icon: Send, tone: 'upcoming' }
  const office: PipelineStep = {
    key: 'office',
    label: 'مراجعة المكتب التنفيذي',
    party: 'المكتب التنفيذي',
    icon: Briefcase,
    tone: 'upcoming',
  }
  const ceo: PipelineStep = { key: 'ceo', label: 'اعتماد الرئيس التنفيذي', party: 'الرئيس التنفيذي', icon: Crown, tone: 'upcoming' }
  const decision: PipelineStep = { key: 'decision', label: 'القرار النهائي', party: '', icon: Flag, tone: 'upcoming' }

  switch (status) {
    case 'draft':
      return [
        { ...submission, tone: 'current', note: 'لم يُرسَل بعد' },
        office,
        ceo,
        decision,
      ]
    case 'returned':
      return [
        { ...submission, tone: 'warning', note: 'أُعيد إليك من المكتب التنفيذي للتعديل' },
        office,
        ceo,
        decision,
      ]
    case 'submitted':
      return [
        { ...submission, tone: 'complete' },
        { ...office, tone: 'current' },
        ceo,
        decision,
      ]
    case 'under_review':
      return [
        { ...submission, tone: 'complete' },
        {
          ...office,
          tone: 'current',
          note: returnReason ? 'أعاده الرئيس التنفيذي لمراجعة إضافية' : undefined,
        },
        ceo,
        decision,
      ]
    case 'pending_approval':
      return [
        { ...submission, tone: 'complete' },
        { ...office, tone: 'complete' },
        { ...ceo, tone: 'current' },
        decision,
      ]
    case 'approved':
      return [
        { ...submission, tone: 'complete' },
        { ...office, tone: 'complete' },
        { ...ceo, tone: 'complete' },
        { ...decision, tone: 'success', label: 'اعتماد الطلب', icon: CheckCircle2 },
      ]
    case 'rejected':
      return [
        { ...submission, tone: 'complete' },
        { ...office, tone: 'complete' },
        { ...ceo, tone: 'complete' },
        { ...decision, tone: 'danger', label: 'رفض الطلب', icon: XCircle },
      ]
    default:
      return [submission, office, ceo, decision]
  }
}

function StepNode({ step, index }: { step: PipelineStep; index: number }) {
  const Icon = step.icon
  const isPulsing = step.tone === 'current' || step.tone === 'warning'

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: index * 0.06, ease: 'easeOut' }}
      className="flex flex-col items-center gap-2 text-center"
    >
      <div className="relative flex h-11 w-11 shrink-0 items-center justify-center">
        {isPulsing && (
          <motion.span
            className={cn('absolute inset-0 rounded-full ring-2', TONE_RING_CLASSES[step.tone])}
            animate={{ scale: [1, 1.5], opacity: [0.55, 0] }}
            transition={{ duration: 1.8, repeat: Infinity, ease: 'easeOut' }}
          />
        )}
        <div
          className={cn(
            'flex h-11 w-11 items-center justify-center rounded-full border-2 transition-colors duration-300',
            TONE_NODE_CLASSES[step.tone],
          )}
        >
          <Icon size={18} />
        </div>
      </div>
      <div className="flex max-w-[9rem] flex-col gap-0.5 sm:max-w-[8.5rem]">
        <p className={cn('text-xs font-semibold leading-tight sm:text-sm', TONE_LABEL_CLASSES[step.tone])}>
          {step.label}
        </p>
        {step.note ? (
          <p className={cn('flex items-center justify-center gap-1 text-[11px] leading-tight', TONE_NOTE_CLASSES[step.tone])}>
            <Undo2 size={11} className="shrink-0" />
            {step.note}
          </p>
        ) : step.party ? (
          <p className="text-[11px] leading-tight text-text-muted">{step.party}</p>
        ) : null}
      </div>
    </motion.div>
  )
}

function Connector({ filled }: { filled: boolean }) {
  return (
    // العلامة الرأسية 1.375rem = نصف ارتفاع دائرة الأيقونة (h-11 = 2.75rem)
    // بالضبط، لمحاذاة الخط أفقيًا في منتصف الدائرة بغضّ النظر عن عدد أسطر
    // تسمية كل مرحلة (بعضها يلتف لسطرين والآخر لسطر واحد).
    <div className="mt-[1.375rem] h-0.5 flex-1 overflow-hidden rounded-full bg-border-default">
      <motion.div
        className="h-full bg-brand-primary"
        initial={false}
        animate={{ width: filled ? '100%' : '0%' }}
        transition={{ duration: 0.4, ease: 'easeOut' }}
      />
    </div>
  )
}

/**
 * Pipeline/Workflow حالة طلب تشكيل اللجنة — العنصر الذي طلبته Lama صراحةً
 * (مُعلَّم "مهم"): يُظهر المرحلة الحالية والسابقة والقادمة، وانتقال الطلب
 * بين مقدّم الطلب ← المكتب التنفيذي ← الرئيس التنفيذي، مبنيًا بالكامل من
 * status الفعلي القادم من الباك-إند دون أي بيانات وهمية. عرض أفقي على
 * الشاشات المتوسطة فأكبر، وعمودي على الجوال (RTL في الحالتين تلقائيًا عبر
 * اتجاه المستند).
 */
export function RequestPipeline({
  status,
  returnReason,
}: {
  status: CommitteeRequestStatus
  returnReason: string | null
}) {
  const steps = buildSteps(status, returnReason)

  return (
    <div className="rounded-md border border-border-default bg-bg-surface p-4 sm:p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
        <Workflow size={15} />
        مسار مراجعة واعتماد الطلب
      </h2>

      {/* Desktop / tablet: horizontal stepper */}
      <div className="mt-6 hidden items-start sm:flex" role="list" aria-label="مسار حالة طلب تشكيل اللجنة">
        {steps.map((step, i) => (
          <Fragment key={step.key}>
            <div role="listitem" className="flex-1">
              <StepNode step={step} index={i} />
            </div>
            {i < steps.length - 1 && <Connector filled={step.tone === 'complete'} />}
          </Fragment>
        ))}
      </div>

      {/* Mobile: vertical stepper */}
      <div className="mt-5 flex flex-col sm:hidden" role="list" aria-label="مسار حالة طلب تشكيل اللجنة">
        {steps.map((step, i) => {
          const Icon = step.icon
          const isPulsing = step.tone === 'current' || step.tone === 'warning'
          return (
            <div key={step.key} role="listitem" className="flex gap-3">
              <div className="flex flex-col items-center">
                <div className="relative flex h-9 w-9 shrink-0 items-center justify-center">
                  {isPulsing && (
                    <motion.span
                      className={cn('absolute inset-0 rounded-full ring-2', TONE_RING_CLASSES[step.tone])}
                      animate={{ scale: [1, 1.5], opacity: [0.55, 0] }}
                      transition={{ duration: 1.8, repeat: Infinity, ease: 'easeOut' }}
                    />
                  )}
                  <div
                    className={cn(
                      'flex h-9 w-9 items-center justify-center rounded-full border-2 transition-colors duration-300',
                      TONE_NODE_CLASSES[step.tone],
                    )}
                  >
                    <Icon size={15} />
                  </div>
                </div>
                {i < steps.length - 1 && (
                  <div className="my-1 w-0.5 flex-1 overflow-hidden rounded-full bg-border-default">
                    <motion.div
                      className="w-full bg-brand-primary"
                      initial={false}
                      animate={{ height: step.tone === 'complete' ? '100%' : '0%' }}
                      transition={{ duration: 0.4, ease: 'easeOut' }}
                      style={{ minHeight: step.tone === 'complete' ? '1.5rem' : 0 }}
                    />
                  </div>
                )}
              </div>
              <div className={cn('flex flex-1 flex-col gap-0.5', i < steps.length - 1 ? 'pb-5' : '')}>
                <p className={cn('text-sm font-semibold', TONE_LABEL_CLASSES[step.tone])}>{step.label}</p>
                {step.note ? (
                  <p className={cn('flex items-center gap-1 text-xs', TONE_NOTE_CLASSES[step.tone])}>
                    <Undo2 size={11} className="shrink-0" />
                    {step.note}
                  </p>
                ) : step.party ? (
                  <p className="text-xs text-text-muted">{step.party}</p>
                ) : null}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
