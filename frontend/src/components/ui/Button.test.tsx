import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Button } from './Button'

describe('Button', () => {
  it('يعرض النص الممرر ويستدعي onClick عند الضغط', async () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>احفظ</Button>)

    const button = screen.getByRole('button', { name: 'احفظ' })
    await userEvent.click(button)

    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('يعطّل الزر ولا يستدعي onClick أثناء التحميل (loading)', async () => {
    const onClick = vi.fn()
    render(
      <Button onClick={onClick} loading>
        حفظ
      </Button>,
    )

    const button = screen.getByRole('button')
    expect(button).toBeDisabled()

    await userEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('يعطّل الزر عند disabled صراحةً', () => {
    render(<Button disabled>غير متاح</Button>)
    expect(screen.getByRole('button', { name: 'غير متاح' })).toBeDisabled()
  })
})
