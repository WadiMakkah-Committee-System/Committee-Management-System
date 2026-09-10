import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SplashScreen } from './SplashScreen'

describe('SplashScreen', () => {
  it('يعرض المحتوى الداخلي (children) فورًا بلا انتظار', () => {
    render(
      <SplashScreen>
        <div>محتوى صفحة تسجيل الدخول</div>
      </SplashScreen>,
    )
    expect(screen.getByText('محتوى صفحة تسجيل الدخول')).toBeInTheDocument()
  })

  it('يعرض الشاشة الافتتاحية عند كل عرض (بلا تتبّع "ظهرت من قبل")', () => {
    const { unmount } = render(
      <SplashScreen>
        <div>محتوى صفحة تسجيل الدخول</div>
      </SplashScreen>,
    )
    expect(screen.getByTestId('splash-screen')).toBeInTheDocument()
    unmount()

    // إعادة عرض ثانية (تحاكي زيارة ثانية لصفحة تسجيل الدخول) — تظهر مجددًا.
    render(
      <SplashScreen>
        <div>محتوى صفحة تسجيل الدخول</div>
      </SplashScreen>,
    )
    expect(screen.getByTestId('splash-screen')).toBeInTheDocument()
  })
})
