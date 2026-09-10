import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import wadiMakkahMark from '@/assets/wadi-makkah-mark.png'

const SESSION_KEY = 'wm-splash-shown'

/**
 * شاشة افتتاحية (Splash Screen) — تظهر مرة واحدة فقط لكل جلسة متصفح
 * (sessionStorage، وليس مرة واحدة للأبد — علامة تبويب/زيارة جديدة تشوفها
 * من جديد، طلب صريح: "يظهر مباشرة عند فتح الموقع لأول مرة"). طبقة عرض
 * بحتة (Overlay بـposition:fixed فوق كل شيء) — لا تلمس منطق التوجيه أو
 * صفحة تسجيل الدخول إطلاقًا؛ ما تحتها (App الفعلي) يبدأ برندره فورًا
 * خلفها، وتُكشَف عنه فقط بالتلاشي، بدل انتظاره.
 *
 * التصميم (طلب صريح من صاحبة المشروع 2026-09-09 — Corporate/Elegant/
 * Minimal، بلا Gradient مبالغ فيه ولا Glassmorphism ولا Neon):
 * - خلفية اللون الأساسي لهوية وادي مكة (--brand-primary) فقط، بلا تدرّج.
 * - الشعار الرسمي كما هو (wadi-makkah-mark.png) — بلا إعادة رسم أو تلوين.
 * - حركة واحدة هادئة: Fade+Scale خفيف عند الدخول (لا دوران، لا Bounce)،
 *   ثبات قصير، ثم Fade بسيط عند الخروج (بلا Scale) — بالضبط تسلسل الخطوات
 *   المطلوب. المدة الإجمالية من الظهور حتى الاختفاء الكامل ~1.5 ثانية.
 * - يحترم prefers-reduced-motion (يقصّر المدد ويلغي التحجيم لمن يفضّل
 *   حركة أقل، دون حذف الشاشة نفسها).
 */
const TIMING = {
  logoEnterMs: 550,
  logoHoldMs: 550,
  logoExitMs: 320,
  screenExitMs: 380,
}

const REDUCED_TIMING = {
  logoEnterMs: 180,
  logoHoldMs: 300,
  logoExitMs: 160,
  screenExitMs: 200,
}

export function SplashScreen({ children }: { children: ReactNode }) {
  const prefersReducedMotion = useMemo(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
    [],
  )
  const timing = prefersReducedMotion ? REDUCED_TIMING : TIMING

  const [visible, setVisible] = useState(() => {
    if (typeof window === 'undefined') return false
    return !window.sessionStorage.getItem(SESSION_KEY)
  })
  const [logoVisible, setLogoVisible] = useState(true)

  useEffect(() => {
    if (!visible) return
    window.sessionStorage.setItem(SESSION_KEY, '1')

    const hideLogoTimer = window.setTimeout(
      () => setLogoVisible(false),
      timing.logoEnterMs + timing.logoHoldMs,
    )
    const hideScreenTimer = window.setTimeout(
      () => setVisible(false),
      timing.logoEnterMs + timing.logoHoldMs + timing.logoExitMs,
    )

    return () => {
      window.clearTimeout(hideLogoTimer)
      window.clearTimeout(hideScreenTimer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible])

  const logoVariants = {
    hidden: { opacity: 0, scale: prefersReducedMotion ? 1 : 0.92 },
    visible: {
      opacity: 1,
      scale: 1,
      transition: { duration: timing.logoEnterMs / 1000, ease: [0.16, 1, 0.3, 1] as const },
    },
    exit: {
      opacity: 0,
      transition: { duration: timing.logoExitMs / 1000, ease: 'easeInOut' as const },
    },
  }

  return (
    <>
      {children}
      <AnimatePresence>
        {visible && (
          <motion.div
            key="splash-screen"
            initial={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: timing.screenExitMs / 1000, ease: 'easeInOut' }}
            className="fixed inset-0 z-[100] flex items-center justify-center bg-brand-primary"
            role="presentation"
            aria-hidden="true"
            data-testid="splash-screen"
          >
            <AnimatePresence>
              {logoVisible && (
                <motion.img
                  key="splash-logo"
                  src={wadiMakkahMark}
                  alt=""
                  variants={logoVariants}
                  initial="hidden"
                  animate="visible"
                  exit="exit"
                  className="h-20 w-auto px-6 sm:h-24 md:h-28"
                  draggable={false}
                />
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
