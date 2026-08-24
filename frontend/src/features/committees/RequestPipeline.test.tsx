import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RequestPipeline } from './RequestPipeline'

/**
 * يتحقق من أن الـ Pipeline يعكس كل حالات CommitteeRequestStatus السبع
 * بشكل صحيح حسب آلة الحالة الفعلية بـ committee_service.py (راجعي
 * project_memory: phase2-committee-formation-requests.md). الترميز
 * (Desktop + Mobile) يعرض كل تسمية مرتين بالـ DOM لذا نستخدم
 * getAllByText بدل getByText.
 */
describe('RequestPipeline', () => {
  it('draft: مرحلة الإرسال هي الحالية ولم تُرسَل بعد', () => {
    render(<RequestPipeline status="draft" returnReason={null} />)
    expect(screen.getAllByText('لم يُرسَل بعد').length).toBeGreaterThan(0)
  })

  it('submitted: مرحلة المكتب التنفيذي هي الحالية', () => {
    render(<RequestPipeline status="submitted" returnReason={null} />)
    expect(screen.getAllByText('مراجعة المكتب التنفيذي').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('أُعيد إليك من المكتب التنفيذي للتعديل')).toHaveLength(0)
  })

  it('returned: تنبيه إرجاع عند مرحلة الإرسال', () => {
    render(<RequestPipeline status="returned" returnReason="ينقص بيان اللجنة" />)
    expect(screen.getAllByText('أُعيد إليك من المكتب التنفيذي للتعديل').length).toBeGreaterThan(0)
  })

  it('under_review بدون سبب إرجاع: لا تظهر ملاحظة الإرجاع', () => {
    render(<RequestPipeline status="under_review" returnReason={null} />)
    expect(screen.queryAllByText('أعاده الرئيس التنفيذي لمراجعة إضافية')).toHaveLength(0)
  })

  it('under_review مع سبب إرجاع: تظهر ملاحظة إرجاع الرئيس التنفيذي', () => {
    render(<RequestPipeline status="under_review" returnReason="يلزم تعديل الأعضاء" />)
    expect(screen.getAllByText('أعاده الرئيس التنفيذي لمراجعة إضافية').length).toBeGreaterThan(0)
  })

  it('pending_approval: مرحلة اعتماد الرئيس التنفيذي هي الحالية', () => {
    render(<RequestPipeline status="pending_approval" returnReason={null} />)
    expect(screen.getAllByText('اعتماد الرئيس التنفيذي').length).toBeGreaterThan(0)
  })

  it('approved: القرار النهائي معتمَد', () => {
    render(<RequestPipeline status="approved" returnReason={null} />)
    expect(screen.getAllByText('اعتماد الطلب').length).toBeGreaterThan(0)
  })

  it('rejected: القرار النهائي مرفوض', () => {
    render(<RequestPipeline status="rejected" returnReason={null} />)
    expect(screen.getAllByText('رفض الطلب').length).toBeGreaterThan(0)
  })
})
