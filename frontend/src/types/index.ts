/**
 * الهدف: أنواع TypeScript المطابقة تمامًا لـ Pydantic Schemas في الباك-إند
 * (backend/app/schemas/user.py, department.py, auth.py) — مصدر واحد للحقيقة
 * حول شكل بيانات الـ API، لتفادي أي اختلاف بين الطرفين.
 */

export type UserRole =
  | 'super_admin'
  | 'admin'
  | 'executive_president'
  | 'executive_office_manager'
  | 'executive_office_secretary'

export type UserStatus = 'active' | 'suspended'

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
  role: UserRole
  dep_id: string | null
  department: Department | null
  status: UserStatus
  must_change_password: boolean
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export interface UserCreatePayload {
  first_name: string
  middle_name: string
  last_name: string
  username: string
  email: string
  password: string
  role: UserRole
  dep_id: string | null
}

export interface UserUpdatePayload {
  first_name?: string
  middle_name?: string
  last_name?: string
  email?: string
  role?: UserRole
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

/** شكل خطأ موحّد قادم من FastAPI (HTTPException.detail) أو Pydantic (422). */
export interface ApiErrorShape {
  detail:
    | string
    | { msg: string; loc?: (string | number)[] }[]
}
