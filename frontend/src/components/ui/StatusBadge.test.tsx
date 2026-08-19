import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { UserStatusBadge } from './StatusBadge'

describe('UserStatusBadge', () => {
  it('يعرض "نشط" لحالة active', () => {
    render(<UserStatusBadge status="active" />)
    expect(screen.getByText('نشط')).toBeInTheDocument()
  })

  it('يعرض "موقوف" لحالة suspended', () => {
    render(<UserStatusBadge status="suspended" />)
    expect(screen.getByText('موقوف')).toBeInTheDocument()
  })
})
