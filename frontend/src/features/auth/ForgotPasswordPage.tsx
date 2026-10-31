import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight, KeyRound, Mail, RotateCw, ShieldCheck } from 'lucide-react'
import * as authApi from '@/api/auth'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { useToast } from '@/components/ui/Toast'
import { extractErrorMessage } from '@/lib/utils'
import wadiMakkahMark from '@/assets/wadi-makkah-mark.png'
import { NEW_PASSWORD_HINT, newPasswordSchema } from './passwordPolicy'

/** نفس مهلة إعادة الإرسال بالباك إند (PASSWORD_RESET_RESEND_SECONDS). */
const RESEND_SECONDS = 60

type Step = 'email' | 'code' | 'password'

const emailSchema = z.object({
  email: z.string().min(1, 'البريد الإلكتروني مطلوب').email('صيغة البريد الإلكتروني غير صحيحة'),
})

const codeSchema = z.object({
  otp_code: z.string().regex(/^\d{6}$/, 'الرمز يتكون من 6 أرقام'),
})

const passwordSchema = z
  .object({
    new_password: newPasswordSchema,
    confirm_password: z.string(),
  })
  .refine((data) => data.new_password === data.confirm_password, {
    message: 'كلمتا المرور غير متطابقتين',
    path: ['confirm_password'],
  })

const STEP_META: Record<Step, { title: string; description: string }> = {
  email: {
    title: 'نسيت كلمة المرور',
    description: 'أدخل بريدك الإلكتروني المسجّل وسنرسل لك رمز تحقق',
  },
  code: {
    title: 'رمز التحقق',
    description: 'إذا كان البريد مسجّلًا ستصلك رسالة برمز من 6 أرقام صالح لمدة 15 دقيقة',
  },
  password: {
    title: 'كلمة مرور جديدة',
    description: 'تم التحقق — عيّن كلمة مرور جديدة لحسابك',
  },
}

/**
 * الهدف:
 * صفحة "نسيت كلمة المرور" العامة (بدون تسجيل دخول) — FR-UM-018.
 *
 * المسؤولية:
 * تدفق من ثلاث خطوات على نفس الصفحة:
 * 1) البريد → POST /auth/forgot-password (الاستجابة واحدة دائمًا — لا تكشف
 *    هل البريد مسجّل).
 * 2) الرمز → POST /auth/verify-reset-code (خطوة تحقق مستقلة)، مع إعادة إرسال
 *    بعد مهلة 60 ثانية.
 * 3) كلمة المرور الجديدة + التأكيد → POST /auth/reset-password، ثم العودة
 *    لصفحة الدخول برسالة نجاح.
 *
 * الحالة: step، البريد والرمز المعتمدين من الخطوات السابقة، وعدّاد إعادة الإرسال.
 * التأثيرات الجانبية: طلبات API فقط — لا تخزين محلي للبريد أو الرمز.
 * الأمان: كل القيود الحقيقية (حد المحاولات، المهلة، سياسة كلمة المرور،
 * إبطال الجلسات) مفروضة بالباك إند؛ تحقق الواجهة لتجربة المستخدم فقط.
 */
export function ForgotPasswordPage() {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const [step, setStep] = useState<Step>('email')
  const [email, setEmail] = useState('')
  const [otpCode, setOtpCode] = useState('')
  const [serverError, setServerError] = useState<string | null>(null)
  const [resendIn, setResendIn] = useState(0)

  useEffect(() => {
    if (resendIn <= 0) return
    const timer = window.setTimeout(() => setResendIn((s) => s - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [resendIn])

  const emailForm = useForm<z.infer<typeof emailSchema>>({ resolver: zodResolver(emailSchema) })
  const codeForm = useForm<z.infer<typeof codeSchema>>({ resolver: zodResolver(codeSchema) })
  const passwordForm = useForm<z.infer<typeof passwordSchema>>({ resolver: zodResolver(passwordSchema) })

  const requestMutation = useMutation({
    mutationFn: (value: string) => authApi.requestPasswordReset(value),
    onSuccess: (_data, value) => {
      setEmail(value)
      setResendIn(RESEND_SECONDS)
      setStep('code')
    },
    onError: (error) => setServerError(extractErrorMessage(error)),
  })

  const verifyMutation = useMutation({
    mutationFn: (code: string) => authApi.verifyResetCode({ email, otp_code: code }),
    onSuccess: (_data, code) => {
      setOtpCode(code)
      setStep('password')
    },
    onError: (error) => setServerError(extractErrorMessage(error)),
  })

  const resetMutation = useMutation({
    mutationFn: (newPassword: string) =>
      authApi.resetPassword({ email, otp_code: otpCode, new_password: newPassword }),
    onSuccess: () => {
      showToast('تم تغيير كلمة المرور بنجاح — سجّل الدخول بكلمة المرور الجديدة', 'success')
      navigate('/login', { replace: true })
    },
    onError: (error) => setServerError(extractErrorMessage(error)),
  })

  const goTo = (next: Step) => {
    setServerError(null)
    setStep(next)
  }

  const handleResend = () => {
    setServerError(null)
    codeForm.reset()
    requestMutation.mutate(email, {
      onSuccess: () => showToast('أُعيد إرسال رمز التحقق', 'success'),
    })
  }

  const meta = STEP_META[step]

  return (
    <div className="flex min-h-svh items-center justify-center bg-bg-app px-4">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
        className="w-full max-w-md"
      >
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <img src={wadiMakkahMark} alt="شعار وادي مكة" className="h-16 w-auto" />
          <div>
            <h1 className="text-2xl font-bold text-text-primary">نظام إدارة اللجان والاجتماعات</h1>
            <p className="mt-1 text-sm text-text-muted">شركة وادي مكة للتقنية</p>
          </div>
        </div>

        {/* نفس تنسيق كرت صفحة تسجيل الدخول (شريط الهوية + أيقونة بمربع) */}
        <div className="relative flex flex-col gap-4 overflow-hidden rounded-lg border border-border-default bg-bg-surface p-6 shadow-xl sm:p-8">
          <div aria-hidden className="brand-stripe absolute inset-x-0 top-0 h-[3px]" />
          <div className="mb-1 flex items-center gap-2.5 text-text-primary">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-sm bg-brand-primary/10 text-brand-primary">
              <ShieldCheck size={18} />
            </span>
            <div>
              <h2 className="text-base font-semibold leading-tight">{meta.title}</h2>
              <p className="text-xs text-text-muted">{meta.description}</p>
            </div>
          </div>

          <ol className="flex gap-1.5" aria-label="خطوات الاستعادة">
            {(['email', 'code', 'password'] as Step[]).map((s, i) => (
              <li
                key={s}
                aria-current={s === step ? 'step' : undefined}
                className={`h-1 flex-1 rounded-full ${
                  i <= (['email', 'code', 'password'] as Step[]).indexOf(step) ? 'bg-brand-primary' : 'bg-border-default'
                }`}
              />
            ))}
          </ol>

          {step === 'email' && (
            <form
              noValidate
              onSubmit={emailForm.handleSubmit(({ email: value }) => {
                setServerError(null)
                requestMutation.mutate(value.trim())
              })}
              className="flex flex-col gap-4"
            >
              <Input
                label="البريد الإلكتروني"
                type="email"
                dir="ltr"
                placeholder="name@example.com"
                autoComplete="email"
                autoFocus
                error={emailForm.formState.errors.email?.message}
                {...emailForm.register('email')}
              />
              {serverError && <ErrorBox message={serverError} />}
              <Button type="submit" size="lg" loading={requestMutation.isPending} icon={<Mail size={16} />}>
                إرسال رمز التحقق
              </Button>
            </form>
          )}

          {step === 'code' && (
            <form
              noValidate
              onSubmit={codeForm.handleSubmit(({ otp_code }) => {
                setServerError(null)
                verifyMutation.mutate(otp_code)
              })}
              className="flex flex-col gap-4"
            >
              <p className="text-sm text-text-secondary">
                أُرسل الرمز إلى{' '}
                <span dir="ltr" className="font-medium text-text-primary">
                  {email}
                </span>{' '}
                — تحقق من مجلد الرسائل غير المرغوب فيها أيضًا.
              </p>
              <Input
                label="رمز التحقق"
                dir="ltr"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                placeholder="000000"
                autoFocus
                className="text-center text-lg tracking-[0.5em]"
                error={codeForm.formState.errors.otp_code?.message}
                {...codeForm.register('otp_code')}
              />
              {serverError && <ErrorBox message={serverError} />}
              <Button type="submit" size="lg" loading={verifyMutation.isPending} icon={<ShieldCheck size={16} />}>
                تحقق
              </Button>
              <div className="flex items-center justify-between gap-2">
                <Button type="button" variant="ghost" size="sm" onClick={() => goTo('email')}>
                  تغيير البريد
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  icon={<RotateCw size={14} />}
                  disabled={resendIn > 0 || requestMutation.isPending}
                  loading={requestMutation.isPending}
                  onClick={handleResend}
                >
                  {resendIn > 0 ? `إعادة الإرسال بعد ${resendIn} ث` : 'إعادة إرسال الرمز'}
                </Button>
              </div>
            </form>
          )}

          {step === 'password' && (
            <form
              noValidate
              onSubmit={passwordForm.handleSubmit(({ new_password }) => {
                setServerError(null)
                resetMutation.mutate(new_password)
              })}
              className="flex flex-col gap-4"
            >
              <Input
                label="كلمة المرور الجديدة"
                type="password"
                autoComplete="new-password"
                autoFocus
                hint={NEW_PASSWORD_HINT}
                error={passwordForm.formState.errors.new_password?.message}
                {...passwordForm.register('new_password')}
              />
              <Input
                label="تأكيد كلمة المرور الجديدة"
                type="password"
                autoComplete="new-password"
                error={passwordForm.formState.errors.confirm_password?.message}
                {...passwordForm.register('confirm_password')}
              />
              <p className="text-xs text-text-muted">سيتم تسجيل خروجك من كل الأجهزة بعد تغيير كلمة المرور.</p>
              {serverError && <ErrorBox message={serverError} />}
              <Button type="submit" size="lg" loading={resetMutation.isPending} icon={<KeyRound size={16} />}>
                حفظ كلمة المرور
              </Button>
              {serverError && (
                <Button type="button" variant="ghost" size="sm" onClick={() => goTo('email')}>
                  طلب رمز جديد
                </Button>
              )}
            </form>
          )}

          <Link
            to="/login"
            className="mt-1 inline-flex items-center justify-center gap-1.5 text-sm font-medium text-brand-primary hover:underline"
          >
            <ArrowRight size={14} />
            العودة لتسجيل الدخول
          </Link>
        </div>

        <p className="mt-6 text-center text-xs text-text-muted">
          © {new Date().getFullYear()} شركة وادي مكة للتقنية — جميع الحقوق محفوظة
        </p>
      </motion.div>
    </div>
  )
}

/** صندوق خطأ الخادم — نفس تنسيق رسالة الخطأ بصفحة تسجيل الدخول. */
function ErrorBox({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger"
    >
      {message}
    </p>
  )
}
