import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ToastProvider } from '@/components/ui/Toast'
import { UserFormModal } from './UserFormModal'
import type { User } from '@/types'

// الهوكات تجلب من الـAPI عبر React Query — نستبدلها ببيانات ثابتة
vi.mock('@/hooks/useRoles', () => ({ useRoles: () => ({ data: [] }) }))
vi.mock('@/hooks/useJobTitles', () => ({
  useJobTitles: () => ({ data: [] }),
  useCreateJobTitle: () => ({ mutateAsync: vi.fn() }),
}))

const EXISTING_USER: User = {
  user_id: 'u-1',
  first_name: 'سارة',
  middle_name: 'محمد',
  last_name: 'العتيبي',
  username: 'sara',
  email: 'sara@example.com',
  role: null,
  dep_id: null,
  department: null,
  job_title_id: null,
  job_title: null,
  status: 'active',
  must_change_password: false,
  last_login_at: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
} as unknown as User

/** يعرض نموذج المستخدم مفتوحًا داخل ToastProvider (مطلوب لزر النسخ). */
function renderModal(props: Partial<Parameters<typeof UserFormModal>[0]> = {}) {
  const onSubmitCreate = vi.fn()
  render(
    <ToastProvider>
      <UserFormModal
        open
        onClose={() => {}}
        departments={[]}
        onSubmitCreate={onSubmitCreate}
        onSubmitEdit={() => {}}
        {...props}
      />
    </ToastProvider>,
  )
  return { onSubmitCreate }
}

const usernameInput = () => screen.getByLabelText(/اسم المستخدم/) as HTMLInputElement
const emailInput = () => screen.getByLabelText(/البريد الإلكتروني/) as HTMLInputElement
const passwordInput = () => screen.getByLabelText(/كلمة المرور المؤقتة/) as HTMLInputElement

describe('UserFormModal — اقتراح بيانات الدخول', () => {
  it('يملأ كلمة مرور مؤقتة مطابقة للسياسة عند فتح نموذج الإضافة', () => {
    renderModal()
    const password = passwordInput().value
    expect(password).toHaveLength(12)
    expect(password).toMatch(/[A-Z]/)
    expect(password).toMatch(/[a-z]/)
    expect(password).toMatch(/[0-9]/)
  })

  it('يقترح اسم المستخدم من البريد أثناء الكتابة', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(emailInput(), 'Ahmed.Ali@wadimakkah.sa')
    expect(usernameInput().value).toBe('ahmed.ali')
  })

  it('لا يغيّر اسم المستخدم بعد تعديله يدويًا', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(usernameInput(), 'custom_name')
    await user.type(emailInput(), 'ahmed@wadimakkah.sa')
    expect(usernameInput().value).toBe('custom_name')
  })

  it('يعود للاقتراح التلقائي إذا مُسح اسم المستخدم بالكامل', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(usernameInput(), 'x')
    await user.clear(usernameInput())
    await user.type(emailInput(), 'khalid@wadimakkah.sa')
    expect(usernameInput().value).toBe('khalid')
  })

  it('يولّد كلمة مرور جديدة عند الضغط على الزر', async () => {
    const user = userEvent.setup()
    renderModal()
    const before = passwordInput().value
    await user.click(screen.getByRole('button', { name: 'توليد كلمة مرور جديدة' }))
    expect(passwordInput().value).not.toBe(before)
  })

  it('يمنع المتصفح من تعبئة بيانات دخول الادمن المحفوظة', () => {
    renderModal()
    expect(passwordInput()).toHaveAttribute('autocomplete', 'new-password')
    expect(usernameInput()).toHaveAttribute('autocomplete', 'off')
  })

  it('يرسل اسم المستخدم وكلمة المرور المقترحين عند الحفظ', async () => {
    const user = userEvent.setup()
    const { onSubmitCreate } = renderModal()
    await user.type(screen.getByLabelText(/الاسم الأول/), 'أحمد')
    await user.type(screen.getByLabelText(/الاسم الأوسط/), 'محمد')
    await user.type(screen.getByLabelText(/اسم العائلة/), 'علي')
    await user.type(emailInput(), 'ahmed.ali@wadimakkah.sa')
    const password = passwordInput().value
    await user.click(screen.getByRole('button', { name: 'إضافة المستخدم' }))
    expect(onSubmitCreate).toHaveBeenCalledWith(
      expect.objectContaining({ username: 'ahmed.ali', password, email: 'ahmed.ali@wadimakkah.sa' }),
    )
  })

  it('لا يعرض حقول اسم المستخدم وكلمة المرور في وضع التعديل', () => {
    renderModal({ user: EXISTING_USER })
    expect(screen.queryByLabelText(/اسم المستخدم/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'توليد كلمة مرور جديدة' })).not.toBeInTheDocument()
    expect(emailInput().value).toBe('sara@example.com')
  })
})
