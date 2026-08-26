import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
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
  ShieldQuestion,
  UserRound,
  Briefcase,
  ChevronDown,
  ClipboardList,
  CheckCircle2,
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
  /** يقيّد ظهور العنصر بدور الجذر (is_super_admin) فقط. */
  superAdminOnly?: boolean
  comingSoon?: boolean
  /** عناصر فرعية — يتحول العنصر لقائمة قابلة للتوسيع/الانكماش بدل رابط مباشر. */
  children?: NavItem[]
}

/** ترتيب التنقل الموثّق في §15 — العناصر غير المبنية بعد تظهر معطّلة ("قريبًا") بدل إخفائها. */
const NAV_ITEMS: NavItem[] = [
  { label: 'لوحة التحكم', icon: LayoutDashboard, comingSoon: true },
  {
    label: 'المستخدمين',
    icon: Users,
    children: [
      { label: 'الأدوار والصلاحيات', icon: ShieldQuestion, path: '/users/roles', superAdminOnly: true },
      { label: 'المستخدمون', icon: UserRound, path: '/users', requiredPermission: ['users.view'] },
      { label: 'المسميات الوظيفية', icon: Briefcase, path: '/users/job-titles', requiredPermission: ['job_titles.view'] },
    ],
  },
  { label: 'الإدارات', icon: Building2, path: '/departments', requiredPermission: ['departments.view'] },
  {
    label: 'اللجان',
    icon: Users2,
    children: [
      {
        label: 'طلبات تشكيل اللجان',
        icon: ClipboardList,
        path: '/committees/requests',
        requiredPermission: ['committees.request.create', 'committees.request.view'],
      },
      {
        label: 'اللجان المعتمدة',
        icon: CheckCircle2,
        path: '/committees/approved',
        requiredPermission: ['committees.view_authorized'],
      },
    ],
  },
  { label: 'الاجتماعات', icon: CalendarDays, comingSoon: true },
  { label: 'المهام', icon: ListChecks, comingSoon: true },
  { label: 'القرارات', icon: Gavel, comingSoon: true },
  { label: 'الوثائق', icon: FileText, comingSoon: true },
  { label: 'البحث الذكي', icon: Sparkles, comingSoon: true },
  { label: 'الإشعارات', icon: Bell, comingSoon: true },
  { label: 'التقارير', icon: BarChart3, comingSoon: true },
]

/**
 * يقارن مسار الصفحة الحالية بمسار عنصر تنقّل فرعي — تطابق تام أو صفحة
 * تفاصيل متفرّعة منه (مثال: /committees/requests/{id} تُبقي عنصر "طلبات
 * تشكيل اللجان" نشطًا ومفتوحًا)، بدل التطابق التام فقط الذي يفشل مع أي
 * صفحة تفاصيل مستقبلية تحت نفس العنصر الفرعي.
 */
function isChildPathActive(pathname: string, childPath: string): boolean {
  return pathname === childPath || pathname.startsWith(`${childPath}/`)
}

/** يفلتر عنصرًا (وأبناءه إن وُجدوا) حسب صلاحيات المستخدم — يُسقط أي عنصر فرعي غير مسموح به،
 *  ويُسقط العنصر الأب بالكامل إذا لم يتبقَّ له أي عنصر فرعي ظاهر. */
function filterNavItem(item: NavItem, isSuperAdmin: boolean, permissions: string[]): NavItem | null {
  if (item.children) {
    const children = item.children
      .map((child) => filterNavItem(child, isSuperAdmin, permissions))
      .filter((child): child is NavItem => child !== null)
    if (children.length === 0) return null
    return { ...item, children }
  }
  if (item.superAdminOnly && !isSuperAdmin) return null
  if (item.requiredPermission && !isSuperAdmin && !item.requiredPermission.some((code) => permissions.includes(code))) {
    return null
  }
  return item
}

export function Sidebar({ mobileOpen, onCloseMobile }: { mobileOpen: boolean; onCloseMobile: () => void }) {
  const user = useAuthStore((s) => s.user)
  const isSuperAdmin = !!user?.role.is_super_admin
  const permissions = user?.permissions ?? []
  const location = useLocation()

  const items = NAV_ITEMS.map((item) => filterNavItem(item, isSuperAdmin, permissions)).filter(
    (item): item is NavItem => item !== null,
  )

  const [openLabel, setOpenLabel] = useState<string | null>(null)

  // يفتح القسم تلقائيًا عند الدخول مباشرة لأحد عناصره الفرعية (تحديث الصفحة أو رابط مباشر)،
  // ويبقى مفتوحًا طالما المستخدم لم يطوِه يدويًا بعد ذلك.
  useEffect(() => {
    const parentWithActiveChild = items.find((item) =>
      item.children?.some((child) => child.path && isChildPathActive(location.pathname, child.path)),
    )
    if (parentWithActiveChild) {
      setOpenLabel(parentWithActiveChild.label)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname])

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
            {items.map((item) => {
              if (item.children) {
                const isOpen = openLabel === item.label
                const hasActiveChild = item.children.some(
                  (child) => child.path && isChildPathActive(location.pathname, child.path),
                )
                return (
                  <li key={item.label}>
                    <button
                      type="button"
                      aria-expanded={isOpen}
                      onClick={() => setOpenLabel((k) => (k === item.label ? null : item.label))}
                      className={cn(
                        'flex w-full items-center justify-between gap-3 rounded-sm px-3 py-2.5 text-sm font-medium transition-colors',
                        hasActiveChild ? 'text-white' : 'text-white/70 hover:bg-sidebar-hover-bg hover:text-white',
                      )}
                    >
                      <span className="flex items-center gap-3">
                        <item.icon size={18} />
                        {item.label}
                      </span>
                      <motion.span
                        animate={{ rotate: isOpen ? 180 : 0 }}
                        transition={{ duration: 0.2, ease: 'easeOut' }}
                      >
                        <ChevronDown size={16} />
                      </motion.span>
                    </button>

                    <AnimatePresence initial={false}>
                      {isOpen && (
                        <motion.ul
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2, ease: 'easeOut' }}
                          className="flex flex-col gap-1 overflow-hidden"
                        >
                          {item.children.map((child) => (
                            <li key={child.path}>
                              <NavLink
                                to={child.path!}
                                onClick={onCloseMobile}
                                className={({ isActive }) =>
                                  cn(
                                    'mt-1 flex items-center gap-3 rounded-sm py-2 pr-9 pl-3 text-sm font-medium transition-colors',
                                    isActive
                                      ? 'bg-sidebar-active-bg text-white'
                                      : 'text-white/60 hover:bg-sidebar-hover-bg hover:text-white',
                                  )
                                }
                              >
                                <child.icon size={16} />
                                {child.label}
                              </NavLink>
                            </li>
                          ))}
                        </motion.ul>
                      )}
                    </AnimatePresence>
                  </li>
                )
              }

              return (
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
              )
            })}
          </ul>
        </nav>
      </aside>
    </>
  )
}
