import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowRight,
  Building2,
  Download,
  Globe2,
  Pencil,
  Trash2,
  Users2,
  UserRound,
} from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import {
  useDeleteDocument,
  useDocumentDetail,
  useDocumentPublishTargets,
  useDownloadDocument,
  useUpdateDocument,
} from '@/hooks/useDocuments'
import { useDocumentCategories } from '@/hooks/useDocumentCategories'
import { useUsers } from '@/hooks/useUsers'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/ui/ErrorState'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/components/ui/Toast'
import { DocumentFormModal, type DocumentFormSubmitValues } from './DocumentFormModal'
import { extractErrorMessage, formatDateTime, formatFileSize } from '@/lib/utils'

/**
 * صفحة تفاصيل وثيقة واحدة — كل الحقول (الوصف الكامل، التصنيف، نطاق
 * الرؤية المفصَّل: إدارات/لجان/مستخدمون محددون، الرافع، التواريخ)، بالإضافة
 * لأزرار تنزيل/تعديل/حذف — كل واحد يظهر فقط حسب صلاحية المستخدم الفعلية
 * (بلا تجاوز تلقائي لـsuper_admin، مطابقةً للباك-إند)، نفس فكرة
 * DepartmentDetailPage (حالة تعديل/حذف محلية بالصفحة نفسها بدل حالة عامة
 * مشتركة).
 */
export function DocumentDetailPage() {
  const { documentId } = useParams<{ documentId: string }>()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { showToast } = useToast()

  const { data: doc, isLoading, isError, refetch } = useDocumentDetail(documentId)
  const { data: categories } = useDocumentCategories()
  // إدارات ولجان الرفع مُصفَّاة مسبقًا حسب مبدأ أقل صلاحية ممكنة — راجعي
  // نفس التعليق في DocumentsPage.tsx.
  const { data: publishTargets } = useDocumentPublishTargets()
  const { data: users } = useUsers()

  const updateMutation = useUpdateDocument()
  const deleteMutation = useDeleteDocument()
  const downloadMutation = useDownloadDocument()

  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const permissions = user?.permissions ?? []
  const canUpdate = permissions.includes('documents.update')
  const canDelete = permissions.includes('documents.delete')
  const canDownload = permissions.includes('documents.download')

  function handleEdit(values: DocumentFormSubmitValues) {
    if (!doc) return
    setFormError(null)
    updateMutation.mutate(
      { documentId: doc.document_id, payload: values },
      {
        onSuccess: () => {
          setFormOpen(false)
          showToast('تم تحديث بيانات الوثيقة بنجاح', 'success')
        },
        onError: (err) => setFormError(extractErrorMessage(err)),
      },
    )
  }

  function handleDelete() {
    if (!doc) return
    setDeleteError(null)
    deleteMutation.mutate(doc.document_id, {
      onSuccess: () => {
        showToast('تم حذف الوثيقة بنجاح', 'success')
        navigate('/documents')
      },
      onError: (err) => setDeleteError(extractErrorMessage(err)),
    })
  }

  function handleDownload() {
    if (!doc) return
    downloadMutation.mutate(
      { documentId: doc.document_id, fileName: doc.file_name },
      { onError: (err) => showToast(extractErrorMessage(err), 'error') },
    )
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40" />
      </div>
    )
  }

  if (isError || !doc) {
    return <ErrorState onRetry={() => refetch()} />
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-start gap-3">
          <button
            onClick={() => navigate('/documents')}
            className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="العودة إلى الوثائق"
          >
            <ArrowRight size={18} />
          </button>
          <div>
            <h1 className="text-xl font-bold text-text-primary">{doc.title}</h1>
            <p className="mt-1 text-sm text-text-muted">{doc.file_name}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {canDownload && (
            <Button variant="secondary" icon={<Download size={16} />} onClick={handleDownload} loading={downloadMutation.isPending}>
              تنزيل
            </Button>
          )}
          {canUpdate && (
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
          {canDelete && (
            <Button variant="danger" icon={<Trash2 size={16} />} onClick={() => setDeleteOpen(true)}>
              حذف
            </Button>
          )}
        </div>
      </div>

      <Card className="flex flex-col gap-4">
        <div>
          <p className="text-xs font-bold text-text-secondary">الوصف</p>
          <p className="mt-1 text-sm text-text-primary">{doc.description || 'لا يوجد وصف'}</p>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <p className="text-xs font-bold text-text-secondary">التصنيف</p>
            <p className="mt-1 text-sm text-text-primary">{doc.category?.name ?? 'بدون تصنيف'}</p>
          </div>
          <div>
            <p className="text-xs font-bold text-text-secondary">حجم الملف</p>
            <p className="mt-1 text-sm text-text-primary">{formatFileSize(doc.file_size_bytes)}</p>
          </div>
          <div>
            <p className="text-xs font-bold text-text-secondary">الرافع</p>
            <p className="mt-1 flex items-center gap-1.5 text-sm text-text-primary">
              <UserRound size={13} />
              {doc.uploader.first_name} {doc.uploader.last_name}
            </p>
          </div>
          <div>
            <p className="text-xs font-bold text-text-secondary">تاريخ الرفع</p>
            <p className="mt-1 text-sm text-text-primary">{formatDateTime(doc.created_at)}</p>
          </div>
          <div>
            <p className="text-xs font-bold text-text-secondary">آخر تعديل</p>
            <p className="mt-1 text-sm text-text-primary">{formatDateTime(doc.updated_at)}</p>
          </div>
        </div>

        <div className="border-t border-border-default pt-4">
          <p className="text-xs font-bold text-text-secondary">نطاق الرؤية</p>
          {doc.is_public ? (
            <p className="mt-2 flex items-center gap-1.5 text-sm font-medium text-success">
              <Globe2 size={15} />
              وثيقة عامة — يراها جميع المستخدمين
            </p>
          ) : (
            <div className="mt-2 flex flex-col gap-3">
              {doc.visible_departments.length === 0 &&
                doc.visible_committees.length === 0 &&
                doc.visible_users.length === 0 && (
                  <p className="text-sm text-text-muted">لا يوجد نطاق رؤية محدَّد بعد لهذه الوثيقة</p>
                )}
              {doc.visible_departments.length > 0 && (
                <div>
                  <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-text-secondary">
                    <Building2 size={13} />
                    إدارات
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {doc.visible_departments.map((d) => (
                      <span key={d.dep_id} className="rounded-xs bg-bg-elevated px-2 py-0.5 text-xs text-text-primary">
                        {d.name}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {doc.visible_committees.length > 0 && (
                <div>
                  <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-text-secondary">
                    <Users2 size={13} />
                    لجان
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {doc.visible_committees.map((c) => (
                      <span key={c.committee_id} className="rounded-xs bg-bg-elevated px-2 py-0.5 text-xs text-text-primary">
                        {c.name}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {doc.visible_users.length > 0 && (
                <div>
                  <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-text-secondary">
                    <UserRound size={13} />
                    مستخدمون
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {doc.visible_users.map((u) => (
                      <span key={u.user_id} className="rounded-xs bg-bg-elevated px-2 py-0.5 text-xs text-text-primary">
                        {u.first_name} {u.last_name}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </Card>

      <DocumentFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        document={doc}
        categories={categories ?? []}
        departments={publishTargets?.departments ?? []}
        committees={publishTargets?.committees ?? []}
        users={users ?? []}
        onSubmitCreate={() => {}}
        onSubmitEdit={handleEdit}
        loading={updateMutation.isPending}
        serverError={formError}
      />

      <ConfirmDialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onConfirm={handleDelete}
        title="حذف الوثيقة"
        description={`هل أنت متأكد من حذف "${doc.title}"؟ لا يمكن التراجع عن هذا الإجراء.`}
        confirmLabel="حذف الوثيقة"
        loading={deleteMutation.isPending}
        errorMessage={deleteError}
      />
    </div>
  )
}
