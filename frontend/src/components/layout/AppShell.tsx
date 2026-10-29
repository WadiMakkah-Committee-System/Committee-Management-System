import { useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { AppFooter } from './AppFooter'
import { ChangePasswordModal } from '@/features/auth/ChangePasswordModal'

export function AppShell() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const location = useLocation()

  return (
    <div className="relative isolate flex min-h-svh bg-bg-app">
      {/* توهّج خلفي ثابت وخافت جدًا بألوان الهوية — يعطي عمقًا بلا تشتيت */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-40 left-[10%] h-[28rem] w-[28rem] rounded-full bg-[var(--wm-cyan)] opacity-[0.05] blur-3xl" />
        <div className="absolute top-1/3 -left-40 h-[24rem] w-[24rem] rounded-full bg-[var(--wm-purple)] opacity-[0.04] blur-3xl" />
      </div>

      <Sidebar mobileOpen={mobileNavOpen} onCloseMobile={() => setMobileNavOpen(false)} />
      <div className="relative flex min-w-0 flex-1 flex-col">
        <Topbar onOpenMobileNav={() => setMobileNavOpen(true)} />
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
          {/* انتقال الصفحات: ظهور ناعم بصعود خفيف عند تغيّر المسار (دخول فقط —
              بلا انتظار خروج الصفحة السابقة، حتى لا يتأخر التنقل أبدًا). */}
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
          >
            <Outlet />
          </motion.div>
        </main>
        <AppFooter />
      </div>
      <ChangePasswordModal />
    </div>
  )
}
