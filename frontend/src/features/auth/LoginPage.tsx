import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Building2, LogIn, ShieldCheck } from 'lucide-react'
import * as authApi from '@/api/auth'
import * as usersApi from '@/api/users'
import { usersKeys } from '@/hooks/useUsers'
import { useAuthStore } from '@/store/authStore'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { extractErrorMessage } from '@/lib/utils'
import {
  isCompanyEmail,
  isMicrosoftCancel,
  loadLoginOptions,
  loadMicrosoftClient,
  signInWithMicrosoft,
  signOutMicrosoft,
} from '@/lib/microsoftSignIn'
import type { AuthMethod, LoginOptions, TokenResponse } from '@/types'
import wadiMakkahMark from '@/assets/wadi-makkah-mark.png'
import { BrandWave } from '@/components/brand/BrandWave'
import { EASE_OUT_EXPO, SplitWords } from '@/components/motion/primitives'

// كلمة المرور اختيارية بالمخطط لأن موظف الشركة (بريد من نطاقها) يكمل من نافذة
// Microsoft بدونها — وتُفرض يدويًا بمسار كلمة المرور (handleLogin أدناه).
const schema = z.object({
  username: z.string().trim().min(1, 'اسم المستخدم أو الإيميل مطلوب'),
  password: z.string().optional(),
})

type FormValues = z.infer<typeof schema>

/**
 * صفحة تسجيل الدخول — خانة واحدة تقرر الطريق (قرار لاما 2026-11-02):
 * - بريد من نطاق الشركة (مثل name@wadimakkah.sa) ⇒ تختفي كلمة المرور ويكمل
 *   من نافذة Microsoft (POST /auth/microsoft) — ونفس الدخول يفتح الاجتماعات
 *   بهويته بدون نافذة ثانية.
 * - غير ذلك (اسم مستخدم، أو عضو من خارج الشركة) ⇒ كلمة المرور كالمعتاد
 *   بكل متطلبات FR-UM-015..019.
 * إعدادات Microsoft تُجلب من الباك-إند، ولو الميزة غير مفعّلة تبقى الصفحة كما كانت.
 */
export function LoginPage() {
  const navigate = useNavigate()
  const setTokens = useAuthStore((s) => s.setTokens)
  const setUser = useAuthStore((s) => s.setUser)
  const setAuthMethod = useAuthStore((s) => s.setAuthMethod)
  const queryClient = useQueryClient()
  const [serverError, setServerError] = useState<string | null>(null)
  const [loginOptions, setLoginOptions] = useState<LoginOptions | null>(null)

  const {
    register,
    handleSubmit,
    watch,
    setError,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  // تهيئة إعدادات Microsoft ومكتبة MSAL أول ما تفتح الصفحة (مو عند الضغط)،
  // حتى تفتح نافذة Microsoft مباشرة من ضغطة الزر بدون ما يحجبها المتصفح.
  useEffect(() => {
    let active = true
    loadLoginOptions()
      .then((options) => {
        if (!active) return
        setLoginOptions(options)
        if (options.microsoft_enabled) void loadMicrosoftClient().catch(() => {})
      })
      .catch(() => {})
    return () => {
      active = false
    }
  }, [])

  const microsoftEnabled = Boolean(loginOptions?.microsoft_enabled)
  const usesMicrosoft = isCompanyEmail(watch('username') ?? '', loginOptions)

  /** المشترك بين طريقتي الدخول: حفظ التوكنات والمستخدم وطريقة الدخول. */
  async function finishLogin(tokens: TokenResponse, method: AuthMethod) {
    setTokens(tokens.access_token, tokens.refresh_token)
    setAuthMethod(method)
    // تحسين أداء 2026-10-25: الباك-إند يرجّع بيانات المستخدم مع رد الدخول
    // نفسه (نفس شكل /users/me) — فلا ننتظر طلبًا ثانيًا متتابعًا. لو رجع
    // بدونها (نسخة باك-إند أقدم) نرجع للسلوك السابق.
    const me = tokens.user ?? (await usersApi.fetchMe())
    queryClient.setQueryData(usersKeys.me, me)
    setUser(me)
    return me
  }

  const mutation = useMutation({
    mutationFn: async (values: { username: string; password: string }) => {
      const tokens = await authApi.login(values)
      // دخول بكلمة المرور ⇒ أي حساب Microsoft محفوظ بالمتصفح (لشخص آخر مثلًا)
      // لازم يُنسى، حتى ما يدخل الاجتماعات بهوية غيره.
      void signOutMicrosoft().catch(() => {})
      return finishLogin(tokens, 'password')
    },
    onSuccess: () => navigate('/users', { replace: true }),
    onError: (error) => setServerError(extractErrorMessage(error)),
  })

  const microsoftMutation = useMutation({
    mutationFn: async (loginHint?: string) => {
      const { idToken } = await signInWithMicrosoft(loginHint)
      try {
        return await finishLogin(await authApi.loginWithMicrosoft(idToken), 'microsoft')
      } catch (err) {
        // المنصة رفضت الحساب (غير مسجل/موقوف...) ⇒ ننسى حساب Microsoft من المتصفح.
        await signOutMicrosoft().catch(() => {})
        throw err
      }
    },
    onSuccess: () => navigate('/users', { replace: true }),
    onError: (error) => {
      if (!isMicrosoftCancel(error)) setServerError(extractErrorMessage(error))
    },
  })

  function handleLogin(values: FormValues) {
    setServerError(null)
    if (isCompanyEmail(values.username, loginOptions)) {
      microsoftMutation.mutate(values.username)
      return
    }
    if (!values.password) {
      setError('password', { message: 'كلمة المرور مطلوبة' })
      return
    }
    mutation.mutate({ username: values.username, password: values.password })
  }

  return (
    <div className="relative flex min-h-svh bg-bg-app">
      {/* ===== لوحة الهوية (شاشات كبيرة) ===== */}
      <aside className="relative hidden w-[46%] max-w-[720px] flex-col overflow-hidden bg-[linear-gradient(160deg,#0b1633_0%,#122a63_55%,#105ea7_120%)] p-12 text-white lg:flex">
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
          <img src={wadiMakkahMark} alt="شعار وادي مكة" className="h-11 w-auto" />
          <div className="leading-tight">
            <p className="text-sm font-bold">شركة وادي مكة للتقنية</p>
            <p className="text-xs text-white/60">Wadi Makkah Company For Technology</p>
          </div>
        </motion.div>

        <div className="relative my-auto">
          <h2 className="text-4xl font-bold leading-[1.35] xl:text-[2.75rem]">
            <SplitWords text="منصة إدارة اللجان" delay={0.2} />
          </h2>
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
            onSubmit={handleSubmit(handleLogin)}
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
              label={microsoftEnabled ? 'اسم المستخدم أو إيميل الشركة' : 'اسم المستخدم'}
              placeholder={microsoftEnabled ? 'name@wadimakkah.sa أو اسم المستخدم' : 'أدخل اسم المستخدم'}
              autoComplete="username"
              error={errors.username?.message}
              {...register('username')}
            />
            <AnimatePresence initial={false} mode="wait">
              {usesMicrosoft ? (
                <motion.p
                  key="microsoft-hint"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="flex items-start gap-2 rounded-sm border border-brand-primary/20 bg-brand-primary/5 px-3 py-2 text-xs text-text-secondary"
                >
                  <Building2 size={14} className="mt-0.5 shrink-0 text-brand-primary" />
                  هذا إيميل الشركة — بتكمل الدخول من نافذة Microsoft بدون كلمة مرور المنصة.
                </motion.p>
              ) : (
                <motion.div
                  key="password-fields"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="flex flex-col gap-4"
                >
                  <Input
                    label="كلمة المرور"
                    type="password"
                    placeholder="أدخل كلمة المرور"
                    autoComplete="current-password"
                    error={errors.password?.message}
                    {...register('password')}
                  />
                  {/* FR-UM-018: الدخول لتدفق استعادة كلمة المرور (صفحة عامة) */}
                  <Link
                    to="/forgot-password"
                    className="-mt-2 self-start text-sm font-medium text-brand-primary hover:underline"
                  >
                    نسيت كلمة المرور؟
                  </Link>
                </motion.div>
              )}
            </AnimatePresence>

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

            <Button
              type="submit"
              size="lg"
              loading={mutation.isPending || microsoftMutation.isPending}
              icon={usesMicrosoft ? <Building2 size={16} /> : <LogIn size={16} />}
              className="mt-1"
            >
              {usesMicrosoft ? 'المتابعة بحساب Microsoft' : 'تسجيل الدخول'}
            </Button>
            {microsoftEnabled && !usesMicrosoft && (
              <button
                type="button"
                disabled={microsoftMutation.isPending}
                onClick={() => {
                  setServerError(null)
                  microsoftMutation.mutate(undefined)
                }}
                className="flex items-center justify-center gap-2 text-sm font-medium text-text-secondary transition-colors hover:text-brand-primary disabled:opacity-60"
              >
                <Building2 size={15} />
                موظف بالشركة؟ الدخول بحساب Microsoft
              </button>
            )}
          </form>
        </motion.div>
      </main>
    </div>
  )
}

