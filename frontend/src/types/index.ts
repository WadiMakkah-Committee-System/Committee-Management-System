/**
 * الهدف: أنواع TypeScript المطابقة تمامًا لـ Pydantic Schemas في الباك-إند
 * (backend/app/schemas/user.py, department.py, role.py, audit_log.py) — مصدر
 * واحد للحقيقة حول شكل بيانات الـ API، لتفادي أي اختلاف بين الطرفين.
 */

export type UserStatus = 'active' | 'suspended'

/** أسماء الأدوار النظامية الخمسة الثابتة (is_system=true) — بقية الأدوار مخصَّصة وتُنشأ من الواجهة. */
export type SystemRoleName =
  | 'super_admin'
  | 'admin'
  | 'executive_president'
  | 'executive_office_manager'
  | 'executive_office_secretary'

export interface RoleSummary {
  role_id: string
  name: string
  description: string | null
  is_super_admin: boolean
}

export interface Permission {
  permission_id: string
  code: string
  category: string
  label_ar: string
  sort_order: number
  is_enforced: boolean
}

export interface Role {
  role_id: string
  name: string
  description: string | null
  is_system: boolean
  is_super_admin: boolean
  created_at: string
  updated_at: string
  permissions: Permission[]
  permission_count: number
  user_count: number
}

export interface RoleCreatePayload {
  name: string
  description: string | null
  permission_codes: string[]
}

export interface RoleUpdatePayload {
  name?: string
  description?: string | null
  permission_codes?: string[]
}

export interface Department {
  dep_id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface User {
  user_id: string
  first_name: string
  middle_name: string
  last_name: string
  username: string
  email: string
  role: RoleSummary
  dep_id: string | null
  department: Department | null
  status: UserStatus
  must_change_password: boolean
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export interface UserDetail extends User {
  permissions: string[]
}

export interface DepartmentDetail extends Department {
  member_count: number
  members: User[]
}

export interface UserCreatePayload {
  first_name: string
  middle_name: string
  last_name: string
  username: string
  email: string
  password: string
  role_id: string
  dep_id: string | null
  status: UserStatus
}

export interface UserUpdatePayload {
  first_name?: string
  middle_name?: string
  last_name?: string
  email?: string
  role_id?: string
  dep_id?: string | null
}

export interface DepartmentCreatePayload {
  name: string
  description: string | null
}

export interface DepartmentUpdatePayload {
  name?: string
  description?: string | null
}

export interface LoginPayload {
  username: string
  password: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  must_change_password: boolean
}

export interface AuditLogEntry {
  log_id: string
  actor_name: string | null
  action_type: string
  target_type: string
  target_id: string
  metadata: Record<string, unknown> | null
  created_at: string
}

export interface AuditLogPage {
  items: AuditLogEntry[]
  total: number
  limit: number
  offset: number
}

/** شكل خطأ موحّد قادم من FastAPI (HTTPException.detail) أو Pydantic (422). */
export interface ApiErrorShape {
  detail:
    | string
    | { msg: string; loc?: (string | number)[] }[]
}
