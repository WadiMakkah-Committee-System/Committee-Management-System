import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FixedVoteOptions } from './FixedVoteOptions'

describe('FixedVoteOptions', () => {
  it('يعرض الخيارات الثلاثة الثابتة بالترتيب وبدون أي حقل قابل للتعديل', () => {
    render(<FixedVoteOptions />)
    const items = screen.getAllByRole('listitem').map((li) => li.textContent)
    expect(items).toEqual(['موافق', 'غير موافق', 'ممتنع'])
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.queryByRole('textbox')).toBeNull()
  })
})
