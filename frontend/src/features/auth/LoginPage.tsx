import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { CalendarDays, FileSignature, Gavel, ListChecks, LogIn, ShieldCheck, Sparkles } from 'lucide-react'
import * as authApi from '@/api/auth'
import * as usersApi from '@/api/users'
import { usersKeys } from '@/hooks/useUsers'
import { useAuthStore } from '@/store/authStore'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { extractErrorMessage } from '@/lib/utils'
import wadiMakkahMark from '@/assets/wadi-makkah-mark.png'
import { BrandWave } from '@/components/brand/BrandWave'
import { EASE_OUT_EXPO, SplitWords } from '@/components/motion/primitives'

const schema = z.object({
  username: z.string().min(1, 'اسم المستخدم مطلوب'),
  password: z.string().min(1, 'كلمة المرور مطلوبة'),
})

type FormValues = z.infer<typeof schema>

export function LoginPage() {
  const navigate = useNavigate()
  const setTokens = useAuthStore((s) => s.setTokens)
  const setUser = useAuthStore((s) => s.setUser)
  const queryClient = useQueryClient()
  const [serverError, setServerError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  const mutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const tokens = await authApi.login(values)
      setTokens(tokens.access_token, tokens.refresh_token)
      // تحسين أداء 2026-10-25: الباك-إند يرجّع بيانات المستخدم مع رد الدخول
      // نفسه (نفس شكل /users/me) — فلا ننتظر طلبًا ثانيًا متتابعًا. لو رجع
      // بدونها (نسخة باك-إند أقدم) نرجع للسلوك السابق.
      const me = tokens.user ?? (await usersApi.fetchMe())
      queryClient.setQueryData(usersKeys.me, me)
      setUser(me)
      return me
    },
    onSuccess: () => navigate('/users', { replace: true }),
    onError: (error) => setServerError(extractErrorMessage(error)),
  })

  return (
    <div className="relative flex min-h-svh bg-bg-app">
      {/* ===== لوحة الهوية (شاشات كبيرة) ===== */}
      <aside className="relative hidden w-[46%] max-w-[720px] flex-col justify-between overflow-hidden bg-[linear-gradient(160deg,#0b1633_0%,#122a63_55%,#105ea7_120%)] p-12 text-white lg:flex">
        <div aria-hidden className="bg-grid-soft absolute inset-0 opacity-[0.18]" />
        <div aria-hidden className="animate-float-soft absolute -top-24 -left-24 h-80 w-80 rounded-full bg-[var(--wm-cyan)] opacity-20 blur-3xl" />
        <div
          aria-hidden
          className="animate-float-soft absolute bottom-24 -right-16 h-72 w-72 rounded-full bg-[var(--wm-purple)] opacity-20 blur-3xl"
          style={{ animationDelay: '-4s' }}
        />

        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: EASE_OUT_EXPO }}
          className="relative flex items-center gap-3"
        >
          <div className="flex h-12 items-center rounded-sm bg-white px-2.5 shadow-lg">
            <img src={wadiMakkahMark} alt="شعار وادي مكة" className="h-9 w-auto" />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-bold">شركة وادي مكة للتقنية</p>
            <p className="text-xs text-white/60">Wadi Makkah Company For Technology</p>
          </div>
        </motion.div>

        <div className="relative">
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.6, delay: 0.15 }}
            className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs text-white/80 backdrop-blur"
          >
            <Sparkles size={14} className="text-[var(--wm-gold)]" />
            مدعوم بالذكاء الاصطناعي
          </motion.p>
          <h2 className="text-4xl font-bold leading-[1.35] xl:text-[2.75rem]">
            <SplitWords text="منصة ذكية لإدارة" delay={0.2} />
            <br />
            <SplitWords
              text="اللجان والاجتماعات"
              delay={0.38}
              wordClassName="bg-[linear-gradient(90deg,var(--wm-cyan),#8fdcf5_60%,var(--wm-lime))] bg-clip-text text-transparent"
            />
          </h2>
          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.6, ease: EASE_OUT_EXPO }}
            className="mt-5 max-w-md text-[15px] leading-7 text-white/70"
          >
            من تشكيل اللجنة إلى المحضر والقرار والمهمة — كل مراحل العمل المؤسسي في مكان واحد.
          </motion.p>

          <ul className="mt-8 flex flex-wrap gap-2.5">
            {FEATURES.map((f, idx) => (
              <motion.li
                key={f.label}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.75 + idx * 0.08, ease: EASE_OUT_EXPO }}
                className="flex items-center gap-2 rounded-sm border border-white/10 bg-white/[0.06] px-3 py-2 text-sm text-white/85 backdrop-blur-sm"
              >
                <f.icon size={16} style={{ color: f.color }} />
                {f.label}
              </motion.li>
            ))}
          </ul>
        </div>

        <motion.div
          aria-hidden
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 1.2, delay: 0.3 }}
          className="pointer-events-none absolute inset-x-0 bottom-0"
        >
          <BrandWave height={150} speed={1.1} className="translate-y-6 opacity-90" />
        </motion.div>

        <p className="relative text-xs text-white/45">
          © {new Date().getFullYear()} شركة وادي مكة للتقنية — جميع الحقوق محفوظة
        </p>
      </aside>

      {/* ===== نموذج الدخول ===== */}
      <main className="relative flex flex-1 items-center justify-center overflow-hidden px-4 py-10">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 lg:hidden">
          <div className="brand-stripe h-[3px] w-full" />
        </div>
        <div
          aria-hidden
          className="pointer-events-none absolute -top-32 left-1/2 h-72 w-72 -translate-x-1/2 rounded-full bg-[var(--wm-cyan)] opacity-[0.08] blur-3xl"
        />

        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: EASE_OUT_EXPO }}
          className="relative w-full max-w-md"
        >
          <div className="mb-8 flex flex-col items-center gap-3 text-center lg:items-start lg:text-right">
            <img src={wadiMakkahMark} alt="شعار وادي مكة" className="h-16 w-auto lg:hidden" />
            <div>
              <h1 className="text-2xl font-bold text-text-primary">نظام إدارة اللجان والاجتماعات</h1>
              <p className="mt-1.5 text-sm text-text-muted">شركة وادي مكة للتقنية</p>
            </div>
          </div>

          <form
            onSubmit={handleSubmit((values) => {
              setServerError(null)
              mutation.mutate(values)
            })}
            className="relative flex flex-col gap-4 overflow-hidden rounded-lg border border-border-default bg-bg-surface p-6 shadow-xl sm:p-8"
          >
            <div aria-hidden className="brand-stripe absolute inset-x-0 top-0 h-[3px]" />
            <div className="mb-1 flex items-center gap-2.5 text-text-primary">
              <span className="flex h-9 w-9 items-center justify-center rounded-sm bg-brand-primary/10 text-brand-primary">
                <ShieldCheck size={18} />
              </span>
              <div>
                <h2 className="text-base font-semibold leading-tight">تسجيل الدخول</h2>
                <p className="text-xs text-text-muted">أدخل بيانات حسابك للمتابعة</p>
              </div>
            </div>

            <Input
              label="اسم المستخدم"
              placeholder="أدخل اسم المستخدم"
              autoComplete="username"
              error={errors.username?.message}
              {...register('username')}
            />
            <Input
              label="كلمة المرور"
              type="password"
              placeholder="أدخل كلمة المرور"
              autoComplete="current-password"
              error={errors.password?.message}
              {...register('password')}
            />

            <AnimatePresence>
              {serverError && (
                <motion.p
                  initial={{ opacity: 0, height: 0, y: -4 }}
                  animate={{ opacity: 1, height: 'auto', y: 0, x: [0, -6, 6, -3, 3, 0] }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.4 }}
                  className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger"
                >
                  {serverError}
                </motion.p>
              )}
            </AnimatePresence>

            <Button type="submit" size="lg" loading={mutation.isPending} icon={<LogIn size={16} />} className="mt-1">
              تسجيل الدخول
            </Button>
          </form>

          <p className="mt-6 text-center text-xs text-text-muted lg:hidden">
            © {new Date().getFullYear()} شركة وادي مكة للتقنية — جميع الحقوق محفوظة
          </p>
        </motion.div>
      </main>
    </div>
  )
}

const FEATURES = [
  { label: 'اجتماعات مرئية', icon: CalendarDays, color: 'var(--wm-cyan)' },
  { label: 'محاضر ذكية', icon: FileSignature, color: 'var(--wm-gold)' },
  { label: 'قرارات وتصويت', icon: Gavel, color: 'var(--wm-lime)' },
  { label: 'مهام ومتابعة', icon: ListChecks, color: '#c99bd0' },
]
