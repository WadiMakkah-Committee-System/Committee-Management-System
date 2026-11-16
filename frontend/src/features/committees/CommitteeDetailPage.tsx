import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowRight,
  CalendarDays,
  CalendarPlus,
  Crown,
  Download,
  FileText,
  Mail,
  NotebookPen,
  Pencil,
  Plus,
  UserMinus,
  UserPlus,
  Users as UsersIcon,
} from 'lucide-react'
import {
  useCommitteeCapabilities,
  useCommitteeDetail,
  useCommitteeMembershipAction,
  useUpdateCommitteeDates,
  type CommitteeMembershipAction,
} from '@/hooks/useCommittees'
import {
  useDocumentPublishTargets,
  useDocuments,
  useDownloadDocument,
  useUploadDocument,
} from '@/hooks/useDocuments'
import { useDocumentCategories } from '@/hooks/useDocumentCategories'
import { useUsers } from '@/hooks/useUsers'
import { useAuthStore } from '@/store/authStore'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { ErrorState } from '@/components/ui/ErrorState'
import { EmptyState } from '@/components/ui/EmptyState'
import { Skeleton, TableSkeleton } from '@/components/ui/Skeleton'
import { Avatar } from '@/components/ui/Avatar'
import { CommitteeLifecycleBadge, CommitteeRoleBadge } from '@/components/ui/StatusBadge'
import { useToast } from '@/components/ui/Toast'
import { CommitteeDatesEditModal } from '@/features/committees/CommitteeDatesEditModal'
import {
  AddCommitteeMemberModal,
  CommitteeHistoryCard,
  ExtendCommitteeModal,
} from '@/features/committees/CommitteeMembershipTools'
import { ActionMenu, type ActionMenuItem } from '@/components/ui/ActionMenu'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { ReasonConfirmDialog } from '@/components/ui/ReasonConfirmDialog'
import { DocumentFormModal, type DocumentFormSubmitValues } from '@/features/documents/DocumentFormModal'
import { cn, extractErrorMessage, formatDate, formatDateTime, formatFileSize } from '@/lib/utils'
import { formatCommitteePeriod } from '@/features/committees/committeePeriod'

/**
 * تفاصيل لجنة معتمدة واحدة — Phase 5. العضوية كانت للعرض فقط؛ منذ
 * migration 0050 (طلب لاما 2026-11-16) اللجان الدائمة تُعدَّل عضويتها من هنا
 * (إضافة/حذف/تغيير الرئيس أو الأمين) مع سجل تغييرات، وأي لجنة بفترة تُمدَّد.
 * المؤقتة تبقى عضويتها مقفلة بعد الاعتماد. الأزرار تتبع /capabilities، والفحص
 * الفعلي بالباك-إند (committee_membership_service).
 * قسم "وثائق اللجنة" أدناه (2026-09-02) استثناء مقصود — ميزة منفصلة
 * تمامًا عن عضوية اللجنة (رفع وثيقة مرتبطة باللجنة مباشرة، راجعي
 * defaultCommitteeId بـDocumentFormModal)، وليست جزءًا من القرار أعلاه.
 */
export function CommitteeDetailPage() {
  const { committeeId } = useParams<{ committeeId: string }>()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { showToast } = useToast()
  const { data: committee, isLoading, isError, refetch } = useCommitteeDetail(committeeId)

  const permissions = user?.permissions ?? []
  // لا يوجد تجاوز تلقائي لـsuper_admin هنا (قرار موثّق 2026-08-27) — العرض
  // محكوم فعليًا بامتلاك الصلاحية، تمامًا مثل الوصول لصفحة الطلب نفسها.
  const canViewSourceRequest = permissions.includes('committees.request.view')
  // قاعدة فترة اللجنة (طلب صاحبة المشروع 2026-09-13) — راجعي
  // backend/db/migrations/0032_committee_dates_update_grant.sql (المكتب
  // التنفيذي فقط حاليًا).
  const canEditDates = permissions.includes('committees.update')
  const [datesEditOpen, setDatesEditOpen] = useState(false)

  // تعديل العضوية + التمديد + السجل (migration 0050).
  const { data: caps } = useCommitteeCapabilities(committeeId)
  const membershipMutation = useCommitteeMembershipAction(committeeId ?? '')
  const [extendOpen, setExtendOpen] = useState(false)
  const [addMemberOpen, setAddMemberOpen] = useState(false)
  const [membershipError, setMembershipError] = useState<string | null>(null)
  const [removeTarget, setRemoveTarget] = useState<{ user_id: string; name: string } | null>(null)
  const [roleTarget, setRoleTarget] = useState<
    { kind: 'chair' | 'secretary' | 'unset_secretary'; user_id: string; name: string } | null
  >(null)

  /** تنفيذ عملية عضوية/تمديد، وإغلاق نوافذها عند النجاح. */
  function runMembership(action: CommitteeMembershipAction, successMessage: string, onDone: () => void) {
    setMembershipError(null)
    membershipMutation.mutate(action, {
      onSuccess: () => {
        onDone()
        showToast(successMessage, 'success')
      },
      onError: (err) => setMembershipError(extractErrorMessage(err)),
    })
  }
  const [datesEditError, setDatesEditError] = useState<string | null>(null)
  const updateDatesMutation = useUpdateCommitteeDates(committeeId ?? '')

  function handleUpdateDates(values: { start_date: string; end_date: string }) {
    setDatesEditError(null)
    updateDatesMutation.mutate(values, {
      onSuccess: () => {
        setDatesEditOpen(false)
        showToast('تم تحديث فترة عمل اللجنة بنجاح', 'success')
      },
      onError: (err) => setDatesEditError(extractErrorMessage(err)),
    })
  }

  // قسم "وثائق اللجنة" (طلب صريح من المستخدمة 2026-09-02): رفع وثيقة من
  // داخل صفحة اللجنة يضبط نطاقها تلقائيًا على هذه اللجنة تحديدًا
  // (defaultCommitteeId بـDocumentFormModal) بدل الذهاب لصفحة "الوثائق"
  // واختيار اللجنة يدويًا — والقائمة هنا مفلترة بـcommittee_id فقط
  // (documents.list يبقى هو الحارس الفعلي: لا تظهر وثيقة هنا إلا لمن
  // يحق له رؤيتها أصلًا، عضوية اللجنة شرط حتى لسوبر أدمن، راجعي
  // can_view_document بالباك-إند).
  const canUploadDocuments = permissions.includes('documents.upload')
  const canDownloadDocuments = permissions.includes('documents.download')
  const [documentFormOpen, setDocumentFormOpen] = useState(false)
  const [documentFormError, setDocumentFormError] = useState<string | null>(null)
  const { data: committeeDocuments, isLoading: documentsLoading } = useDocuments({
    committee_id: committeeId,
  })
  // بيانات نموذج رفع الوثيقة فقط — تُجلب عند فتحه (تحسين أداء 2026-10-24).
  const { data: documentCategories } = useDocumentCategories({ enabled: documentFormOpen })
  const { data: publishTargets } = useDocumentPublishTargets({ enabled: documentFormOpen })
  const { data: usersList } = useUsers({ enabled: documentFormOpen })
  const uploadDocumentMutation = useUploadDocument()
  const downloadDocumentMutation = useDownloadDocument()

  function handleDocumentUpload(values: DocumentFormSubmitValues & { file?: File }) {
    if (!values.file) return
    setDocumentFormError(null)
    uploadDocumentMutation.mutate(
      { ...values, file: values.file },
      {
        onSuccess: () => {
          setDocumentFormOpen(false)
          showToast('تم رفع الوثيقة بنجاح', 'success')
        },
        onError: (err) => setDocumentFormError(extractErrorMessage(err)),
      },
    )
  }

  // مراجعة لاما 2026-09-01: "لما الشخص يدخل لجنته يعرف اذا هو رئيس لجنة
  // او عضو لجنة" — member_roles يحمل دور كل عضو داخل هذه اللجنة تحديدًا
  // (راجعي schemas/committee.py::CommitteeMemberRoleOut)، نبحث فيه عن صف
  // المستخدم الحالي نفسه. تبقى undefined لمن يشاهد اللجنة عبر صلاحية
  // نظامية (committees.view بنطاق department/all) بدون أن يكون عضوًا
  // فعليًا فيها — لا شارة تظهر له حينها، وهذا صحيح.
  const myMembership = committee?.member_roles.find((m) => m.user.user_id === user?.user_id)
  const roleSlugByUserId = new Map(
    (committee?.member_roles ?? []).map((m) => [m.user.user_id, m.committee_role.committee_role_slug]),
  )

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

  if (isError || !committee) {
    return <ErrorState onRetry={() => refetch()} />
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-start gap-3">
          <button
            onClick={() => navigate('/committees/approved')}
            className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="العودة إلى اللجان المعتمدة"
          >
            <ArrowRight size={18} />
          </button>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-bold tracking-tight text-text-primary sm:text-[1.6rem] sm:leading-tight">{committee.name}</h1>
              <CommitteeLifecycleBadge state={committee.lifecycle_state} />
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <p className="text-sm text-text-muted">لجنة معتمدة رسميًا</p>
              {myMembership && (
                <>
                  <span className="text-text-muted">·</span>
                  <span className="text-sm text-text-muted">دورك في اللجنة:</span>
                  <CommitteeRoleBadge slug={myMembership.committee_role.committee_role_slug} />
                </>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {caps?.can_extend && (
            <Button
              variant="secondary"
              size="sm"
              icon={<CalendarPlus size={14} />}
              onClick={() => {
                setMembershipError(null)
                setExtendOpen(true)
              }}
            >
              تمديد مدة اللجنة
            </Button>
          )}
          {/* migration 0050: فترة الدائمة صارت قابلة للتعديل أيضًا. */}
          {canEditDates && (
            <Button variant="secondary" size="sm" icon={<Pencil size={14} />} onClick={() => setDatesEditOpen(true)}>
              تعديل فترة اللجنة
            </Button>
          )}
          {canViewSourceRequest && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate(`/committees/requests/${committee.source_request_id}`)}
            >
              عرض طلب التشكيل الأصلي
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[
          {
            icon: <CalendarDays size={20} />,
            tone: 'bg-brand-teal/10 text-brand-teal',
            value: formatCommitteePeriod(committee),
            label: 'فترة عمل اللجنة',
          },
          {
            icon: <UsersIcon size={20} />,
            tone: 'bg-brand-purple/10 text-brand-purple',
            value: String(committee.members.length),
            label: 'عدد الأعضاء',
          },
          {
            icon: <CalendarDays size={20} />,
            tone: 'bg-brand-primary/10 text-brand-primary',
            value: formatDate(committee.created_at),
            label: 'تاريخ الاعتماد',
          },
        ].map((item, i) => (
          <motion.div
            key={item.label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: i * 0.05, ease: 'easeOut' }}
          >
            <Card className="flex items-center gap-4">
              <div className={cn('flex h-12 w-12 shrink-0 items-center justify-center rounded-full', item.tone)}>
                {item.icon}
              </div>
              <div>
                <p className="text-sm font-semibold text-text-primary">{item.value}</p>
                <p className="mt-1 text-xs text-text-muted">{item.label}</p>
              </div>
            </Card>
          </motion.div>
        ))}
      </div>

      {committee.statement && (
        <Card>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <FileText size={15} />
            بيان/غرض اللجنة
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-text-secondary">{committee.statement}</p>
        </Card>
      )}

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <UsersIcon size={15} />
            أعضاء اللجنة
          </h2>
          {caps?.can_add_members && (
            <Button
              size="sm"
              icon={<UserPlus size={14} />}
              onClick={() => {
                setMembershipError(null)
                setAddMemberOpen(true)
              }}
            >
              إضافة عضو
            </Button>
          )}
        </div>
        {/* قائمة أعضاء بصف مرن بدل جدول — يتكيّف تلقائيًا على الجوال (البريد
            ينزل تحت الاسم) بدل جدول بعرض ثابت يحتاج تمريرًا أفقيًا. */}
        <ul>
          {committee.members.map((member, i) => (
            <motion.li
              key={member.user_id}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.15, delay: Math.min(i * 0.02, 0.2) }}
              className="flex flex-col gap-1.5 border-b border-border-default px-4 py-3 last:border-0 sm:flex-row sm:items-center sm:justify-between sm:gap-3"
            >
              <div className="flex items-center gap-3">
                <Avatar firstName={member.first_name} lastName={member.last_name} />
                <p className="font-medium text-text-primary">
                  {member.first_name} {member.last_name}
                  {member.user_id === user?.user_id && (
                    <span className="mr-1.5 text-xs font-normal text-text-muted">(أنت)</span>
                  )}
                </p>
                <CommitteeRoleBadge slug={roleSlugByUserId.get(member.user_id) ?? null} />
              </div>
              <div className="flex items-center gap-2">
                <span className="flex items-center gap-1.5 text-sm text-text-secondary">
                  <Mail size={13} className="shrink-0" />
                  {member.email}
                </span>
                {(() => {
                  const name = `${member.first_name} ${member.last_name}`
                  const isChair = committee.chair_user_id === member.user_id
                  const isSecretary = committee.secretary_user_id === member.user_id
                  const items: ActionMenuItem[] = []
                  if (caps?.can_change_roles && !isChair) {
                    items.push({
                      label: 'تعيين رئيسًا للجنة',
                      icon: <Crown size={14} />,
                      onClick: () => setRoleTarget({ kind: 'chair', user_id: member.user_id, name }),
                    })
                    items.push(
                      isSecretary
                        ? {
                            label: 'إلغاء تعيينه أمينًا للسر',
                            icon: <NotebookPen size={14} />,
                            onClick: () => setRoleTarget({ kind: 'unset_secretary', user_id: member.user_id, name }),
                          }
                        : {
                            label: 'تعيين أمينًا للسر',
                            icon: <NotebookPen size={14} />,
                            onClick: () => setRoleTarget({ kind: 'secretary', user_id: member.user_id, name }),
                          },
                    )
                  }
                  if (caps?.can_remove_members && !isChair) {
                    items.push({
                      label: 'حذف من اللجنة',
                      icon: <UserMinus size={14} />,
                      tone: 'danger',
                      onClick: () => {
                        setMembershipError(null)
                        setRemoveTarget({ user_id: member.user_id, name })
                      },
                    })
                  }
                  return items.length > 0 ? <ActionMenu items={items} /> : null
                })()}
              </div>
            </motion.li>
          ))}
        </ul>
      </Card>

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <FileText size={15} />
            وثائق اللجنة
          </h2>
          {canUploadDocuments && (
            <Button size="sm" icon={<Plus size={14} />} onClick={() => setDocumentFormOpen(true)}>
              رفع وثيقة
            </Button>
          )}
        </div>
        {documentsLoading ? (
          <div className="p-4">
            <TableSkeleton />
          </div>
        ) : !committeeDocuments || committeeDocuments.length === 0 ? (
          <EmptyState
            icon={<FileText size={22} />}
            title="لا توجد وثائق بعد"
            description="لا توجد وثائق خاصة بهذه اللجنة حتى الآن"
          />
        ) : (
          <ul>
            {committeeDocuments.map((doc) => (
              <li
                key={doc.document_id}
                className="flex flex-col gap-1.5 border-b border-border-default px-4 py-3 last:border-0 sm:flex-row sm:items-center sm:justify-between sm:gap-3"
              >
                <button
                  type="button"
                  onClick={() => navigate(`/documents/${doc.document_id}`)}
                  className="flex items-center gap-2 text-start font-medium text-text-primary hover:text-brand-primary"
                >
                  <FileText size={15} className="shrink-0 text-brand-primary" />
                  {doc.title}
                </button>
                <div className="flex items-center gap-3 text-xs text-text-muted">
                  <span>{formatFileSize(doc.file_size_bytes)}</span>
                  <span>{formatDate(doc.created_at)}</span>
                  {canDownloadDocuments && (
                    <button
                      type="button"
                      onClick={() =>
                        downloadDocumentMutation.mutate(
                          { documentId: doc.document_id, fileName: doc.file_name },
                          { onError: (err) => showToast(extractErrorMessage(err), 'error') },
                        )
                      }
                      className="flex items-center gap-1 rounded-xs p-1 text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
                      aria-label="تنزيل"
                    >
                      <Download size={14} />
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {caps?.can_view_history && <CommitteeHistoryCard committeeId={committee.committee_id} />}

      <p className="text-xs text-text-muted">أُنشئت اللجنة في {formatDateTime(committee.created_at)}</p>

      {canUploadDocuments && (
        <DocumentFormModal
          open={documentFormOpen}
          onClose={() => setDocumentFormOpen(false)}
          categories={documentCategories ?? []}
          departments={publishTargets?.departments ?? []}
          committees={publishTargets?.committees ?? []}
          users={usersList ?? []}
          defaultCommitteeId={committee.committee_id}
          onSubmitCreate={handleDocumentUpload}
          onSubmitEdit={handleDocumentUpload}
          loading={uploadDocumentMutation.isPending}
          serverError={documentFormError}
        />
      )}

      {caps?.can_extend && (
        <ExtendCommitteeModal
          open={extendOpen}
          onClose={() => setExtendOpen(false)}
          committee={committee}
          loading={membershipMutation.isPending}
          serverError={membershipError}
          onSubmit={({ endDate, reason }) =>
            runMembership({ kind: 'extend', endDate, reason }, 'تم تمديد مدة اللجنة', () => setExtendOpen(false))
          }
        />
      )}

      {caps?.can_add_members && (
        <AddCommitteeMemberModal
          open={addMemberOpen}
          onClose={() => setAddMemberOpen(false)}
          committeeId={committee.committee_id}
          loading={membershipMutation.isPending}
          serverError={membershipError}
          onSubmit={({ userId, reason }) =>
            runMembership({ kind: 'add', userId, reason }, 'تمت إضافة العضو للجنة', () => setAddMemberOpen(false))
          }
        />
      )}

      <ReasonConfirmDialog
        open={!!removeTarget}
        onClose={() => setRemoveTarget(null)}
        title="حذف عضو من اللجنة"
        description={`سيُحذف ${removeTarget?.name ?? ''} من اللجنة ويُسجَّل ذلك بسجل التغييرات.`}
        reasonLabel="سبب الحذف"
        confirmLabel="حذف العضو"
        variant="danger"
        loading={membershipMutation.isPending}
        errorMessage={membershipError}
        onConfirm={(reason) =>
          removeTarget &&
          runMembership({ kind: 'remove', userId: removeTarget.user_id, reason }, 'تم حذف العضو من اللجنة', () =>
            setRemoveTarget(null),
          )
        }
      />

      <ConfirmDialog
        open={!!roleTarget}
        onClose={() => setRoleTarget(null)}
        title={
          roleTarget?.kind === 'chair'
            ? 'تغيير رئيس اللجنة'
            : roleTarget?.kind === 'secretary'
              ? 'تعيين أمين السر'
              : 'إلغاء تعيين أمين السر'
        }
        description={
          roleTarget?.kind === 'chair'
            ? `سيصبح ${roleTarget.name} رئيس اللجنة، والرئيس الحالي عضوًا عاديًا.`
            : roleTarget?.kind === 'secretary'
              ? `سيصبح ${roleTarget.name} أمين سر اللجنة.`
              : `سيصبح ${roleTarget?.name ?? ''} عضوًا عاديًا.`
        }
        confirmLabel="تأكيد"
        variant="primary"
        loading={membershipMutation.isPending}
        errorMessage={membershipError}
        onConfirm={() => {
          if (!roleTarget) return
          const action: CommitteeMembershipAction =
            roleTarget.kind === 'chair'
              ? { kind: 'chair', userId: roleTarget.user_id }
              : { kind: 'secretary', userId: roleTarget.kind === 'secretary' ? roleTarget.user_id : null }
          runMembership(action, 'تم تحديث أدوار اللجنة', () => setRoleTarget(null))
        }}
      />

      {canEditDates && (
        <CommitteeDatesEditModal
          open={datesEditOpen}
          onClose={() => setDatesEditOpen(false)}
          committee={committee}
          onSubmit={handleUpdateDates}
          loading={updateDatesMutation.isPending}
          serverError={datesEditError}
        />
      )}
    </div>
  )
}
