import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Users,
  Building2,
  Users2,
  CalendarDays,
  ListChecks,
  Gavel,
  FileText,
  Sparkles,
  Bell,
  BarChart3,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import wadiMakkahMark from '@/assets/wadi-makkah-mark.png'

interface NavItem {
  label: string
  icon: LucideIcon
  path?: string
  /** يكفي امتلاك واحدة من هذه الصلاحيات (أو is_super_admin) لإظهار العنصر. */
  requiredPermission?: string[]
  comingSoon?: boolean
}

/** ترتيب التنقل الموثّق في §15 — العناصر غير المبنية بعد تظهر معطّلة ("قريبًا") بدل إخفائها. */
const NAV_ITEMS: NavItem[] = [
  { label: 'لوحة التحكم', icon: LayoutDashboard, comingSoon: true },
  { label: 'المستخدمون', icon: Users, path: '/users', requiredPermission: ['users.view'] },
  { label: 'الإدارات', icon: Building2, path: '/departments', requiredPermission: ['departments.view'] },
  { label: 'اللجان', icon: Users2, comingSoon: true },
  { label: 'الاجتماعات', icon: CalendarDays, comingSoon: true },
  { label: 'المهام', icon: ListChecks, comingSoon: true },
  { label: 'القرارات', icon: Gavel, comingSoon: true },
  { label: 'الوثائق', icon: FileText, comingSoon: true },
  { label: 'البحث الذكي', icon: Sparkles, comingSoon: true },
  { label: 'الإشعارات', icon: Bell, comingSoon: true },
  { label: 'التقارير', icon: BarChart3, comingSoon: true },
]

export function Sidebar({ mobileOpen, onCloseMobile }: { mobileOpen: boolean; onCloseMobile: () => void }) {
  const user = useAuthStore((s) => s.user)
  const isSuperAdmin = !!user?.role.is_super_admin
  const permissions = user?.permissions ?? []

  const items = NAV_ITEMS.filter(
    (item) =>
      !item.requiredPermission ||
      isSuperAdmin ||
      item.requiredPermission.some((code) => permissions.includes(code)),
  )

  return (
    <>
      {mobileOpen && (
        <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={onCloseMobile} />
      )}
      <aside
        className={cn(
          'fixed inset-y-0 right-0 z-40 flex w-64 shrink-0 flex-col bg-sidebar-bg transition-transform duration-200 lg:sticky lg:top-0 lg:h-svh lg:translate-x-0',
          mobileOpen ? 'translate-x-0' : 'translate-x-full lg:translate-x-0',
        )}
      >
        <div className="flex h-20 items-center gap-2.5 px-5">
          <img src={wadiMakkahMark} alt="شعار وادي مكة" className="h-9 w-auto shrink-0" />
          <div className="leading-tight">
            <p className="text-sm font-bold text-white">وادي مكة</p>
            <p className="text-[11px] text-white/50">إدارة اللجان والاجتماعات</p>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-2">
          <ul className="flex flex-col gap-1">
            {items.map((item) => (
              <li key={item.label}>
                {item.comingSoon || !item.path ? (
                  <div className="flex cursor-not-allowed items-center justify-between gap-3 rounded-sm px-3 py-2.5 text-sm text-white/35">
                    <span className="flex items-center gap-3">
                      <item.icon size={18} />
                      {item.label}
                    </span>
                    <span className="rounded-xs bg-white/5 px-1.5 py-0.5 text-[10px]">قريبًا</span>
                  </div>
                ) : (
                  <NavLink
                    to={item.path}
                    onClick={onCloseMobile}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center gap-3 rounded-sm px-3 py-2.5 text-sm font-medium transition-colors',
                        isActive
                          ? 'bg-sidebar-active-bg text-white'
                          : 'text-white/70 hover:bg-sidebar-hover-bg hover:text-white',
                      )
                    }
                  >
                    <item.icon size={18} />
                    {item.label}
                  </NavLink>
                )}
              </li>
            ))}
          </ul>
        </nav>
      </aside>
    </>
  )
}
