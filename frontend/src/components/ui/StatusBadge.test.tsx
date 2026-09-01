import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CommitteeRoleBadge, UserStatusBadge } from './StatusBadge'

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

// مراجعة لاما 2026-09-01: "لما الشخص يدخل لجنته يعرف اذا هو رئيس لجنة او
// عضو لجنة" — راجعي CommitteeDetailPage.tsx لاستخدامها الفعلي.
describe('CommitteeRoleBadge', () => {
  it('يعرض "رئيس اللجنة" لـchair', () => {
    render(<CommitteeRoleBadge slug="chair" />)
    expect(screen.getByText('رئيس اللجنة')).toBeInTheDocument()
  })

  it('يعرض "عضو اللجنة" لـmember', () => {
    render(<CommitteeRoleBadge slug="member" />)
    expect(screen.getByText('عضو اللجنة')).toBeInTheDocument()
  })

  it('لا يعرض شيئًا لـnull (مشاهد ليس عضوًا فعليًا باللجنة)', () => {
    const { container } = render(<CommitteeRoleBadge slug={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})
