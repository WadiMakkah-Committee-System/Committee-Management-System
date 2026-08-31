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

/** نطاقات الوصول المدعومة — راجعي db/migrations/0014 وbackend/app/models/role.py. */
export type PermissionScope = 'own' | 'department' | 'all'

/** صلاحية دور معيّن، مع نطاق الوصول الفعلي الممنوح لها (مراجعة لاما 2026-08-30). */
export interface RolePermission extends Permission {
  scope: PermissionScope
}

export interface Role {
  role_id: string
  name: string
  description: string | null
  is_system: boolean
  is_super_admin: boolean
  created_at: string
  updated_at: string
  permissions: RolePermission[]
  permission_count: number
  user_count: number
}

export interface RoleCreatePayload {
  name: string
  description: string | null
  permission_codes: string[]
  /** {كود_الصلاحية: نطاقها} اختياري — أي كود غير مذكور يأخذ 'all' افتراضيًا. */
  permission_scopes?: Record<string, PermissionScope>
}

export interface RoleUpdatePayload {
  name?: string
  description?: string | null
  permission_codes?: string[]
  permission_scopes?: Record<string, PermissionScope>
}

export interface DepartmentManager {
  user_id: string
  first_name: string
  middle_name: string
  last_name: string
  email: string
}

export interface Department {
  dep_id: string
  name: string
  code: string | null
  description: string | null
  manager: DepartmentManager | null
  created_at: string
  updated_at: string
}

export interface JobTitle {
  job_title_id: string
  name: string
  created_at: string
  updated_at: string
}

export interface JobTitleCreatePayload {
  name: string
}

export interface JobTitleUpdatePayload {
  name: string
}

export interface User {
  user_id: string
  first_name: string
  middle_name: string
  last_name: string
  username: string
  email: string
  role: RoleSummary | null
  dep_id: string | null
  department: Department | null
  job_title_id: string | null
  job_title: JobTitle | null
  status: UserStatus
  must_change_password: boolean
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export interface UserDetail extends User {
  permissions: string[]
  /**
   * {كود_الصلاحية: نطاقها (own/department/all)} — مراجعة لاما 2026-08-31
   * (بلاغ خطأ): permissions وحدها (وجود/عدم) لا تكفي لإظهار/إخفاء
   * إجراءات مقيَّدة بنطاق بشكل صحيح (مثال: زر "إرجاع لمقدّم الطلب" بطلبات
   * تشكيل اللجان — نطاق department/all فقط). استخدمي scopeFor() من
   * @/lib/utils بدل قراءة هذا الحقل مباشرة.
   */
  permission_scopes: Record<string, PermissionScope>
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
  /** اختياري (مراجعة لاما 2026-08-30) — مستخدم بلا دور يُنشأ بنجاح. */
  role_id: string | null
  dep_id: string | null
  job_title_id: string | null
  status: UserStatus
}

export interface UserUpdatePayload {
  first_name?: string
  middle_name?: string
  last_name?: string
  email?: string
  role_id?: string
  dep_id?: string | null
  job_title_id?: string | null
}

export interface DepartmentCreatePayload {
  name: string
  code: string
  description: string | null
  manager_user_id: string
}

export interface DepartmentUpdatePayload {
  name?: string
  code?: string
  description?: string | null
  manager_user_id?: string
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

/**
 * أنواع وحدة "طلبات تشكيل اللجان" — مطابقة تمامًا لـ
 * backend/app/schemas/committee.py وbackend/app/models/committee_request.py
 * (Phase 2، مصحَّحة بـ PR #15). راجعي project_memory:
 * phase2-committee-formation-requests.md لآلة الحالة الكاملة والقرارات
 * الموثّقة قبل أي تعديل على هذه الأنواع.
 */
export type CommitteeRequestStatus =
  | 'draft'
  | 'submitted'
  | 'under_review'
  | 'returned'
  | 'pending_approval'
  | 'approved'
  | 'rejected'

export interface CommitteeMemberUser {
  user_id: string
  first_name: string
  middle_name: string
  last_name: string
  email: string
}

export interface CommitteeFormationRequest {
  request_id: string
  committee_name: string
  statement: string | null
  start_date: string
  end_date: string
  status: CommitteeRequestStatus
  requester: CommitteeMemberUser
  proposed_members: CommitteeMemberUser[]
  chair_user_id: string | null
  chair: CommitteeMemberUser | null
  /** معرّف اللجنة المعتمدة الناتجة عن هذا الطلب — null قبل الاعتماد (approved فقط). */
  committee_id: string | null
  rejection_reason: string | null
  return_reason: string | null
  created_at: string
  updated_at: string
}

export interface CommitteeFormationRequestCreatePayload {
  committee_name: string
  statement: string | null
  start_date: string
  end_date: string
  proposed_member_ids: string[]
  chair_user_id: string
}

export interface CommitteeFormationRequestUpdatePayload {
  committee_name?: string
  statement?: string | null
  start_date?: string
  end_date?: string
  proposed_member_ids?: string[]
  chair_user_id?: string
}

/** اللجنة المعتمدة رسميًا — سطح قراءة بسيط فقط (Phase 5 لاحقًا لإدارتها الكاملة). */
export interface Committee {
  committee_id: string
  name: string
  statement: string | null
  start_date: string
  end_date: string
  source_request_id: string
  members: CommitteeMemberUser[]
  chair_user_id: string | null
  chair: CommitteeMemberUser | null
  created_at: string
}

/**
 * سطر تعريفي خفيف — موظف من إدارة المستخدم الحالي عضو بلجنة رئيسها من
 * إدارة ثانية (أو بدون إدارة معروفة). مراجعة لاما 2026-08-30 (الجولة
 * الثالثة). عمدًا بدون بقية تفاصيل اللجنة — راجعي
 * backend/app/schemas/committee.py::DepartmentMemberElsewhereOut.
 */
export interface DepartmentMemberElsewhere {
  member: CommitteeMemberUser
  committee_id: string
  committee_name: string
  department_name: string | null
}
