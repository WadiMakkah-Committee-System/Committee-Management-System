import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfirmDialog } from './ConfirmDialog'

describe('ConfirmDialog', () => {
  it('يعرض رسالة خطأ الباك-إند حرفيًا عند تمريرها (مثل حماية آخر super_admin)', () => {
    render(
      <ConfirmDialog
        open
        onClose={() => {}}
        onConfirm={() => {}}
        title="حذف المستخدم"
        description="هل أنت متأكد؟"
        errorMessage="لا يمكن حذف هذا المستخدم — إنه آخر super_admin نشط في النظام"
      />,
    )

    expect(
      screen.getByText('لا يمكن حذف هذا المستخدم — إنه آخر super_admin نشط في النظام'),
    ).toBeInTheDocument()
  })

  it('يستدعي onConfirm عند الضغط على زر التأكيد', async () => {
    const onConfirm = vi.fn()
    render(
      <ConfirmDialog
        open
        onClose={() => {}}
        onConfirm={onConfirm}
        title="حذف الإدارة"
        description="هل أنت متأكد؟"
        confirmLabel="حذف الإدارة"
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'حذف الإدارة' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('لا يعرض شيئًا عندما open=false', () => {
    render(
      <ConfirmDialog
        open={false}
        onClose={() => {}}
        onConfirm={() => {}}
        title="حذف الإدارة"
        description="هل أنت متأكد؟"
      />,
    )
    expect(screen.queryByText('حذف الإدارة')).not.toBeInTheDocument()
  })
})
