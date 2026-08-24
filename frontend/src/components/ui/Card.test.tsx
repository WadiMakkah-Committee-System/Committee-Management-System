import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Card } from './Card'

describe('Card', () => {
  it('لا تضيف role/tabIndex عند عدم تفعيل interactive (بطاقة عرض فقط)', () => {
    render(<Card data-testid="card">محتوى</Card>)
    const card = screen.getByTestId('card')
    expect(card).not.toHaveAttribute('role')
    expect(card).not.toHaveAttribute('tabindex')
  })

  it('تضيف role="button" و tabIndex عند تفعيل interactive', () => {
    render(
      <Card interactive onClick={() => {}} data-testid="card">
        محتوى
      </Card>,
    )
    const card = screen.getByTestId('card')
    expect(card).toHaveAttribute('role', 'button')
    expect(card).toHaveAttribute('tabindex', '0')
  })

  it('تستدعي onClick عند الضغط بالفأرة', async () => {
    const onClick = vi.fn()
    render(
      <Card interactive onClick={onClick} data-testid="card">
        محتوى
      </Card>,
    )
    await userEvent.click(screen.getByTestId('card'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('تستدعي onClick عند الضغط على Enter من لوحة المفاتيح (وصولية)', async () => {
    const onClick = vi.fn()
    render(
      <Card interactive onClick={onClick} data-testid="card">
        محتوى
      </Card>,
    )
    const card = screen.getByTestId('card')
    card.focus()
    await userEvent.keyboard('{Enter}')
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('تستدعي onClick عند الضغط على مسافة (Space) من لوحة المفاتيح', async () => {
    const onClick = vi.fn()
    render(
      <Card interactive onClick={onClick} data-testid="card">
        محتوى
      </Card>,
    )
    const card = screen.getByTestId('card')
    card.focus()
    await userEvent.keyboard(' ')
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
