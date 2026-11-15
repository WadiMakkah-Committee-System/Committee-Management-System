import { useLayoutEffect, useRef } from 'react'
import { cn } from '@/lib/utils'

/**
 * الهدف:
 * نص داخل المحضر يُعدَّل في مكانه (مثل الوورد) — يبدو كنص المستند نفسه، ويظهر
 * إطار خفيف عند المرور والتركيز فقط.
 *
 * المدخلات:
 * - value / onChange: القيمة الحالية ودالة التعديل.
 * - editable: false ⇒ نص عادي فقط.
 * - multiline: سطر واحد (input) أو عدة أسطر يكبر ارتفاعها تلقائيًا (textarea).
 * - sync: "auto" ⇒ خانة تتعبّأ تلقائيًا من الاجتماع ولم تُعدَّل بعد (تلميح منقّط)،
 *   "locked" ⇒ عُدّلت يدويًا فثبتت (لا تتغير بالمزامنة)، undefined ⇒ يدوية.
 * - ariaLabel: وصف الخانة لقارئ الشاشة (إلزامي عمليًا لأن الخانة بلا عنوان ظاهر).
 * - fit: سطر واحد بعرض محتواه (مثل "القرار (1-6-2025)") بدل عرض السطر كاملًا.
 *
 * الإطار عند المرور/التركيز معرّف في index.css (.minutes-inline) لا بأصناف
 * Tailwind، لأن قاعدة الحدود العامة (* { border-color }) خارج طبقات Tailwind
 * فتغلب أصناف الحدود الشفافة وتُظهر إطارًا دائمًا.
 */

interface InlineTextProps {
  value: string
  onChange?: (value: string) => void
  editable: boolean
  multiline?: boolean
  placeholder?: string
  className?: string
  ariaLabel: string
  sync?: 'auto' | 'locked'
  onFocus?: () => void
  align?: 'right' | 'center' | 'left'
  fit?: boolean
}

const SYNC_TITLE = {
  auto: 'تتعبّأ تلقائيًا من بيانات الاجتماع إلى أن تعدّلها',
  locked: 'عُدّلت يدويًا — لن تتغير تلقائيًا',
} as const

export function InlineText({
  value,
  onChange,
  editable,
  multiline,
  placeholder,
  className,
  ariaLabel,
  sync,
  onFocus,
  align = 'right',
  fit,
}: InlineTextProps) {
  const areaRef = useRef<HTMLTextAreaElement>(null)

  // ارتفاع textarea يتبع المحتوى (بدل شريط تمرير داخل المستند).
  useLayoutEffect(() => {
    const el = areaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [value, multiline, editable])

  const alignClass = align === 'center' ? 'text-center' : align === 'left' ? 'text-left' : 'text-right'

  if (!editable) {
    return <span className={cn('whitespace-pre-line', alignClass, className)}>{value}</span>
  }

  const shared = {
    'aria-label': ariaLabel,
    title: sync ? SYNC_TITLE[sync] : undefined,
    placeholder,
    onFocus,
    className: cn(
      'minutes-inline rounded-xs bg-transparent px-0.5 text-inherit outline-none transition-colors',
      // fit: عرض الحقل الذاتي صفر (لا يكبّر الخلية)، ويملأ عرض النص المخفي (min-w-full).
      fit ? 'w-0 min-w-full' : 'w-full min-w-0',
      sync === 'auto' && 'minutes-inline-auto',
      alignClass,
      className,
    ),
  }

  if (multiline) {
    return (
      <textarea
        ref={areaRef}
        rows={1}
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        {...shared}
        className={cn(shared.className, 'block resize-none overflow-hidden')}
      />
    )
  }
  const input = (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
      {...shared}
    />
  )
  if (!fit) return input
  // عرض بقدر النص: نص مخفي بنفس الخلية يحدد العرض، والحقل يملأها (يعمل بكل المتصفحات،
  // بخلاف خاصية size اللي تعتمد متوسط عرض حروف الخط فتطلع أعرض من اللازم بالعربي).
  return (
    <span className="inline-grid max-w-full align-baseline">
      <span aria-hidden className="invisible col-start-1 row-start-1 whitespace-pre px-1.5">
        {value || placeholder || '\u00a0'}
      </span>
      <span className="col-start-1 row-start-1 grid">{input}</span>
    </span>
  )
}
