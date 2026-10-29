import { useEffect, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { BrandWave } from './BrandWave'
import wadiMakkahMark from '@/assets/wadi-makkah-mark.png'

/**
 * الشاشة الافتتاحية — تظهر مرة واحدة لكل جلسة متصفح قبل صفحة تسجيل
 * الدخول (مستوحاة من افتتاحية عرض المنصة): خلفية كحلية، موجات هوية
 * شفافة تنساب بالخلف، شعار الموجة ينكشف من المنتصف للأطراف، ثم اسم
 * "وادي مكة" يظهر بنعومة. مدتها ~3 ثوانٍ، وتُتخطّى بنقرة أو أي زر،
 * وتُلغى كليًا مع "تقليل الحركة".
 */

const EASE = [0.16, 1, 0.3, 1] as const
const TOTAL_MS = 3100
const STORAGE_KEY = 'wm-intro-seen'

export function shouldShowIntro(): boolean {
  if (import.meta.env.MODE === 'test') return false
  try {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false
    return sessionStorage.getItem(STORAGE_KEY) !== '1'
  } catch {
    return false
  }
}

export function IntroSplash({ onLeave, onDone }: { onLeave?: () => void; onDone: () => void }) {
  const reduce = useReducedMotion()
  const [leaving, setLeaving] = useState(false)

  // لحظة بدء الخروج: نُعلم التطبيق ليعرض صفحة الدخول تحت الشاشة الافتتاحية
  // فتظهر حركتها الخاصة أثناء تلاشي الافتتاحية (انتقال متداخل سلس).
  useEffect(() => {
    if (leaving) onLeave?.()
  }, [leaving, onLeave])

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, '1')
    } catch {
      /* تجاهل — التخزين غير متاح */
    }
    const t = window.setTimeout(() => setLeaving(true), reduce ? 0 : TOTAL_MS)
    const skip = () => setLeaving(true)
    window.addEventListener('keydown', skip)
    return () => {
      window.clearTimeout(t)
      window.removeEventListener('keydown', skip)
    }
  }, [reduce])

  return (
    <motion.div
      role="presentation"
      aria-label="وادي مكة للتقنية"
      onClick={() => setLeaving(true)}
      initial={{ opacity: 1 }}
      animate={leaving ? { opacity: 0, scale: 1.04, filter: 'blur(8px)' } : { opacity: 1, scale: 1, filter: 'blur(0px)' }}
      transition={{ duration: leaving ? 0.7 : 0, ease: EASE }}
      onAnimationComplete={() => leaving && onDone()}
      className="fixed inset-0 z-[200] flex cursor-pointer select-none flex-col items-center justify-center overflow-hidden bg-[radial-gradient(ellipse_at_center,#12224a_0%,#0b1530_55%,#070e22_100%)]"
    >
      {/* موجات الخلفية الشفافة */}
      <motion.div
        aria-hidden
        initial={{ opacity: 0, scaleY: 0.2 }}
        animate={{ opacity: 0.35, scaleY: 1 }}
        transition={{ duration: 1.6, ease: EASE }}
        className="pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2"
      >
        <BrandWave height={220} speed={1.6} />
      </motion.div>
      <motion.div
        aria-hidden
        initial={{ opacity: 0 }}
        animate={{ opacity: 0.18 }}
        transition={{ duration: 2, delay: 0.3 }}
        className="pointer-events-none absolute inset-x-0 top-1/2 -translate-y-[40%] -scale-x-100"
      >
        <BrandWave height={160} palette="cool" speed={1.2} />
      </motion.div>

      {/* شعار الموجة — ينكشف من المنتصف للأطراف */}
      <motion.img
        src={wadiMakkahMark}
        alt=""
        initial={{ clipPath: 'inset(0 50% 0 50%)', scale: 0.92, opacity: 0.6 }}
        animate={{ clipPath: 'inset(0 0% 0 0%)', scale: 1, opacity: 1 }}
        transition={{ duration: 1.2, delay: 0.25, ease: EASE }}
        className="relative w-[min(62vw,300px)] drop-shadow-[0_10px_40px_rgba(36,186,233,0.25)]"
      />

      {/* اسم الشركة */}
      <div className="relative mt-6 flex flex-col items-center leading-none" dir="rtl">
        <motion.p
          initial={{ opacity: 0, y: 14, filter: 'blur(10px)' }}
          animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
          transition={{ duration: 0.9, delay: 1.05, ease: EASE }}
          className="text-5xl font-bold text-white sm:text-6xl"
        >
          وادي <span className="text-white">مكة</span>
        </motion.p>
        <motion.p
          dir="ltr"
          initial={{ opacity: 0, y: 8, letterSpacing: '0.4em' }}
          animate={{ opacity: 0.75, y: 0, letterSpacing: '0.08em' }}
          transition={{ duration: 1, delay: 1.3, ease: EASE }}
          className="mt-3 text-lg text-white sm:text-xl"
        >
          Wadi <span className="font-bold">Makkah</span>
        </motion.p>
      </div>

      {/* شريط الطيف يمتد أسفل الاسم */}
      <motion.div
        aria-hidden
        initial={{ scaleX: 0, opacity: 0 }}
        animate={{ scaleX: 1, opacity: 1 }}
        transition={{ duration: 1.1, delay: 1.6, ease: EASE }}
        className="brand-stripe relative mt-7 h-[2px] w-40 rounded-full"
      />

      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 0.45 }}
        transition={{ duration: 0.6, delay: 2 }}
        className="absolute bottom-8 text-xs text-white"
      >
        اضغط للتخطي
      </motion.p>
    </motion.div>
  )
}
