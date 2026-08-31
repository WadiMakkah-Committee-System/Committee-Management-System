import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuthStore } from '@/store/authStore'
import { AppShell } from '@/components/layout/AppShell'
import { ProtectedRoute } from '@/routes/ProtectedRoute'
import { LoginPage } from '@/features/auth/LoginPage'
import { UsersPage } from '@/features/users/UsersPage'
import { RolesPermissionsPage } from '@/features/roles/RolesPermissionsPage'
import { RoleDetailPage } from '@/features/roles/RoleDetailPage'
import { JobTitlesPage } from '@/features/jobTitles/JobTitlesPage'
import { DepartmentsPage } from '@/features/departments/DepartmentsPage'
import { DepartmentDetailPage } from '@/features/departments/DepartmentDetailPage'
import { CommitteeRequestsPage } from '@/features/committees/CommitteeRequestsPage'
import { CommitteeRequestDetailPage } from '@/features/committees/CommitteeRequestDetailPage'
import { CommitteesPage } from '@/features/committees/CommitteesPage'
import { CommitteeDetailPage } from '@/features/committees/CommitteeDetailPage'
import { MeetingsPage } from '@/features/meetings/MeetingsPage'
import { MeetingDetailPage } from '@/features/meetings/MeetingDetailPage'
import { ProfilePage } from '@/features/profile/ProfilePage'
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
    <AppBootstrap>
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        <Route element={<ProtectedRoute />}>
          <Route element={<AppShell />}>
            <Route path="/profile" element={<ProfilePage />} />

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

            {/* بدون anyPermission عمدًا — راجعي رأس MeetingsPage.tsx: التفويض
                هيكلي (رئيس/عضو اللجنة)، وليس صلاحية عامة بالكتالوج، فحجب
                المسار خلف صلاحية كالمعتاد يمنع أي رئيس/عضو لجنة بلا دور
                ادمن من الوصول لاجتماعاته الخاصة. */}
            <Route path="/meetings" element={<MeetingsPage />} />
            <Route path="/meetings/:meetingId" element={<MeetingDetailPage />} />

            <Route path="/" element={<Navigate to="/users" replace />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppBootstrap>
  )
}

export default App
