import { useState } from 'react'
import { ShieldQuestion, Users as UsersIcon } from 'lucide-react'
import { Tabs } from '@/components/ui/Tabs'
import { useAuthStore } from '@/store/authStore'
import { RolesPermissionsTab } from '@/features/roles/RolesPermissionsTab'
import { UsersTab } from './UsersTab'

type TabKey = 'users' | 'roles'

/**
 * الحاوية العلوية لشاشة "إدارة المستخدمين والإدارات" — تبويبان:
 * "المستخدمون" (متاح لمن يملك صلاحية users.view) و"الأدوار والصلاحيات"
 * (مقصور على is_super_admin فقط، لأن منح/تعديل الصلاحيات نفسها محصور
 * بالدور الجذري في الباك-إند — انظر core/dependencies.require_super_admin).
 */
export function UserManagementPage() {
  const user = useAuthStore((s) => s.user)
  const isSuperAdmin = !!user?.role.is_super_admin
  const canViewUsers = isSuperAdmin || !!user?.permissions.includes('users.view')

  const [tab, setTab] = useState<TabKey>(isSuperAdmin ? 'roles' : 'users')

  const items = [
    ...(isSuperAdmin
      ? [{ key: 'roles', label: 'الأدوار والصلاحيات', icon: <ShieldQuestion size={15} /> }]
      : []),
    ...(canViewUsers ? [{ key: 'users', label: 'المستخدمون', icon: <UsersIcon size={15} /> }] : []),
  ]

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-bold text-text-primary">المستخدمون</h1>
        <p className="mt-1 text-sm text-text-muted">إدارة حسابات المستخدمين، وأدوارهم وصلاحياتهم في النظام</p>
      </div>

      {items.length > 1 && <Tabs items={items} value={tab} onChange={(k) => setTab(k as TabKey)} />}

      {tab === 'users' && canViewUsers && <UsersTab />}
      {tab === 'roles' && isSuperAdmin && <RolesPermissionsTab />}
    </div>
  )
}
