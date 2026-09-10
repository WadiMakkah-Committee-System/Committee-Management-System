import { describe, expect, it, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SplashScreen } from './SplashScreen'

describe('SplashScreen', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it('يعرض المحتوى الداخلي (children) فورًا بلا انتظار', () => {
    render(
      <SplashScreen>
        <div>محتوى التطبيق</div>
      </SplashScreen>,
    )
    expect(screen.getByText('محتوى التطبيق')).toBeInTheDocument()
  })

  it('يعرض الشاشة الافتتاحية أول مرة بالجلسة (شعار وادي مكة ظاهر)', () => {
    render(
      <SplashScreen>
        <div>محتوى التطبيق</div>
      </SplashScreen>,
    )
    expect(screen.getByTestId('splash-screen')).toBeInTheDocument()
  })

  it('لا يعرضها مرة ثانية بنفس الجلسة (sessionStorage محدَّد مسبقًا)', () => {
    window.sessionStorage.setItem('wm-splash-shown', '1')
    render(
      <SplashScreen>
        <div>محتوى التطبيق</div>
      </SplashScreen>,
    )
    expect(screen.queryByTestId('splash-screen')).not.toBeInTheDocument()
  })

  it('تسجّل ظهورها بـsessionStorage فور العرض الأول', () => {
    render(
      <SplashScreen>
        <div>محتوى التطبيق</div>
      </SplashScreen>,
    )
    expect(window.sessionStorage.getItem('wm-splash-shown')).toBe('1')
  })
})
