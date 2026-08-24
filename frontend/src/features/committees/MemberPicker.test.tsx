import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemberPicker } from './MemberPicker'
import type { User } from '@/types'

function makeUser(overrides: Partial<User>): User {
  return {
    user_id: 'u-1',
    first_name: 'سارة',
    middle_name: '',
    last_name: 'العتيبي',
    username: 'sarah',
    email: 'sarah@example.com',
    role: { role_id: 'r-1', name: 'admin', description: null, is_super_admin: false },
    dep_id: null,
    department: null,
    status: 'active',
    must_change_password: false,
    last_login_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

const USERS: User[] = [
  makeUser({ user_id: 'u-1', first_name: 'سارة', last_name: 'العتيبي', email: 'sarah@example.com' }),
  makeUser({ user_id: 'u-2', first_name: 'محمد', last_name: 'القحطاني', email: 'mohammed@example.com' }),
]

describe('MemberPicker', () => {
  it('يعرض عدّاد "0 محدد" عند عدم اختيار أي عضو', () => {
    render(<MemberPicker users={USERS} selected={[]} onChange={() => {}} />)
    expect(screen.getByText('0 محدد')).toBeInTheDocument()
  })

  it('يستدعي onChange بالمعرّف الصحيح عند اختيار عضو', async () => {
    const onChange = vi.fn()
    render(<MemberPicker users={USERS} selected={[]} onChange={onChange} />)

    await userEvent.click(screen.getByText('سارة العتيبي'))
    expect(onChange).toHaveBeenCalledWith(['u-1'])
  })

  it('يعرض رقائق الأعضاء المحدَّدين ويحدّث العدّاد', () => {
    render(<MemberPicker users={USERS} selected={['u-1', 'u-2']} onChange={() => {}} />)
    expect(screen.getByText('2 محدد')).toBeInTheDocument()
    expect(screen.getAllByText('سارة العتيبي').length).toBeGreaterThan(0)
  })

  it('يزيل العضو عند الضغط على زر الإزالة بالرقاقة', async () => {
    const onChange = vi.fn()
    render(<MemberPicker users={USERS} selected={['u-1']} onChange={onChange} />)

    await userEvent.click(screen.getByLabelText('إزالة سارة العتيبي'))
    expect(onChange).toHaveBeenCalledWith([])
  })

  it('يعرض رسالة الخطأ الممرَّرة', () => {
    render(<MemberPicker users={USERS} selected={[]} onChange={() => {}} error="اختاري عضوًا واحدًا على الأقل" />)
    expect(screen.getByText('اختاري عضوًا واحدًا على الأقل')).toBeInTheDocument()
  })

  it('يفلتر القائمة بالبحث بالاسم', async () => {
    render(<MemberPicker users={USERS} selected={[]} onChange={() => {}} />)
    await userEvent.type(screen.getByPlaceholderText('ابحث بالاسم أو البريد الإلكتروني...'), 'محمد')
    expect(screen.getByText('محمد القحطاني')).toBeInTheDocument()
    expect(screen.queryByText('سارة العتيبي')).not.toBeInTheDocument()
  })
})
