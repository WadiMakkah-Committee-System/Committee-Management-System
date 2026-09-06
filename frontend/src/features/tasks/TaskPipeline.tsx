import { Fragment } from 'react'
import { motion } from 'framer-motion'
import { CheckCircle2, ListTodo, PauseCircle, PlayCircle, Workflow, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { TaskStatus } from '@/types'

type StepTone = 'complete' | 'current' | 'upcoming' | 'warning' | 'success'

interface PipelineStep {
  key: string
  label: string
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
}

const TONE_RING_CLASSES: Record<StepTone, string> = {
  complete: '',
  current: 'ring-brand-primary/35',
  upcoming: '',
  warning: 'ring-warning/35',
  success: '',
}

const TONE_LABEL_CLASSES: Record<StepTone, string> = {
  complete: 'text-text-primary',
  current: 'text-brand-primary',
  upcoming: 'text-text-muted',
  warning: 'text-warning',
  success: 'text-success',
}

/**
 * يبسّط حالات المهمة الأربع (TaskStatus) لثلاث محطات مرئية: لم تبدأ ←
 * قيد التنفيذ ← مكتملة. "معلّقة" تُعامَل كتفريع تحذيري عن محطة "قيد
 * التنفيذ" نفسها (بدل محطة رابعة منفصلة) — بنفس مبدأ معاملة "returned"
 * كتفريع عن "إرسال الطلب" في RequestPipeline.tsx بوحدة طلبات تشكيل
 * اللجان؛ راجعي تعليق buildSteps هناك قبل تعديل هذا التبسيط.
 */
function buildSteps(status: TaskStatus): PipelineStep[] {
  const start: PipelineStep = { key: 'start', label: 'لم تبدأ', icon: ListTodo, tone: 'upcoming' }
  const progress: PipelineStep = { key: 'progress', label: 'قيد التنفيذ', icon: PlayCircle, tone: 'upcoming' }
  const done: PipelineStep = { key: 'done', label: 'مكتملة', icon: CheckCircle2, tone: 'upcoming' }

  switch (status) {
    case 'todo':
      return [{ ...start, tone: 'current', note: 'بانتظار البدء' }, progress, done]
    case 'in_progress':
      return [{ ...start, tone: 'complete' }, { ...progress, tone: 'current' }, done]
    case 'on_hold':
      return [
        { ...start, tone: 'complete' },
        { ...progress, tone: 'warning', icon: PauseCircle, note: 'معلّقة مؤقتًا' },
        done,
      ]
    case 'completed':
      return [{ ...start, tone: 'complete' }, { ...progress, tone: 'complete' }, { ...done, tone: 'success' }]
    default:
      return [start, progress, done]
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
      <div className="flex max-w-[8rem] flex-col gap-0.5">
        <p className={cn('text-xs font-semibold leading-tight sm:text-sm', TONE_LABEL_CLASSES[step.tone])}>
          {step.label}
        </p>
        {step.note && (
          <p className={cn('text-[11px] leading-tight', TONE_LABEL_CLASSES[step.tone])}>{step.note}</p>
        )}
      </div>
    </motion.div>
  )
}

function Connector({ filled }: { filled: boolean }) {
  return (
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
 * مسار حالة المهمة — العنصر اللي طلبَته Lujain صراحةً على غرار
 * RequestPipeline.tsx بوحدة طلبات تشكيل اللجان (نفس فكرة "الخط الأفقي
 * الزمني الملوّن"). يُبنى بالكامل من status الفعلي القادم من الباك-إند.
 */
export function TaskPipeline({ status }: { status: TaskStatus }) {
  const steps = buildSteps(status)

  return (
    <div className="rounded-md border border-border-default bg-bg-surface p-4 sm:p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
        <Workflow size={15} />
        مسار حالة المهمة
      </h2>

      <div className="mt-6 flex items-start" role="list" aria-label="مسار حالة المهمة">
        {steps.map((step, i) => (
          <Fragment key={step.key}>
            <div role="listitem" className="flex-1">
              <StepNode step={step} index={i} />
            </div>
            {i < steps.length - 1 && <Connector filled={step.tone === 'complete' || step.tone === 'success'} />}
          </Fragment>
        ))}
      </div>
    </div>
  )
}
