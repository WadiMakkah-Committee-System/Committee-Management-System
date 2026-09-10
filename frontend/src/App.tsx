import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuthStore } from '@/store/authStore'
import { AppShell } from '@/components/layout/AppShell'
import { SplashScreen } from '@/components/layout/SplashScreen'
import { ProtectedRoute } from '@/routes/ProtectedRoute'
import { LoginPage } from '@/features/auth/LoginPage'
import { UsersPage } from '@/features/users/UsersPage'
import { RolesPermissionsPage } from '@/features/roles/RolesPermissionsPage'
import { RoleDetailPage } from '@/features/roles/RoleDetailPage'
import { JobTitlesPage } from '@/features/jobTitles/JobTitlesPage'
import { DepartmentsPage } from '@/features/departments/DepartmentsPage'
import { DashboardPage } from '@/features/dashboard/DashboardPage'
import { DepartmentDetailPage } from '@/features/departments/DepartmentDetailPage'
import { CommitteeRequestsPage } from '@/features/committees/CommitteeRequestsPage'
import { CommitteeRequestDetailPage } from '@/features/committees/CommitteeRequestDetailPage'
import { CommitteesPage } from '@/features/committees/CommitteesPage'
import { CommitteeDetailPage } from '@/features/committees/CommitteeDetailPage'
import { DocumentsPage } from '@/features/documents/DocumentsPage'
import { DocumentDetailPage } from '@/features/documents/DocumentDetailPage'
import { DocumentsSmartSearchPage } from '@/features/documents/DocumentsSmartSearchPage'
import { MeetingsPage } from '@/features/meetings/MeetingsPage'
import { MeetingDetailPage } from '@/features/meetings/MeetingDetailPage'
import { DecisionsPage } from '@/features/decisions/DecisionsPage'
import { DecisionDetailPage } from '@/features/decisions/DecisionDetailPage'
import { TasksPage } from '@/features/tasks/TasksPage'
import { TaskDetailPage } from '@/features/tasks/TaskDetailPage'
import { ProfilePage } from '@/features/profile/ProfilePage'
import { NotificationsPage } from '@/features/notifications/NotificationsPage'
import { PageSpinner } from '@/components/ui/Spinner'
import { usersKeys } from '@/hooks/useUsers'
import * as usersApi from '@/api/users'

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
    <SplashScreen>
      <AppBootstrap>
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
      </AppBootstrap>
    </SplashScreen>
  )
}

export default App
