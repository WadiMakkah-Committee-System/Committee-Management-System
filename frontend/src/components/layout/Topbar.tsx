import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, LogOut, Menu, UserCircle } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { useMutation } from '@tanstack/react-query'
import * as authApi from '@/api/auth'
import { Avatar } from '@/components/ui/Avatar'
import { ThemeToggle } from './ThemeToggle'
import { ROLE_LABELS } from '@/lib/utils'

export function Topbar({ onOpenMobileNav }: { onOpenMobileNav: () => void }) {
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  const logoutMutation = useMutation({
    mutationFn: authApi.logout,
    onSettled: () => {
      logout()
      navigate('/login', { replace: true })
    },
  })

  useEffect(() => {
    if (!menuOpen) return
    const onClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [menuOpen])

  if (!user) return null

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-border-default bg-bg-surface/80 px-4 backdrop-blur-md sm:px-6">
      <button
        onClick={onOpenMobileNav}
        className="rounded-sm p-2 text-text-secondary hover:bg-bg-elevated lg:hidden"
        aria-label="فتح القائمة"
      >
        <Menu size={20} />
      </button>

      <div className="hidden lg:block" />

      <div className="flex items-center gap-2">
        <ThemeToggle />
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((o) => !o)}
            className="flex items-center gap-2 rounded-sm py-1.5 pr-1 pl-2.5 transition-colors hover:bg-bg-elevated"
          >
            <Avatar firstName={user.first_name} lastName={user.last_name} size={32} />
            <span className="hidden text-right sm:block">
              <span className="block text-sm font-semibold leading-tight text-text-primary">
                {user.first_name} {user.last_name}
              </span>
              <span className="block text-xs leading-tight text-text-muted">
                {ROLE_LABELS[user.role]}
              </span>
            </span>
            <ChevronDown size={14} className="text-text-muted" />
          </button>

          <AnimatePresence>
            {menuOpen && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95, y: -4 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: -4 }}
                transition={{ duration: 0.12 }}
                className="absolute left-0 top-full mt-2 w-52 overflow-hidden rounded-sm border border-border-default bg-bg-elevated py-1 shadow-lg"
              >
                <button
                  onClick={() => {
                    setMenuOpen(false)
                    navigate('/profile')
                  }}
                  className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-right text-sm text-text-primary transition-colors hover:bg-bg-surface"
                >
                  <UserCircle size={16} />
                  الملف الشخصي
                </button>
                <div className="my-1 h-px bg-border-default" />
                <button
                  onClick={() => logoutMutation.mutate()}
                  disabled={logoutMutation.isPending}
                  className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-right text-sm text-danger transition-colors hover:bg-danger-bg disabled:opacity-50"
                >
                  <LogOut size={16} />
                  تسجيل الخروج
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </header>
  )
}
