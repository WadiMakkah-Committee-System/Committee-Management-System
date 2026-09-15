import { Suspense, lazy, useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuthStore } from '@/store/authStore'
import { AppShell } from '@/components/layout/AppShell'
import { ProtectedRoute } from '@/routes/ProtectedRoute'
import { PageSpinner } from '@/components/ui/Spinner'
import { usersKeys } from '@/hooks/useUsers'
import * as usersApi from '@/api/users'

/**
 * إصلاح أداء (تحليل.pdf — Medium severity، المرحلة الخامسة، بعد المراحل
 * 1-4 المُنفَّذة سابقًا): تقسيم الكود بمستوى الصفحات (Route-level code
 * splitting) — لم يكن مستخدَمًا إطلاقًا قبل هذا التعديل. كل صفحات
 * التطبيق الـ24 كانت مستوردة Statically بأعلى App.tsx (import عادي)،
 * فتنتهي كلها ضمن حزمة JS أولية واحدة ضخمة يجب تحميلها كاملة حتى لو
 * المستخدمة فتحت صفحة تسجيل الدخول فقط أو صفحة واحدة بسيطة كـ"الملف
 * الشخصي".
 *
 * الحل: كل مكوّن صفحة أدناه يُستورَد الآن عبر React.lazy(() =>
 * import(...)) بدل import ثابت بالأعلى — Vite يتكفّل تلقائيًا بتحويل كل
 * import() ديناميكي كهذا إلى حزمة (chunk) منفصلة تُحمَّل فقط عند أول
 * زيارة فعلية لمسارها، بلا أي إعداد إضافي بـvite.config. غلاف <Suspense>
 * واحد فقط حول <Routes> بالأسفل يكفي (يلتقط أي تعليق Lazy داخل الشجرة
 * كاملة، حتى عبر Outlet بـAppShell/ProtectedRoute اللي بقيا Static عمدًا
 * لأنهما هيكل التوجيه نفسه لا محتوى صفحة). PageSpinner نفسه المستخدَم
 * أصلًا بـAppBootstrap بالأسفل تمامًا — فلا فرق بصري يُذكر عن السلوك
 * الحالي أثناء التحميل الأول (Cold)، وبعده أي عودة لصفحة زارتها المستخدمة
 * سابقًا تكون فورية كليًا (Cache المتصفح الطبيعي على حزمة تلك الصفحة).
 *
 * ملاحظة تقنية: كل صفحات هذا الملف مُصدَّرة بتصدير مُسمّى (export
 * function X)، لا Default export — لذا .then(m => ({ default: m.X }))
 * بكل سطر أدناه (النمط الموثّق رسميًا بـReact لتحويل تصدير مُسمّى إلى
 * الشكل اللي يتوقعه React.lazy). تحققت من اسم كل تصدير فعليًا بالكود
 * الحالي (grep على "export function"/"export const" بكل ملف) قبل كتابة
 * هذا التحويل — تطابق تام بلا استثناء. تحويل ميكانيكي بحت لا يمس أي منطق
 * توجيه/صلاحيات/عرض — نفس بنية <Routes>/<Route> بالأسفل حرفيًا بلا أي
 * تغيير.
 */
const LoginPage = lazy(() => import('@/features/auth/LoginPage').then((m) => ({ default: m.LoginPage })))
const UsersPage = lazy(() => import('@/features/users/UsersPage').then((m) => ({ default: m.UsersPage })))
const RolesPermissionsPage = lazy(() =>
  import('@/features/roles/RolesPermissionsPage').then((m) => ({ default: m.RolesPermissionsPage })),
)
const RoleDetailPage = lazy(() =>
  import('@/features/roles/RoleDetailPage').then((m) => ({ default: m.RoleDetailPage })),
)
const JobTitlesPage = lazy(() =>
  import('@/features/jobTitles/JobTitlesPage').then((m) => ({ default: m.JobTitlesPage })),
)
const DepartmentsPage = lazy(() =>
  import('@/features/departments/DepartmentsPage').then((m) => ({ default: m.DepartmentsPage })),
)
const DashboardPage = lazy(() =>
  import('@/features/dashboard/DashboardPage').then((m) => ({ default: m.DashboardPage })),
)
const DepartmentDetailPage = lazy(() =>
  import('@/features/departments/DepartmentDetailPage').then((m) => ({ default: m.DepartmentDetailPage })),
)
const CommitteeRequestsPage = lazy(() =>
  import('@/features/committees/CommitteeRequestsPage').then((m) => ({ default: m.CommitteeRequestsPage })),
)
const CommitteeRequestDetailPage = lazy(() =>
  import('@/features/committees/CommitteeRequestDetailPage').then((m) => ({
    default: m.CommitteeRequestDetailPage,
  })),
)
const CommitteesPage = lazy(() =>
  import('@/features/committees/CommitteesPage').then((m) => ({ default: m.CommitteesPage })),
)
const CommitteeDetailPage = lazy(() =>
  import('@/features/committees/CommitteeDetailPage').then((m) => ({ default: m.CommitteeDetailPage })),
)
const DocumentsPage = lazy(() =>
  import('@/features/documents/DocumentsPage').then((m) => ({ default: m.DocumentsPage })),
)
const DocumentDetailPage = lazy(() =>
  import('@/features/documents/DocumentDetailPage').then((m) => ({ default: m.DocumentDetailPage })),
)
const DocumentsSmartSearchPage = lazy(() =>
  import('@/features/documents/DocumentsSmartSearchPage').then((m) => ({
    default: m.DocumentsSmartSearchPage,
  })),
)
const MeetingsPage = lazy(() =>
  import('@/features/meetings/MeetingsPage').then((m) => ({ default: m.MeetingsPage })),
)
const MeetingDetailPage = lazy(() =>
  import('@/features/meetings/MeetingDetailPage').then((m) => ({ default: m.MeetingDetailPage })),
)
const MeetingMinutesPage = lazy(() =>
  import('@/features/meetings/MeetingMinutesPage').then((m) => ({ default: m.MeetingMinutesPage })),
)
const MinutesListPage = lazy(() =>
  import('@/features/meetings/MinutesListPage').then((m) => ({ default: m.MinutesListPage })),
)
const DecisionsPage = lazy(() =>
  import('@/features/decisions/DecisionsPage').then((m) => ({ default: m.DecisionsPage })),
)
const DecisionDetailPage = lazy(() =>
  import('@/features/decisions/DecisionDetailPage').then((m) => ({ default: m.DecisionDetailPage })),
)
const TasksPage = lazy(() => import('@/features/tasks/TasksPage').then((m) => ({ default: m.TasksPage })))
const TaskDetailPage = lazy(() =>
  import('@/features/tasks/TaskDetailPage').then((m) => ({ default: m.TaskDetailPage })),
)
const ProfilePage = lazy(() =>
  import('@/features/profile/ProfilePage').then((m) => ({ default: m.ProfilePage })),
)
const NotificationsPage = lazy(() =>
  import('@/features/notifications/NotificationsPage').then((m) => ({ default: m.NotificationsPage })),
)

/**
 * عند تحديث الصفحة يوجد accessToken في التخزين لكن user في الحالة يكون
 * فارغًا مؤقتًا — هذا المكوّن يعيد جلب /users/me مرة واحدة عشان يملأ بيانات
 * المستخدم (تُستخدم في الـ Sidebar/Topbar وقيود الأدوار) قبل عرض التطبيق.
 */
function AppBootstrap({ children }: { children: React.ReactNode }) {
  const accessToken = useAuthStore((s) => s.accessToken)
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)
  const logout = useAuthStore((s) => s.logout)
  const [ready, setReady] = useState(!accessToken || !!user)

  const { data, isError } = useQuery({
    queryKey: usersKeys.me,
    queryFn: usersApi.fetchMe,
    enabled: !!accessToken && !user,
  })

  useEffect(() => {
    if (data) {
      setUser(data)
      setReady(true)
    }
  }, [data, setUser])

  useEffect(() => {
    if (isError) {
      logout()
      setReady(true)
    }
  }, [isError, logout])

  if (!ready) return <PageSpinner />
  return <>{children}</>
}

function App() {
  return (
    <AppBootstrap>
      <Suspense fallback={<PageSpinner />}>
        <Routes>
        <Route path="/login" element={<LoginPage />} />

        <Route element={<ProtectedRoute />}>
          <Route element={<AppShell />}>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/notifications" element={<NotificationsPage />} />

            <Route element={<ProtectedRoute anyPermission={['users.view']} />}>
              <Route path="/users" element={<UsersPage />} />
            </Route>

            <Route element={<ProtectedRoute superAdminOnly />}>
              <Route path="/users/roles" element={<RolesPermissionsPage />} />
              <Route path="/users/roles/:roleId" element={<RoleDetailPage />} />
            </Route>

            <Route element={<ProtectedRoute anyPermission={['job_titles.view']} />}>
              <Route path="/users/job-titles" element={<JobTitlesPage />} />
            </Route>

            <Route element={<ProtectedRoute anyPermission={['departments.view']} />}>
              <Route path="/departments" element={<DepartmentsPage />} />
              <Route path="/departments/:depId" element={<DepartmentDetailPage />} />
            </Route>

            <Route
              element={
                <ProtectedRoute anyPermission={['committees.request.create', 'committees.request.view']} />
              }
            >
              <Route path="/committees/requests" element={<CommitteeRequestsPage />} />
              <Route path="/committees/requests/:requestId" element={<CommitteeRequestDetailPage />} />
            </Route>

            <Route element={<ProtectedRoute anyPermission={['committees.view']} />}>
              <Route path="/committees/approved" element={<CommitteesPage />} />
              <Route path="/committees/approved/:committeeId" element={<CommitteeDetailPage />} />
            </Route>

            {/* راوت البحث الذكي بصلاحية منفصلة (documents.search_all_agent) — قبل
                راوت /documents/:documentId عشان ما يتلخبط الترتيب مع مسار
                حرفي مستقبلي، بنفس مبدأ /publish-targets قبل /{document_id}
                بالباك-إند. */}
            <Route element={<ProtectedRoute anyPermission={['documents.search_all_agent']} />}>
              <Route path="/documents/search" element={<DocumentsSmartSearchPage />} />
            </Route>

            <Route element={<ProtectedRoute anyPermission={['documents.view', 'documents.search']} />}>
              <Route path="/documents" element={<DocumentsPage />} />
              <Route path="/documents/:documentId" element={<DocumentDetailPage />} />
            </Route>
            {/* قرار توحيد سلوك القائمة الجانبية بين "اللجان" و"الاجتماعات"
                (2026-09-01): نفس نمط committees.view تمامًا — anyPermission
                هنا يمر لمن يملك meetings.view نظاميًا (ادمن/سوبر أدمن)،
                وProtectedRoute.tsx يحتوي بديلًا (hasMeetingsMembershipBypass)
                لأي عضو/رئيس لجنة عبر has_any_committee_membership. */}
            <Route element={<ProtectedRoute anyPermission={['meetings.view']} />}>
              <Route path="/meetings" element={<MeetingsPage />} />
              <Route path="/meetings/:meetingId" element={<MeetingDetailPage />} />
            </Route>

            {/* قسم "المحاضر" المستقل بالقائمة الجانبية (طلب لاما 2026-09-08،
                وفصل تام لاحق 2026-09-09: "قسم المحاضر يجب أن يكون وحدة
                مستقلة مرتبطة بالاجتماع فقط كمرجع") — مسار صفحة المحضر
                التفصيلية نُقل من /meetings/:meetingId/minutes إلى
                /minutes/:meetingId عمدًا: قبل النقل كان الاعتماد على
                بادئة /meetings يجعل NavLink بالسايد بار (Sidebar.tsx، بلا
                خاصية end) يُفعّل "الاجتماعات" بدل "المحاضر" أثناء عرض
                صفحة المحضر فعليًا — وهذا بالضبط ما بدا وكأن قسم المحاضر
                "جزء من" قسم الاجتماعات رغم أنه واجهة Lovable مستقلة كليًا.
                كما كان محميًا بصلاحية meetings.view بدل minutes.view، وهو
                خطأ صلاحيات إضافي بحد ذاته. راجعي hasMinutesMembershipBypass
                بـProtectedRoute.tsx وSidebar.tsx. */}
            <Route element={<ProtectedRoute anyPermission={['minutes.view']} />}>
              <Route path="/minutes" element={<MinutesListPage />} />
              <Route path="/minutes/:meetingId" element={<MeetingMinutesPage />} />
            </Route>

            {/* نفس نمط الاجتماعات أعلاه بالضبط — راجعي hasDecisionsMembershipBypass بـProtectedRoute.tsx. */}
            <Route element={<ProtectedRoute anyPermission={['decisions.view']} />}>
              <Route path="/decisions" element={<DecisionsPage />} />
              <Route path="/decisions/:decisionId" element={<DecisionDetailPage />} />
            </Route>

            {/* نفس نمط القرارات أعلاه بالضبط — راجعي hasTasksMembershipBypass بـProtectedRoute.tsx. */}
            <Route element={<ProtectedRoute anyPermission={['tasks.view']} />}>
              <Route path="/tasks" element={<TasksPage />} />
              <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
            </Route>

            {/* SRS حرفيًا: "توجيه المستخدم بعد تسجيل الدخول للوحة التحكم
                المناسبة لدوره وصلاحياته" — بلا حاجة لصلاحية معيّنة (راجعي
                رأس DashboardPage.tsx). */}
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AppBootstrap>
  )
}

export default App
