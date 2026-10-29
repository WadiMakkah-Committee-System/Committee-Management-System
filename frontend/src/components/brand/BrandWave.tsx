import { memo, useMemo } from 'react'
import { cn } from '@/lib/utils'

/**
 * موجة الهوية — إعادة رسم شرائط موجة شعار وادي مكة كـSVG خفيف بألوان
 * الهوية الحقيقية، مع انجراف أفقي بطيء جدًا (CSS transform فقط على GPU —
 * بلا JavaScript لكل إطار، وبلا أي مكتبة إضافية). كل شريط مرسوم بعرض
 * ضعف المساحة الظاهرة وبطول موجة يقسم العرض بالضبط، فيتكرر بلا قطع
 * عند تحريكه -50%. تتوقف الحركة تلقائيًا مع prefers-reduced-motion.
 */

interface Ribbon {
  color: string
  /** ارتفاع الموجة */
  amp: number
  /** عدد الموجات داخل عرض واحد (عدد صحيح للتكرار السلس) */
  waves: number
  phase: number
  /** سماكة الشريط القصوى */
  thickness: number
  opacity: number
  duration: number
}

const TILE = 1200

const PALETTES: Record<'full' | 'cool' | 'warm', Ribbon[]> = {
  full: [
    { color: '#24bae9', amp: 34, waves: 2, phase: 0.2, thickness: 26, opacity: 0.85, duration: 46 },
    { color: '#e9a625', amp: 48, waves: 1, phase: 1.4, thickness: 30, opacity: 0.9, duration: 58 },
    { color: '#9a559c', amp: 30, waves: 2, phase: 2.6, thickness: 22, opacity: 0.8, duration: 40 },
    { color: '#99c23e', amp: 26, waves: 3, phase: 0.9, thickness: 18, opacity: 0.8, duration: 52 },
    { color: '#2b3f90', amp: 22, waves: 2, phase: 3.6, thickness: 20, opacity: 0.85, duration: 36 },
    { color: '#018b85', amp: 28, waves: 1, phase: 4.4, thickness: 22, opacity: 0.8, duration: 64 },
    { color: '#105ea7', amp: 18, waves: 3, phase: 5.2, thickness: 16, opacity: 0.85, duration: 44 },
  ],
  cool: [
    { color: '#24bae9', amp: 34, waves: 2, phase: 0.2, thickness: 26, opacity: 0.7, duration: 46 },
    { color: '#105ea7', amp: 40, waves: 1, phase: 1.4, thickness: 28, opacity: 0.75, duration: 58 },
    { color: '#53519c', amp: 26, waves: 2, phase: 2.6, thickness: 20, opacity: 0.7, duration: 40 },
    { color: '#018b85', amp: 24, waves: 3, phase: 0.9, thickness: 18, opacity: 0.7, duration: 52 },
  ],
  warm: [
    { color: '#e9a625', amp: 40, waves: 1, phase: 1.4, thickness: 26, opacity: 0.8, duration: 58 },
    { color: '#facc12', amp: 26, waves: 2, phase: 0.4, thickness: 18, opacity: 0.7, duration: 44 },
    { color: '#9a559c', amp: 30, waves: 2, phase: 2.6, thickness: 20, opacity: 0.75, duration: 40 },
    { color: '#99c23e', amp: 22, waves: 3, phase: 0.9, thickness: 16, opacity: 0.7, duration: 52 },
  ],
}

function ribbonPath(r: Ribbon, cy: number): string {
  const k = (Math.PI * 2 * r.waves) / TILE
  const step = 24
  const top: string[] = []
  const bottom: string[] = []
  for (let x = 0; x <= TILE * 2; x += step) {
    const y = cy + r.amp * Math.sin(k * x + r.phase)
    // سماكة متغيّرة بنفس الدورة → شريط يضيق ويتسع مثل الشعار
    const t = 2 + r.thickness * (0.5 + 0.5 * Math.sin(k * x + r.phase + Math.PI / 2))
    top.push(`${x},${y.toFixed(1)}`)
    bottom.push(`${x},${(y + t).toFixed(1)}`)
  }
  return `M${top.join(' L')} L${bottom.reverse().join(' L')} Z`
}

export const BrandWave = memo(function BrandWave({
  className,
  palette = 'full',
  height = 160,
  speed = 1,
}: {
  className?: string
  palette?: keyof typeof PALETTES
  height?: number
  /** مُضاعِف سرعة الحركة (1 = الافتراضي الهادئ) */
  speed?: number
}) {
  const ribbons = PALETTES[palette]
  const cy = height / 2 - 12
  const paths = useMemo(() => ribbons.map((r) => ribbonPath(r, cy)), [ribbons, cy])

  return (
    <svg
      aria-hidden
      viewBox={`0 0 ${TILE} ${height}`}
      preserveAspectRatio="none"
      className={cn('pointer-events-none block w-full select-none', className)}
      style={{ height }}
    >
      {ribbons.map((r, i) => (
        <path
          key={i}
          d={paths[i]}
          fill={r.color}
          fillOpacity={r.opacity}
          className="wave-ribbon"
          style={{ ['--wave-duration' as string]: `${r.duration / speed}s` }}
        />
      ))}
    </svg>
  )
})

/** شريط الطيف الرفيع بألوان الهوية — يُستخدم أعلى الهيدر/البطاقات المميزة. */
export function BrandStripe({ className }: { className?: string }) {
  return <div aria-hidden className={cn('brand-stripe h-[3px] w-full', className)} />
}
