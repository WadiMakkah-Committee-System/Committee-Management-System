import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation } from '@tanstack/react-query'
import { KeyRound } from 'lucide-react'
import * as authApi from '@/api/auth'
import { useAuthStore } from '@/store/authStore'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { useToast } from '@/components/ui/Toast'
import { extractErrorMessage } from '@/lib/utils'

const schema = z
  .object({
    current_password: z.string().min(1, 'كلمة المرور الحالية مطلوبة'),
    new_password: z
      .string()
      .min(8, 'يجب أن تحتوي على 8 أحرف على الأقل')
      .regex(/[A-Z]/, 'يجب أن تحتوي على حرف كبير')
      .regex(/[a-z]/, 'يجب أن تحتوي على حرف صغير')
      .regex(/[0-9]/, 'يجب أن تحتوي على رقم'),
    confirm_password: z.string(),
  })
  .refine((data) => data.new_password === data.confirm_password, {
    message: 'كلمتا المرور غير متطابقتين',
    path: ['confirm_password'],
  })

type FormValues = z.infer<typeof schema>

/**
 * نافذة إجبارية لتغيير كلمة المرور عند أول دخول (FR-UM-016) — بدون زر
 * إغلاق أو إمكانية تجاوزها، حتى يُغيّر المستخدم كلمة المرور المؤقتة.
 */
export function ChangePasswordModal() {
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)
  const { showToast } = useToast()

  const {
    register,
    handleSubmit,
    formState: { errors },
    setError,
    reset,
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  const mutation = useMutation({
    mutationFn: (values: FormValues) => authApi.changePassword(values),
    onSuccess: () => {
      if (user) setUser({ ...user, must_change_password: false })
      showToast('تم تغيير كلمة المرور بنجاح', 'success')
      reset()
    },
    onError: (error) => setError('current_password', { message: extractErrorMessage(error) }),
  })

  if (!user?.must_change_password) return null

  return (
    <Modal
      open
      onClose={() => {}}
      title="مطلوب تغيير كلمة المرور"
      description="هذه كلمة مرور مؤقتة — يجب تعيين كلمة مرور جديدة قبل المتابعة"
      size="sm"
      footer={
        <Button
          form="change-password-form"
          type="submit"
          loading={mutation.isPending}
          icon={<KeyRound size={16} />}
          className="w-full"
        >
          تعيين كلمة المرور
        </Button>
      }
    >
      <form
        id="change-password-form"
        onSubmit={handleSubmit((values) => mutation.mutate(values))}
        className="flex flex-col gap-4"
      >
        <Input
          label="كلمة المرور الحالية"
          type="password"
          error={errors.current_password?.message}
          {...register('current_password')}
        />
        <Input
          label="كلمة المرور الجديدة"
          type="password"
          hint="8 أحرف على الأقل، حرف كبير وصغير ورقم"
          error={errors.new_password?.message}
          {...register('new_password')}
        />
        <Input
          label="تأكيد كلمة المرور الجديدة"
          type="password"
          error={errors.confirm_password?.message}
          {...register('confirm_password')}
        />
      </form>
    </Modal>
  )
}
