import { useEffect, useRef, useState, type ReactNode } from 'react'
import { animate, motion, useReducedMotion, type Variants } from 'framer-motion'
import { cn } from '@/lib/utils'

/**
 * أدوات حركة موحّدة للنظام — مستوحاة من أسلوب المواقع المرجعية (كشف النص
 * كلمة بكلمة مثل SplitText، وظهور متتابع Stagger)، لكن مبنية على
 * framer-motion الموجودة أصلًا بالمشروع (بلا مكتبة إضافية تزيد حجم الحزمة).
 * كل الحركات قصيرة (≤ 0.7 ثانية) وتُعطَّل تلقائيًا مع "تقليل الحركة".
 */

export const EASE_OUT_EXPO = [0.16, 1, 0.3, 1] as const

/** كشف نص كلمة بكلمة — صعود ناعم مع زوال ضبابية خفيفة. */
export function SplitWords({
  text,
  className,
  wordClassName,
  delay = 0,
  stagger = 0.06,
}: {
  text: string
  className?: string
  /** صنف يُطبَّق على كل كلمة (مثل تدرّج لوني بـbg-clip-text — يجب أن يكون على الكلمة نفسها). */
  wordClassName?: string
  delay?: number
  stagger?: number
}) {
  const reduce = useReducedMotion()
  const words = text.split(/\s+/).filter(Boolean)
  if (reduce) return <span className={className}>{text}</span>

  return (
    <span className={cn('inline-block', className)} aria-label={text}>
      {words.map((w, i) => (
        <span key={`${w}-${i}`} aria-hidden className="inline-block overflow-hidden pb-[0.12em] align-bottom">
          <motion.span
            className={cn('inline-block', wordClassName)}
            initial={{ y: '105%', opacity: 0, filter: 'blur(6px)' }}
            animate={{ y: '0%', opacity: 1, filter: 'blur(0px)' }}
            transition={{ duration: 0.7, delay: delay + i * stagger, ease: EASE_OUT_EXPO }}
          >
            {w}
          </motion.span>
          {i < words.length - 1 && ' '}
        </span>
      ))}
    </span>
  )
}

const containerVariants: Variants = {
  hidden: {},
  show: (stagger: number = 0.06) => ({ transition: { staggerChildren: stagger, delayChildren: 0.04 } }),
}

export const itemVariants: Variants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: EASE_OUT_EXPO } },
}

/** حاوية ظهور متتابع — ضعي عناصر <StaggerItem> بداخلها. */
export function Stagger({
  children,
  className,
  stagger = 0.06,
}: {
  children: ReactNode
  className?: string
  stagger?: number
}) {
  return (
    <motion.div className={className} variants={containerVariants} custom={stagger} initial="hidden" animate="show">
      {children}
    </motion.div>
  )
}

export function StaggerItem({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div className={className} variants={itemVariants}>
      {children}
    </motion.div>
  )
}

/** عدّاد رقمي يتصاعد من 0 للقيمة عند أول ظهور (مرة واحدة لكل قيمة). */
const SKIP_COUNT_ANIMATION = import.meta.env.MODE === 'test'

export function CountUp({ value, duration = 1.1 }: { value: number; duration?: number }) {
  const reduce = useReducedMotion()
  const skip = reduce || SKIP_COUNT_ANIMATION
  const [display, setDisplay] = useState(skip ? value : 0)
  const fromRef = useRef(0)

  useEffect(() => {
    if (skip) {
      setDisplay(value)
      return
    }
    const controls = animate(fromRef.current, value, {
      duration,
      ease: EASE_OUT_EXPO,
      onUpdate: (v) => setDisplay(Math.round(v)),
    })
    fromRef.current = value
    return () => controls.stop()
  }, [value, skip, duration])

  return <span className="tabular-nums">{display}</span>
}
