import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowLeftRight, Check, ChevronDown, Loader2 } from 'lucide-react'
import { useSwitchActiveRole } from '@/hooks/useUsers'
import { assignedRoles, cn, extractErrorMessage, roleLabel } from '@/lib/utils'
import { notify } from '@/components/ui/Toast'
import { useAuthStore } from '@/store/authStore'

/**
 * الهدف:
 * مبدّل الدور الحالي بالشريط العلوي — تعدد الأدوار (migration 0046، قرار
 * صاحب المشروع 2026-11-08: هيكلة "مبدّل الأدوار" بدل العرض المدمج).
 *
 * المسؤولية:
 * - يعرض الدور الحالي دائمًا ("تعمل الآن كـ ...") لمن يحمل أكثر من دور.
 * - قائمة بأدواره، والضغط على دور آخر يبدّل إليه (POST /users/me/active-role)
 *   ثم ينتقل للوحة التحكم — الصفحة الحالية قد لا تتبع الدور الجديد.
 * - لا يظهر إطلاقًا لمن يحمل دورًا واحدًا (أو بلا دور).
 *
 * المدخلات: لا شيء — يقرأ المستخدم الحالي من authStore.
 *
 * التأثيرات الجانبية: استدعاء API للتبديل، تحديث authStore وإعادة ضبط
 * البيانات المخزّنة (useSwitchActiveRole)، والتنقل لـ/dashboard.
 *
 * الصلاحيات: أي مستخدم مسجَّل الدخول، لأدواره المسندة فقط (يفرضها الباك-إند).
 */
export function RoleSwitcher() {
  const user = useAuthStore((s) => s.user)
  const navigate = useNavigate()
  const switchMutation = useSwitchActiveRole()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    document.addEventListener('keydown', onEscape)
    return () => {
      document.removeEventListener('mousedown', onClickOutside)
      document.removeEventListener('keydown', onEscape)
    }
  }, [open])

  if (!user) return null
  const roles = assignedRoles(user)
  if (roles.length < 2) return null

  const currentId = user.role?.role_id

  /** التبديل لدور آخر ثم الانتقال للوحة التحكم (بداية نظيفة بالدور الجديد). */
  async function switchTo(roleId: string) {
    if (roleId === currentId || switchMutation.isPending) return
    try {
      await switchMutation.mutateAsync(roleId)
      setOpen(false)
      navigate('/dashboard')
    } catch (error) {
      notify(extractErrorMessage(error), 'error')
    }
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`الدور الحالي: ${roleLabel(user.role)} — تبديل الدور`}
        className="flex h-9 items-center gap-2 rounded-sm border border-brand-primary/30 bg-brand-primary/[0.06] px-2.5 text-brand-primary transition-colors hover:border-brand-primary hover:bg-brand-primary/[0.1]"
      >
        <ArrowLeftRight size={15} className="shrink-0" />
        <span className="hidden max-w-[11rem] truncate text-right sm:block">
          <span className="block text-[10px] leading-tight text-text-muted">تعمل الآن كـ</span>
          <span className="block text-xs font-semibold leading-tight">{roleLabel(user.role)}</span>
        </span>
        <ChevronDown size={13} className={cn('shrink-0 transition-transform duration-300', open && 'rotate-180')} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={{ opacity: 0, scale: 0.96, y: -6 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -4 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            style={{ transformOrigin: 'top left' }}
            className="absolute left-0 top-full z-30 mt-2 w-64 overflow-hidden rounded-md border border-border-default bg-bg-surface py-1 shadow-xl"
          >
            <p className="px-3.5 pb-1.5 pt-2 text-xs font-semibold text-text-muted">تبديل الدور</p>
            {roles.map((role) => {
              const isCurrent = role.role_id === currentId
              const isSwitching = switchMutation.isPending && switchMutation.variables === role.role_id
              return (
                <button
                  key={role.role_id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={isCurrent}
                  disabled={switchMutation.isPending}
                  onClick={() => switchTo(role.role_id)}
                  className={cn(
                    'flex w-full items-center justify-between gap-2 px-3.5 py-2.5 text-right text-sm transition-colors disabled:cursor-not-allowed',
                    isCurrent
                      ? 'bg-brand-primary/[0.06] font-semibold text-brand-primary'
                      : 'text-text-primary hover:bg-bg-elevated disabled:opacity-60',
                  )}
                >
                  <span className="truncate">{roleLabel(role)}</span>
                  {isSwitching ? (
                    <Loader2 size={15} className="shrink-0 animate-spin" />
                  ) : (
                    isCurrent && <Check size={15} className="shrink-0" />
                  )}
                </button>
              )
            })}
            <p className="border-t border-border-default px-3.5 py-2 text-[11px] leading-relaxed text-text-muted">
              تظهر لك صلاحيات الدور الحالي فقط
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
