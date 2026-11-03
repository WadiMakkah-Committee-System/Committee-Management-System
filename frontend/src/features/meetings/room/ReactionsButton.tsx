import { useEffect, useRef, useState } from 'react'
import type { Reaction } from '@azure/communication-calling'
import { SmilePlus } from 'lucide-react'
import { cn } from '@/lib/utils'
import { REACTION_EMOJI } from './reactions'

const ORDER: Reaction[] = ['like', 'applause', 'heart', 'laugh', 'surprised']
const LABELS: Record<Reaction, string> = {
  like: 'إعجاب',
  applause: 'تصفيق',
  heart: 'قلب',
  laugh: 'ضحك',
  surprised: 'تفاجؤ',
}

/**
 * زر التفاعلات بشريط التحكم (قرار لاما 2026-11-03): قائمة صغيرة فيها 👍👏❤️😂😮،
 * والتفاعل يطير فوق فيديوي عند الكل — بما فيهم اللي بتطبيق Teams (ميزة Teams نفسها).
 */
export function ReactionsButton({ onReact }: { onReact: (type: Reaction) => void }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="تفاعل"
        title="تفاعل"
        className={cn(
          'flex h-11 w-11 items-center justify-center rounded-full transition-all active:scale-95',
          open ? 'bg-white/20 text-white' : 'bg-white/10 text-white hover:bg-white/20',
        )}
      >
        <SmilePlus size={18} />
      </button>
      {open && (
        <div className="absolute bottom-14 left-1/2 z-10 flex -translate-x-1/2 gap-1 rounded-full bg-[#1b2338] p-1.5 shadow-xl ring-1 ring-white/10">
          {ORDER.map((type) => (
            <button
              key={type}
              type="button"
              title={LABELS[type]}
              onClick={() => {
                onReact(type)
                setOpen(false)
              }}
              className="flex h-10 w-10 items-center justify-center rounded-full text-2xl transition-transform hover:scale-125 hover:bg-white/10"
            >
              {REACTION_EMOJI[type]}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
