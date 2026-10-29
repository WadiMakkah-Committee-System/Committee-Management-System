import { useEffect, useMemo, useState } from 'react'
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
  ShieldQuestion,
  UserRound,
  Briefcase,
  ChevronDown,
  ClipboardList,
  CheckCircle2,
  FileSignature,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import wadiMakkahMark from '@/assets/wadi-makkah-mark.png'
import { BrandWave } from '@/components/brand/BrandWave'

interface NavItem {
  label: string
  icon: LucideIcon
  path?: string
  /** يكفي امتلاك واحدة من هذه الصلاحيات لإظهار العنصر — حتى لو كان المستخدم super_admin. */
  requiredPermission?: string[]
  /** يقيّد ظهور العنصر بدور الجذر (is_super_admin) فقط. */
  superAdminOnly?: boolean
  comingSoon?: boolean
  /** عناصر فرعية — يتحول العنصر لقائمة قابلة للتوسيع/الانكماش بدل رابط مباشر. */
  children?: NavItem[]
}

/** ترتيب التنقل الموثّق في §15 — العناصر غير المبنية بعد تظهر معطّلة ("قريبًا") بدل إخفائها. */
const NAV_ITEMS: NavItem[] = [
  { label: 'لوحة التحكم', icon: LayoutDashboard, path: '/dashboard' },
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
        requiredPermission: ['committees.view'],
      },
    ],
  },
  { label: 'الاجتماعات', icon: CalendarDays, path: '/meetings', requiredPermission: ['meetings.view'] },
  // قسم مستقل بالقائمة الجانبية (طلب لاما 2026-09-08) — لا علاقة له بمسار
  // "الاجتماعات ← اختيار اجتماع ← زر محضر" القائم أصلًا بصفحة تفاصيل
  // الاجتماع (أُبقي كما هو تمامًا بناءً على طلبها الصريح). راجعي
  // MinutesListPage.tsx وhasMinutesMembershipBypass بـProtectedRoute.tsx.
  { label: 'المحاضر', icon: FileSignature, path: '/minutes', requiredPermission: ['minutes.view'] },
  { label: 'المهام', icon: ListChecks, path: '/tasks', requiredPermission: ['tasks.view'] },
  { label: 'القرارات', icon: Gavel, path: '/decisions', requiredPermission: ['decisions.view'] },
  {
    // كانت "الوثائق" قائمة قابلة للتوسّع بعنصرين فرعيين (كل الوثائق /
    // تصنيفات الوثائق) — بعد دمج إدارة التصنيفات داخل صفحة الوثائق نفسها
    // كنافذة (راجعي DocumentCategoriesModal.tsx)، صار عنصرًا فرعيًا واحدًا
    // فقط فلا داعي لقائمة فرعية بعد الآن؛ رابط مباشر أبسط للمستخدم.
    label: 'الوثائق',
    icon: FileText,
    path: '/documents',
    requiredPermission: ['documents.view', 'documents.search'],
  },
  {
    label: 'البحث الذكي',
    icon: Sparkles,
    path: '/documents/search',
    requiredPermission: ['documents.search_all_agent'],
  },
  { label: 'الإشعارات', icon: Bell, path: '/notifications' },
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
 *  ويُҳقط العنصر الأب بالكامل إذا لم يتبقَّ له أي عنصر فرعي ظاهر. */
function filterNavItem(item: NavItem, isSuperAdmin: boolean, permissions: string[]): NavItem | null {
  if (item.children) {
    const children = item.children
      .map((child) => filterNavItem(child, isSuperAdmin, permissions))
      .filter((child): child is NavItem => child !== null)
    if (children.length === 0) return null
    return { ...item, children }
  }
  if (item.superAdminOnly && !isSuperAdmin) return null
  if (item.requiredPermission && !item.requiredPermission.some((code) => permissions.includes(code))) {
    return null
  }
  return item
}

export function Sidebar({ mobileOpen, onCloseMobile }: { mobileOpen: boolean; onCloseMobile: () => void }) {
  const user = useAuthStore((s) => s.user)
  const isSuperAdmin = !!user?.role?.is_super_admin
  // بلاغ لاما 2026-09-01: عضو لجنة (رئيس/عضو) قد يملك وصولًا فعليًا لقسم
  // "اللجان" عبر عضوية اللجنة نفسها فقط، بدون أي صلاحية committees.view
  // على مستوى System Role — نسخة محلية فقط لفلترة القائمة الجانبية (لا
  // تُكتب على user.permissions الفعلية، حتى لا تؤثر على أجزاء أخرى من
  // الواجهة تعتمد عليها كصلاحية نظامية حقيقية، مثل قسم "موظفو إدارتي بلجان
  // أخرى" بصفحة اللجان). راجعي has_committee_membership_access بالنوع
  // UserDetail وProtectedRoute.tsx لنفس المنطق على مستوى المسار.
  const permissions = useMemo(() => {
    let base = user?.permissions ?? []
    if (user?.has_committee_membership_access && !base.includes('committees.view')) {
      base = [...base, 'committees.view']
    }
    // قرار توحيد سلوك القائمة الجانبية بين "اللجان" و"الاجتماعات"
    // (2026-09-01): نفس فكرة committees.view أعلاه بالضبط، لكن بحقل أبسط
    // (مجرّد عضوية بأي لجنة، بدون فحص كود صلاحية داخل دور اللجنة — راجعي
    // has_any_committee_membership بـtypes/index.ts للفرق الدقيق).
    if (user?.has_any_committee_membership && !base.includes('meetings.view')) {
      base = [...base, 'meetings.view']
    }
    // نفس المبدأ لوحدة "القرارات" — راجعي نفس الملاحظة أعلاه.
    if (user?.has_any_committee_membership && !base.includes('decisions.view')) {
      base = [...base, 'decisions.view']
    }
    // نفس المبدأ لوحدة "المهام" — راجعي نفس الملاحظة أعلاه.
    if (user?.has_any_committee_membership && !base.includes('tasks.view')) {
      base = [...base, 'tasks.view']
    }
    // نفس المبدأ لوحدة "المحاضر" (طلب لاما 2026-09-08) — راجعي نفس الملاحظة أعلاه.
    if (user?.has_any_committee_membership && !base.includes('minutes.view')) {
      base = [...base, 'minutes.view']
    }
    return base
  }, [user])
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
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="fixed inset-0 z-30 bg-[#0a1430]/50 backdrop-blur-[2px] lg:hidden"
            onClick={onCloseMobile}
          />
        )}
      </AnimatePresence>
      <aside
        className={cn(
          'fixed inset-y-0 right-0 z-40 flex w-[17rem] shrink-0 flex-col overflow-hidden transition-transform duration-500 ease-out-expo lg:sticky lg:top-0 lg:h-svh lg:translate-x-0',
          'bg-[linear-gradient(180deg,var(--sidebar-bg)_0%,var(--sidebar-bg-2)_100%)] shadow-2xl lg:shadow-none',
          mobileOpen ? 'translate-x-0' : 'translate-x-full lg:translate-x-0',
        )}
      >
        {/* شريط الطيف + توهّج خافت بلون الهوية أعلى القائمة */}
        <div aria-hidden className="brand-stripe h-[3px] w-full shrink-0" />
        <div
          aria-hidden
          className="pointer-events-none absolute -top-24 -right-20 h-64 w-64 rounded-full bg-[var(--wm-cyan)] opacity-[0.10] blur-3xl"
        />

        <div className="relative flex h-20 items-center gap-3 px-5">
          <img src={wadiMakkahMark} alt="شعار وادي مكة" className="h-9 w-auto shrink-0" />
          <div className="leading-tight">
            <p className="text-sm font-bold text-white">وادي مكة للتقنية</p>
            <p className="mt-0.5 text-[11px] text-white/55">إدارة اللجان والاجتماعات</p>
          </div>
        </div>

        <div aria-hidden className="mx-5 mb-2 h-px bg-gradient-to-l from-transparent via-white/15 to-transparent" />

        <nav className="relative flex-1 overflow-y-auto px-3 py-2 [scrollbar-width:thin]">
          <ul className="flex flex-col gap-0.5">
            {items.map((item, index) => {
              if (item.children) {
                const isOpen = openLabel === item.label
                const hasActiveChild = item.children.some(
                  (child) => child.path && isChildPathActive(location.pathname, child.path),
                )
                return (
                  <motion.li
                    key={item.label}
                    initial={{ opacity: 0, x: 12 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.45, delay: 0.04 * index, ease: [0.16, 1, 0.3, 1] }}
                  >
                    <button
                      type="button"
                      aria-expanded={isOpen}
                      onClick={() => setOpenLabel((k) => (k === item.label ? null : item.label))}
                      className={cn(
                        'group flex w-full items-center justify-between gap-3 rounded-sm px-3 py-2.5 text-sm font-medium transition-colors duration-200',
                        hasActiveChild ? 'text-white' : 'text-white/70 hover:bg-sidebar-hover-bg hover:text-white',
                      )}
                    >
                      <span className="flex items-center gap-3">
                        <item.icon
                          size={18}
                          className={cn(
                            'transition-transform duration-300 group-hover:scale-110',
                            hasActiveChild && 'text-[var(--wm-cyan)]',
                          )}
                        />
                        {item.label}
                      </span>
                      <motion.span
                        animate={{ rotate: isOpen ? 180 : 0 }}
                        transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                        className="text-white/50"
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
                          transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                          className="relative mr-[1.35rem] flex flex-col gap-0.5 overflow-hidden border-r border-white/10 pr-2"
                        >
                          {item.children.map((child) => (
                            <li key={child.path}>
                              <NavLink
                                to={child.path!}
                                onClick={onCloseMobile}
                                className={({ isActive }) =>
                                  cn(
                                    'relative mt-0.5 flex items-center gap-3 rounded-sm py-2 pr-3 pl-3 text-[13px] font-medium transition-colors duration-200',
                                    isActive ? 'text-white' : 'text-white/60 hover:bg-sidebar-hover-bg hover:text-white',
                                  )
                                }
                              >
                                {({ isActive }) => (
                                  <>
                                    {isActive && <ActivePill />}
                                    <child.icon size={16} className="relative" />
                                    <span className="relative">{child.label}</span>
                                  </>
                                )}
                              </NavLink>
                            </li>
                          ))}
                        </motion.ul>
                      )}
                    </AnimatePresence>
                  </motion.li>
                )
              }

              return (
                <motion.li
                  key={item.label}
                  initial={{ opacity: 0, x: 12 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.45, delay: 0.04 * index, ease: [0.16, 1, 0.3, 1] }}
                >
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
                          'group relative flex items-center gap-3 rounded-sm px-3 py-2.5 text-sm font-medium transition-colors duration-200',
                          isActive ? 'text-white' : 'text-white/70 hover:bg-sidebar-hover-bg hover:text-white',
                        )
                      }
                    >
                      {({ isActive }) => (
                        <>
                          {isActive && <ActivePill />}
                          <item.icon
                            size={18}
                            className={cn(
                              'relative transition-transform duration-300 group-hover:scale-110',
                              isActive && 'text-[var(--wm-cyan)]',
                            )}
                          />
                          <span className="relative">{item.label}</span>
                        </>
                      )}
                    </NavLink>
                  )}
                </motion.li>
              )
            })}
          </ul>
        </nav>

        {/* موجة الهوية أسفل القائمة — زخرفة خافتة ثابتة الموقع */}
        <div aria-hidden className="pointer-events-none relative shrink-0 overflow-hidden opacity-[0.55]">
          <BrandWave height={90} speed={0.8} className="translate-y-3" />
          <div className="absolute inset-0 bg-gradient-to-b from-[var(--sidebar-bg-2)] via-transparent to-transparent" />
        </div>
      </aside>
    </>
  )
}

/**
 * مؤشر العنصر النشط — "حبة" تنزلق بين العناصر بحركة نابضية (layoutId)،
 * مع خط جانبي بلون السماوي من الهوية. مستوحى من انتقالات Flip بالمواقع
 * المرجعية، لكن عبر framer-motion الموجودة أصلًا.
 */
function ActivePill() {
  return (
    <motion.span
      layoutId="sidebar-active-pill"
      transition={{ type: 'spring', stiffness: 420, damping: 36, mass: 0.9 }}
      className="absolute inset-0 rounded-sm bg-[linear-gradient(270deg,rgba(36,186,233,0.22),rgba(16,94,167,0.12))] ring-1 ring-inset ring-white/10"
    >
      <span className="absolute inset-y-1.5 right-0 w-[3px] rounded-full bg-[var(--wm-cyan)] shadow-[0_0_12px_var(--wm-cyan)]" />
    </motion.span>
  )
}
