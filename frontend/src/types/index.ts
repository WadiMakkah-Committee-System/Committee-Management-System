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

/** 'system' لصلاحيات System Roles العادية، أو 'committee' لصلاحيات "أدوار اللجان" (راجعي db/migrations/0016). */
export type PermissionKind = 'system' | 'committee'

export interface Permission {
  permission_id: string
  code: string
  category: string
  label_ar: string
  sort_order: number
  is_enforced: boolean
  kind: PermissionKind
}

/** نطاقات الوصول المدعومة — راجعي db/migrations/0014 وbackend/app/models/role.py. */
export type PermissionScope = 'own' | 'department' | 'all'

/** صلاحية دور معيّن، مع نطاق الوصول الفعلي الممنوح لها (مراجعة لاما 2026-08-30). */
export interface RolePermission extends Permission {
  scope: PermissionScope
}

/** 'user' لدور نظامي عادي (يظهر عند إنشاء مستخدم)، أو 'committee' لـ"رئيس اللجنة"/"عضو اللجنة" (لا يظهر هناك إطلاقًا). */
export type RoleKind = 'user' | 'committee'

/** 'chair'/'member' لدوري اللجان الثابتين فقط، وnull لكل الأدوار النظامية. */
export type CommitteeRoleSlug = 'chair' | 'member' | null

export interface Role {
  role_id: string
  name: string
  description: string | null
  is_system: boolean
  is_super_admin: boolean
  kind: RoleKind
  committee_role_slug: CommitteeRoleSlug
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
  /**
   * مراجعة لاما 2026-09-01 (بلاغ خطأ): true لو يملك المستخدم صلاحية
   * committees.view ضمن دور أي لجنة هو عضو/رئيس فيها فعليًا (بغض النظر
   * عن permissions أعلاه، المشتقة من System Role فقط ولا تعكس عضوية
   * اللجنة). استخدميه لإظهار قسم "اللجان" بالقائمة الجانبية والسماح
   * بالوصول لمساره — وليس permissions.includes('committees.view') وحدها.
   */
  has_committee_membership_access: boolean
  /**
   * قرار توحيد سلوك القائمة الجانبية بين "اللجان" و"الاجتماعات"
   * (2026-09-01): true لو المستخدم عضو أو رئيس بأي لجنة معتمدة إطلاقًا —
   * بدون فحص أي كود صلاحية داخل دور عضويته (أبسط من الحقل أعلاه عمدًا).
   * استخدميه فقط لإظهار رابط/مسار "الاجتماعات" — القائمة الفعلية قد ترجع
   * فارغة رغم true هنا، إن لم تُمنح meetings.view بعد لدور اللجنة.
   */
  has_any_committee_membership: boolean
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

/** دور اللجنة (رئيس/عضو) — نسخة مختصرة تُستخدم داخل CommitteeMemberRole فقط. */
export interface CommitteeRoleSummary {
  role_id: string
  name: string
  committee_role_slug: CommitteeRoleSlug
}

/** عضو اللجنة مع دوره داخلها تحديدًا — مراجعة لاما 2026-08-31 ("أدوار اللجان"). */
export interface CommitteeMemberRole {
  user: CommitteeMemberUser
  committee_role: CommitteeRoleSummary
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
  /** نفس الأعضاء أعلاه، لكن مع دور كل واحد منهم داخل هذه اللجنة تحديدًا. */
  member_roles: CommitteeMemberRole[]
  chair_user_id: string | null
  chair: CommitteeMemberUser | null
  created_at: string
}

/**
 * أنواع وحدة "إدارة الوثائق" — مطابقة تمامًا لـ
 * backend/app/schemas/document.py وbackend/app/models/document.py.
 * الرفع نفسه (POST /documents) لا يمر بـ JSON بل multipart/form-data —
 * لهذا لا يوجد DocumentCreatePayload هنا (يُبنى FormData مباشرة في
 * DocumentFormModal)، بعكس DocumentUpdatePayload (تعديل Metadata فقط،
 * JSON عادي — لا يوجد استبدال للملف نفسه في هذه المرحلة).
 */
export type DocumentCategoryScope = 'global' | 'department'

export type DocumentStatus = 'active' | 'archived'

/**
 * "قسم" الوثيقة لعنصر التحكم المُقسَّم بأعلى صفحة "الوثائق" (الكل/عامة/
 * إدارتي/لجاني/شورك معي) — مطابق تمامًا لـDocumentScopeFilter بالباك-إند
 * (backend/app/services/document_service.py) — راجعي GET /documents?scope=.
 */
export type DocumentScopeFilter = 'public' | 'department' | 'committee' | 'shared'

export interface DocumentCategory {
  category_id: string
  name: string
  scope: DocumentCategoryScope
  department_id: string | null
  created_at: string
  updated_at: string
}

export interface DocumentCategoryCreatePayload {
  name: string
  scope: DocumentCategoryScope
  department_id: string | null
}

export interface DocumentCategoryUpdatePayload {
  name: string
}

export interface DocumentUploaderSummary {
  user_id: string
  first_name: string
  middle_name: string
  last_name: string
}

export interface DocumentVisibleDepartment {
  dep_id: string
  name: string
}

export interface DocumentVisibleCommittee {
  committee_id: string
  name: string
}

export interface DocumentVisibleUser {
  user_id: string
  first_name: string
  middle_name: string
  last_name: string
}

export interface Document {
  document_id: string
  title: string
  description: string | null
  file_name: string
  mime_type: string
  file_size_bytes: number
  category: DocumentCategory | null
  status: DocumentStatus
  is_public: boolean
  uploader: DocumentUploaderSummary
  visible_departments: DocumentVisibleDepartment[]
  visible_committees: DocumentVisibleCommittee[]
  visible_users: DocumentVisibleUser[]
  created_at: string
  updated_at: string
}

/**
 * الإدارات واللجان اللي يحق للمستخدم الحالي إتاحة وثيقة لها عند الرفع
 * (مبدأ أقل صلاحية ممكنة) — راجعي GET /documents/publish-targets
 * وbackend/app/services/document_service.py::get_publish_targets.
 */
export interface DocumentPublishTargets {
  departments: DocumentVisibleDepartment[]
  committees: DocumentVisibleCommittee[]
}

/** كل الحقول اختيارية: الحقل المتروك undefined لا يُرسَل ولا يُعدَّل. */
export interface DocumentUpdatePayload {
  title?: string
  description?: string | null
  category_id?: string | null
  is_public?: boolean
  department_ids?: string[]
  committee_ids?: string[]
  user_ids?: string[]
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

/**
 * أنواع وحدة "إدارة الاجتماعات" — مطابقة تمامًا لـ
 * backend/app/schemas/meeting.py وbackend/app/models/meeting.py.
 * بدون تكامل Teams فعلي بعد — mode='remote' يمهّد لتلك المرحلة فقط.
 *
 * تحديث 2026-09-01 (قرارات صاحبة المشروع):
 * - meeting_type (نص حر) → mode (عن بعد/حضوري) + location.
 * - لا يوجد حقل مشاركين بالإنشاء/التعديل — يُشتقّون تلقائيًا من عضوية
 *   اللجنة بالكامل بطبقة الخدمة (Meeting.participants أدناه حقل قراءة
 *   فقط بالنتيجة، وليس بالـPayload).
 * - مرفقات الاجتماع (عرض تقديمي + مرفقات عامة) عبر document_links —
 *   أنواعها بأسفل هذا القسم.
 */
export type MeetingStatus = 'upcoming' | 'ongoing' | 'finished' | 'recorded'
export type MeetingMode = 'remote' | 'in_person'

export interface MeetingAgendaItem {
  agenda_item_id: string
  meeting_id: string
  title: string
  description: string | null
  sort_order: number
  created_at: string
  updated_at: string
}

export interface MeetingAgendaItemCreatePayload {
  title: string
  description?: string | null
  sort_order?: number
}

export interface MeetingAgendaItemUpdatePayload {
  title?: string
  description?: string | null
  sort_order?: number
}

export interface Meeting {
  meeting_id: string
  committee_id: string
  title: string
  description: string | null
  mode: MeetingMode
  location: string | null
  scheduled_at: string
  status: MeetingStatus
  creator: CommitteeMemberUser
  participants: CommitteeMemberUser[]
  agenda_items: MeetingAgendaItem[]
  created_at: string
  updated_at: string
}

export interface MeetingCreatePayload {
  committee_id: string
  title: string
  description?: string | null
  mode: MeetingMode
  location?: string | null
  scheduled_at: string
  agenda_items?: MeetingAgendaItemCreatePayload[]
}

export interface MeetingUpdatePayload {
  title?: string
  description?: string | null
  mode?: MeetingMode
  location?: string | null
  scheduled_at?: string
}

/** قسما مرفقات الاجتماع — يقابلان linked_entity_type بجدول document_links بالباك-إند. */
export type MeetingAttachmentKind = 'presentation' | 'attachment'

export interface MeetingAttachment {
  document_id: string
  kind: MeetingAttachmentKind
  title: string
  file_name: string
  mime_type: string
  file_size_bytes: number
  uploaded_by: CommitteeMemberUser
  linked_at: string
}

/**
 * أنواع وحدة "إدارة القرارات" — القرارات المستقلة فقط (بدون قرارات
 * مستخرجة من اجتماع بالذكاء الاصطناعي — تُبنى لاحقًا). مطابقة تمامًا
 * لـbackend/app/schemas/decision.py وapp/models/decision.py. راجعي رأس
 * db/migrations/0021_decisions_schema.sql لكل الاجتهادات الموثّقة.
 */
export type DecisionClassification = 'final' | 'voting'
export type DecisionStatus = 'pending' | 'voting' | 'approved' | 'rejected'
export type DecisionVoteChoice = 'approve' | 'reject'

export interface DecisionVote {
  voter: CommitteeMemberUser
  choice: DecisionVoteChoice
  voted_at: string
}

export interface Decision {
  decision_id: string
  committee_id: string
  title: string
  classification: DecisionClassification
  status: DecisionStatus
  start_date: string
  end_date: string
  voting_opened_at: string | null
  voting_deadline: string | null
  voting_closed_at: string | null
  rejection_reason: string | null
  creator: CommitteeMemberUser
  assignees: CommitteeMemberUser[]
  votes: DecisionVote[]
  created_at: string
  updated_at: string
}

export interface DecisionCreatePayload {
  committee_id: string
  title: string
  classification: DecisionClassification
  start_date: string
  end_date: string
  assignee_ids: string[]
}

export interface DecisionUpdatePayload {
  title?: string
  classification?: DecisionClassification
  start_date?: string
  end_date?: string
  assignee_ids?: string[]
}
