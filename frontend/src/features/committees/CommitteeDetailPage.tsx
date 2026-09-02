import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight, CalendarDays, Download, FileText, Mail, Plus, Users as UsersIcon } from 'lucide-react'
import { useCommitteeDetail } from '@/hooks/useCommittees'
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
import { CommitteeRoleBadge } from '@/components/ui/StatusBadge'
import { useToast } from '@/components/ui/Toast'
import { DocumentFormModal, type DocumentFormSubmitValues } from '@/features/documents/DocumentFormModal'
import { cn, extractErrorMessage, formatDate, formatDateTime, formatFileSize } from '@/lib/utils'

/**
 * تفاصيل لجنة معتمدة واحدة — Phase 5، عرض فقط (Read-only) لبيانات
 * اللجنة والعضوية تحديدًا: لا أي إجراء تعديل/إضافة/حذف أعضاء هنا عمدًا —
 * قرار موثّق من Lama (راجعي project_memory: phase2-committee-formation-requests.md).
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
  const { data: documentCategories } = useDocumentCategories()
  const { data: publishTargets } = useDocumentPublishTargets()
  const { data: usersList } = useUsers()
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
            <h1 className="text-xl font-bold text-text-primary">{committee.name}</h1>
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

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[
          {
            icon: <CalendarDays size={20} />,
            tone: 'bg-brand-teal/10 text-brand-teal',
            value: `${formatDate(committee.start_date)} — ${formatDate(committee.end_date)}`,
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
              <span className="flex items-center gap-1.5 text-sm text-text-secondary">
                <Mail size={13} className="shrink-0" />
                {member.email}
              </span>
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
    </div>
  )
}
