import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { LogIn, ShieldCheck } from 'lucide-react'
import * as authApi from '@/api/auth'
import * as usersApi from '@/api/users'
import { useAuthStore } from '@/store/authStore'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { extractErrorMessage } from '@/lib/utils'

const schema = z.object({
  username: z.string().min(1, 'اسم المستخدم مطلوب'),
  password: z.string().min(1, 'كلمة المرور مطلوبة'),
})

type FormValues = z.infer<typeof schema>

export function LoginPage() {
  const navigate = useNavigate()
  const setTokens = useAuthStore((s) => s.setTokens)
  const setUser = useAuthStore((s) => s.setUser)
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
      const me = await usersApi.fetchMe()
      setUser(me)
      return me
    },
    onSuccess: () => navigate('/users', { replace: true }),
    onError: (error) => setServerError(extractErrorMessage(error)),
  })

  return (
    <div className="flex min-h-svh items-center justify-center bg-bg-app px-4">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
        className="w-full max-w-md"
      >
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-md bg-brand-primary text-xl font-bold text-white shadow-lg shadow-brand-primary/20">
            وم
          </div>
          <div>
            <h1 className="text-xl font-bold text-text-primary">نظام إدارة اللجان والاجتماعات</h1>
            <p className="mt-1 text-sm text-text-muted">شركة وادي مكة للتقنية</p>
          </div>
        </div>

        <form
          onSubmit={handleSubmit((values) => {
            setServerError(null)
            mutation.mutate(values)
          })}
          className="flex flex-col gap-4 rounded-md border border-border-default bg-bg-surface p-6 shadow-sm sm:p-8"
        >
          <div className="mb-1 flex items-center gap-2 text-text-primary">
            <ShieldCheck size={18} className="text-brand-primary" />
            <h2 className="text-base font-semibold">تسجيل الدخول</h2>
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

          {serverError && (
            <p className="rounded-sm border border-danger-border/30 bg-danger-bg px-3 py-2 text-sm font-medium text-danger">
              {serverError}
            </p>
          )}

          <Button type="submit" size="lg" loading={mutation.isPending} icon={<LogIn size={16} />} className="mt-1">
            تسجيل الدخول
          </Button>
        </form>

        <p className="mt-6 text-center text-xs text-text-muted">
          © {new Date().getFullYear()} شركة وادي مكة للتقنية — جميع الحقوق محفوظة
        </p>
      </motion.div>
    </div>
  )
}
