import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowRight,
  ArrowUpCircle,
  CalendarDays,
  CheckCircle2,
  FileText,
  Mail,
  Pencil,
  Send,
  Undo2,
  UserRound,
  Users as UsersIcon,
  XCircle,
} from 'lucide-react'
import {
  useApproveCommitteeRequest,
  useCommitteeRequestDetail,
  useEscalateCommitteeRequest,
  useRejectCommitteeRequest,
  useReturnCommitteeRequestToAdmin,
  useReturnCommitteeRequestToOffice,
  useSubmitCommitteeRequest,
  useUpdateCommitteeRequest,
} from '@/hooks/useCommitteeRequests'
import { useAuthStore } from '@/store/authStore'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { ErrorState } from '@/components/ui/ErrorState'
import { Skeleton, TableSkeleton } from '@/components/ui/Skeleton'
import { Avatar } from '@/components/ui/Avatar'
import { CommitteeRequestStatusBadge } from '@/components/ui/StatusBadge'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { ReasonConfirmDialog } from '@/components/ui/ReasonConfirmDialog'
import { useToast } from '@/components/ui/Toast'
import { CommitteeRequestFormModal, type CommitteeRequestFormSubmitValues } from './CommitteeRequestFormModal'
import { RequestPipeline } from './RequestPipeline'
import { extractErrorMessage, formatDate, formatDateTime } from '@/lib/utils'

/**
 * صفحة تفاصيل طلب تشكيل لجنة واحد — عرض كامل + كل إجراءات دورة الحياة
 * حسب القواعد الموثّقة بـ committee_service.py بالضبط (راجعي
 * project_memory: phase2-committee-formation-requests.md لآلة الحالة
 * الكاملة). Phase 3 (تعديل/إرسال لصاحب الطلب) + Phase 4 (واجهات المراجعة
 * والاعتماد: إرجاع مع سبب، رفع، اعتماد/رفض مع سبب) مبنيّتان معًا هنا —
 * نفس الصفحة، لأن كل الإجراءات تتشارك نفس بيانات الطلب وتُفرَّق فقط
 * بالحالة + صلاحية الفاعل، تمامًا كما في الباك-إند.
 */
export function CommitteeRequestDetailPage() {
  const { requestId } = useParams<{ requestId: string }>()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { data: request, isLoading, isError, refetch } = useCommitteeRequestDetail(requestId)
  const updateMutation = useUpdateCommitteeRequest()
  const submitMutation = useSubmitCommitteeRequest()
  const returnToAdminMutation = useReturnCommitteeRequestToAdmin()
  const escalateMutation = useEscalateCommitteeRequest()
  const returnToOfficeMutation = useReturnCommitteeRequestToOffice()
  const approveMutation = useApproveCommitteeRequest()
  const rejectMutation = useRejectCommitteeRequest()
  const { showToast } = useToast()

  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [submitConfirmOpen, setSubmitConfirmOpen] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [returnToAdminOpen, setReturnToAdminOpen] = useState(false)
  const [returnToAdminError, setReturnToAdminError] = useState<string | null>(null)
  const [escalateConfirmOpen, setEscalateConfirmOpen] = useState(false)
  const [escalateError, setEscalateError] = useState<string | null>(null)
  const [returnToOfficeOpen, setReturnToOfficeOpen] = useState(false)
  const [returnToOfficeError, setReturnToOfficeError] = useState<string | null>(null)
  const [approveConfirmOpen, setApproveConfirmOpen] = useState(false)
  const [approveError, setApproveError] = useState<string | null>(null)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectError, setRejectError] = useState<string | null>(null)

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-8 w-56" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <div className="overflow-hidden rounded-md border border-border-default bg-bg-surface">
          <TableSkeleton />
        </div>
      </div>
    )
  }

  if (isError || !request) {
    return <ErrorState onRetry={() => refetch()} />
  }

  const isSuperAdmin = !!user?.role.is_super_admin
  const permissions = user?.permissions ?? []
  const isOwner = user?.user_id === request.requester.user_id
  const isDraftLike = request.status === 'draft' || request.status === 'returned'
  const isPendingOfficeStage = request.status === 'submitted' || request.status === 'under_review'
  const isPendingApproval = request.status === 'pending_approval'

  const canEditAsOwner =
    isDraftLike && (isOwner || isSuperAdmin) && (isSuperAdmin || permissions.includes('committees.request.create'))
  const canEditAsOffice =
    isPendingOfficeStage && (isSuperAdmin || permissions.includes('committees.request.update'))
  const canEdit = canEditAsOwner || canEditAsOffice
  const canSubmit = canEditAsOwner

  // Phase 4 — إجراءات المكتب التنفيذي (submitted/under_review فقط):
  const canReturnToAdmin = isPendingOfficeStage && (isSuperAdmin || permissions.includes('committees.request.update'))
  const canEscalate = isPendingOfficeStage && (isSuperAdmin || permissions.includes('committees.request.escalate'))

  // Phase 4 — إجراءات الرئيس التنفيذي (pending_approval فقط، القرار الثلاثي):
  const canDecide = isPendingApproval && (isSuperAdmin || permissions.includes('committees.request.approve'))

  function handleEdit(values: CommitteeRequestFormSubmitValues) {
    if (!requestId) return
    setFormError(null)
    updateMutation.mutate(
      { requestId, payload: values },
      {
        onSuccess: () => {
          setFormOpen(false)
          showToast('تم حفظ تعديلات الطلب بنجاح', 'success')
        },
        onError: (err) => setFormError(extractErrorMessage(err)),
      },
    )
  }

  function handleSubmit() {
    if (!requestId) return
    setSubmitError(null)
    submitMutation.mutate(requestId, {
      onSuccess: () => {
        setSubmitConfirmOpen(false)
        showToast('تم إرسال الطلب إلى المكتب التنفيذي بنجاح', 'success')
      },
      onError: (err) => setSubmitError(extractErrorMessage(err)),
    })
  }

  function handleReturnToAdmin(reason: string) {
    if (!requestId) return
    setReturnToAdminError(null)
    returnToAdminMutation.mutate(
      { requestId, returnReason: reason },
      {
        onSuccess: () => {
          setReturnToAdminOpen(false)
          showToast('تم إرجاع الطلب لمقدّمه للتعديل', 'success')
        },
        onError: (err) => setReturnToAdminError(extractErrorMessage(err)),
      },
    )
  }

  function handleEscalate() {
    if (!requestId) return
    setEscalateError(null)
    escalateMutation.mutate(requestId, {
      onSuccess: () => {
        setEscalateConfirmOpen(false)
        showToast('تم رفع الطلب للرئيس التنفيذي للاعتماد', 'success')
      },
      onError: (err) => setEscalateError(extractErrorMessage(err)),
    })
  }

  function handleReturnToOffice(reason: string) {
    if (!requestId) return
    setReturnToOfficeError(null)
    returnToOfficeMutation.mutate(
      { requestId, returnReason: reason },
      {
        onSuccess: () => {
          setReturnToOfficeOpen(false)
          showToast('تم إرجاع الطلب للمكتب التنفيذي للتعديل', 'success')
        },
        onError: (err) => setReturnToOfficeError(extractErrorMessage(err)),
      },
    )
  }

  function handleApprove() {
    if (!requestId) return
    setApproveError(null)
    approveMutation.mutate(requestId, {
      onSuccess: () => {
        setApproveConfirmOpen(false)
        showToast('تم اعتماد الطلب — تم تشكيل اللجنة رسميًا', 'success')
      },
      onError: (err) => setApproveError(extractErrorMessage(err)),
    })
  }

  function handleReject(reason: string) {
    if (!requestId) return
    setRejectError(null)
    rejectMutation.mutate(
      { requestId, rejectionReason: reason },
      {
        onSuccess: () => {
          setRejectOpen(false)
          showToast('تم رفض الطلب', 'success')
        },
        onError: (err) => setRejectError(extractErrorMessage(err)),
      },
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-start gap-3">
          <button
            onClick={() => navigate('/committees/requests')}
            className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="العودة إلى طلبات تشكيل اللجان"
          >
            <ArrowRight size={18} />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-text-primary">{request.committee_name}</h1>
              <CommitteeRequestStatusBadge status={request.status} />
            </div>
            <p className="mt-1 text-sm text-text-muted">
              مقدّم الطلب: {request.requester.first_name} {request.requester.last_name}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          {canEdit && (
            <Button
              variant="secondary"
              icon={<Pencil size={16} />}
              onClick={() => {
                setFormError(null)
                setFormOpen(true)
              }}
            >
              تعديل
            </Button>
          )}
          {canSubmit && (
            <Button icon={<Send size={16} />} onClick={() => setSubmitConfirmOpen(true)}>
              إرسال الطلب
            </Button>
          )}
          {canReturnToAdmin && (
            <Button
              variant="secondary"
              icon={<Undo2 size={16} />}
              onClick={() => {
                setReturnToAdminError(null)
                setReturnToAdminOpen(true)
              }}
            >
              إرجاع لمقدّم الطلب
            </Button>
          )}
          {canEscalate && (
            <Button icon={<ArrowUpCircle size={16} />} onClick={() => setEscalateConfirmOpen(true)}>
              رفع للرئيس التنفيذي
            </Button>
          )}
          {canDecide && (
            <>
              <Button
                variant="secondary"
                icon={<Undo2 size={16} />}
                onClick={() => {
                  setReturnToOfficeError(null)
                  setReturnToOfficeOpen(true)
                }}
              >
                إرجاع للمكتب التنفيذي
              </Button>
              <Button
                variant="danger"
                icon={<XCircle size={16} />}
                onClick={() => {
                  setRejectError(null)
                  setRejectOpen(true)
                }}
              >
                رفض
              </Button>
              <Button icon={<CheckCircle2 size={16} />} onClick={() => setApproveConfirmOpen(true)}>
                اعتماد
              </Button>
            </>
          )}
        </div>
      </div>

      <RequestPipeline status={request.status} returnReason={request.return_reason} />

      {request.status === 'returned' && request.return_reason && (
        <div className="rounded-md border border-warning-border/30 bg-warning-bg px-4 py-3 text-sm text-warning">
          <p className="font-semibold">أُعيد هذا الطلب للتعديل</p>
          <p className="mt-1 text-text-secondary">{request.return_reason}</p>
        </div>
      )}
      {request.status === 'under_review' && request.return_reason && (
        <div className="rounded-md border border-warning-border/30 bg-warning-bg px-4 py-3 text-sm text-warning">
          <p className="font-semibold">أرجع الرئيس التنفيذي هذا الطلب للمكتب التنفيذي</p>
          <p className="mt-1 text-text-secondary">{request.return_reason}</p>
        </div>
      )}
      {request.status === 'rejected' && request.rejection_reason && (
        <div className="rounded-md border border-danger-border/30 bg-danger-bg px-4 py-3 text-sm text-danger">
          <p className="font-semibold">تم رفض هذا الطلب</p>
          <p className="mt-1 text-text-secondary">{request.rejection_reason}</p>
        </div>
      )}
      {request.status === 'approved' && (
        <div className="rounded-md border border-success-border/30 bg-success-bg px-4 py-3 text-sm text-success">
          <p className="font-semibold">تم اعتماد هذا الطلب وتشكيل اللجنة رسميًا</p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card className="flex items-center gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-brand-primary/10 text-brand-primary">
            <UserRound size={20} />
          </div>
          <div>
            <p className="text-sm font-semibold text-text-primary">
              {request.requester.first_name} {request.requester.last_name}
            </p>
            <p className="mt-1 text-xs text-text-muted">مقدّم الطلب</p>
          </div>
        </Card>
        <Card className="flex items-center gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-brand-teal/10 text-brand-teal">
            <CalendarDays size={20} />
          </div>
          <div>
            <p className="text-sm font-semibold text-text-primary">
              {formatDate(request.start_date)} — {formatDate(request.end_date)}
            </p>
            <p className="mt-1 text-xs text-text-muted">فترة عمل اللجنة</p>
          </div>
        </Card>
        <Card className="flex items-center gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-brand-purple/10 text-brand-purple">
            <UsersIcon size={20} />
          </div>
          <div>
            <p className="text-sm font-semibold text-text-primary">{request.proposed_members.length}</p>
            <p className="mt-1 text-xs text-text-muted">الأعضاء المقترحون</p>
          </div>
        </Card>
      </div>

      {request.statement && (
        <Card>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <FileText size={15} />
            بيان/غرض اللجنة
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-text-secondary">{request.statement}</p>
        </Card>
      )}

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <UsersIcon size={15} />
            الأعضاء المقترحون
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-right text-sm">
            <thead>
              <tr className="border-b border-border-default bg-table-header">
                <th className="px-4 py-3 font-semibold text-text-secondary">العضو</th>
                <th className="px-4 py-3 font-semibold text-text-secondary">البريد الإلكتروني</th>
              </tr>
            </thead>
            <tbody>
              {request.proposed_members.map((member, i) => (
                <motion.tr
                  key={member.user_id}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.15, delay: Math.min(i * 0.02, 0.2) }}
                  className="border-b border-border-default last:border-0"
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <Avatar firstName={member.first_name} lastName={member.last_name} />
                      <p className="font-medium text-text-primary">
                        {member.first_name} {member.last_name}
                      </p>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className="flex items-center gap-1.5 text-text-secondary">
                      <Mail size={13} />
                      {member.email}
                    </span>
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <p className="text-xs text-text-muted">
        أُنشئ الطلب في {formatDateTime(request.created_at)} — آخر تحديث {formatDateTime(request.updated_at)}
      </p>

      <CommitteeRequestFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        request={request}
        onSubmit={handleEdit}
        loading={updateMutation.isPending}
        serverError={formError}
      />

      <ConfirmDialog
        open={submitConfirmOpen}
        onClose={() => setSubmitConfirmOpen(false)}
        onConfirm={handleSubmit}
        title="إرسال طلب تشكيل اللجنة"
        description="بعد الإرسال، لن تقدري تعديل الطلب مباشرة إلا إذا أعاده المكتب التنفيذي إليك مع سبب. هل تريدين المتابعة؟"
        confirmLabel="إرسال الطلب"
        variant="primary"
        loading={submitMutation.isPending}
        errorMessage={submitError}
      />

      <ReasonConfirmDialog
        open={returnToAdminOpen}
        onClose={() => setReturnToAdminOpen(false)}
        onConfirm={handleReturnToAdmin}
        title="إرجاع الطلب لمقدّمه"
        description="سيُرجَع الطلب لمقدّمه (الادمن) ليعدّله ويعيد إرساله من جديد — اذكري سبب الإرجاع."
        reasonLabel="سبب الإرجاع"
        confirmLabel="إرجاع الطلب"
        variant="danger"
        loading={returnToAdminMutation.isPending}
        errorMessage={returnToAdminError}
      />

      <ConfirmDialog
        open={escalateConfirmOpen}
        onClose={() => setEscalateConfirmOpen(false)}
        onConfirm={handleEscalate}
        title="رفع الطلب للرئيس التنفيذي"
        description="سيُرفَع الطلب للرئيس التنفيذي لاتخاذ قرار الاعتماد النهائي، ولن تقدري تعديله بعدها إلا إذا أرجعه لكم. هل تريدين المتابعة؟"
        confirmLabel="رفع الطلب"
        variant="primary"
        loading={escalateMutation.isPending}
        errorMessage={escalateError}
      />

      <ReasonConfirmDialog
        open={returnToOfficeOpen}
        onClose={() => setReturnToOfficeOpen(false)}
        onConfirm={handleReturnToOffice}
        title="إرجاع الطلب للمكتب التنفيذي"
        description="سيُرجَع الطلب للمكتب التنفيذي ليعدّله ويرفعه إليك مرة أخرى — هذا إجراء غير نهائي، بخلاف الرفض. اذكري سبب الإرجاع."
        reasonLabel="سبب الإرجاع"
        confirmLabel="إرجاع للمكتب"
        variant="danger"
        loading={returnToOfficeMutation.isPending}
        errorMessage={returnToOfficeError}
      />

      <ConfirmDialog
        open={approveConfirmOpen}
        onClose={() => setApproveConfirmOpen(false)}
        onConfirm={handleApprove}
        title="اعتماد طلب تشكيل اللجنة"
        description="سيُعتمَد الطلب نهائيًا وتُشكَّل اللجنة رسميًا بالأعضاء المقترحين — لا يمكن التراجع عن هذا القرار. هل تريدين المتابعة؟"
        confirmLabel="اعتماد الطلب"
        variant="primary"
        loading={approveMutation.isPending}
        errorMessage={approveError}
      />

      <ReasonConfirmDialog
        open={rejectOpen}
        onClose={() => setRejectOpen(false)}
        onConfirm={handleReject}
        title="رفض طلب تشكيل اللجنة"
        description="سيُرفَض الطلب نهائيًا ولا يمكن التراجع عن هذا القرار — اذكري سبب الرفض."
        reasonLabel="سبب الرفض"
        confirmLabel="رفض الطلب"
        variant="danger"
        loading={rejectMutation.isPending}
        errorMessage={rejectError}
      />
    </div>
  )
}
