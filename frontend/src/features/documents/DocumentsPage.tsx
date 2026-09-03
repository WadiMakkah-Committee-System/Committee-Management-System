import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Building2,
  Download,
  FileText,
  Globe2,
  LayoutGrid,
  Layers,
  Pencil,
  Plus,
  Trash2,
  UserRound,
  Users2,
} from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import {
  useDeleteDocument,
  useDocumentPublishTargets,
  useDocuments,
  useDownloadDocument,
  useUpdateDocument,
  useUploadDocument,
} from '@/hooks/useDocuments'
import { useDocumentCategories } from '@/hooks/useDocumentCategories'
import { useUsers } from '@/hooks/useUsers'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { SearchInput } from '@/components/ui/SearchInput'
import { Select } from '@/components/ui/Select'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { CardSkeleton } from '@/components/ui/Skeleton'
import { ActionMenu } from '@/components/ui/ActionMenu'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { StatCard } from '@/components/ui/StatCard'
import { useToast } from '@/components/ui/Toast'
import { DocumentFormModal, type DocumentFormSubmitValues } from './DocumentFormModal'
import { DocumentCategoriesModal } from './DocumentCategoriesModal'
import { cardToneClass, cn, extractErrorMessage, formatDate, formatFileSize } from '@/lib/utils'
import type { Document, DocumentScopeFilter } from '@/types'

/**
 * عنصر التحكم المُقسَّم (segmented filter) بأعلى صفحة "الوثائق" —
 * فلترة بـ"قسم" الوثيقة (الكل/عامة/إدارتي/لجاني/شورك معي)، بنفس الصفحة
 * وبدون تبويب/مسار جديد (طلب صريح من المستخدمة)، مدفوعة بمعامل رابط
 * (?scope=) بدل State محلي فقط — يحفظ اختيار المستخدمة عند تحديث الصفحة
 * أو مشاركة الرابط، ويطابق GET /documents?scope= بالباك-إند تمامًا
 * (راجعي DocumentScopeFilter بـtypes/index.ts وdocument_service.py).
 */
const SCOPE_FILTER_OPTIONS: { value: DocumentScopeFilter | 'all'; label: string; icon: typeof Globe2 }[] = [
  { value: 'all', label: 'الكل', icon: LayoutGrid },
  { value: 'public', label: 'عامة', icon: Globe2 },
  { value: 'department', label: 'إدارتي', icon: Building2 },
  { value: 'committee', label: 'لجاني', icon: Users2 },
  { value: 'shared', label: 'شورك معي', icon: UserRound },
]

/** أيقونة "قسم" الوثيقة لشارة كل بطاقة — نفس مجموعة أيقونات DocumentScope بـDocumentFormModal. */
function documentScopeBadge(doc: Document): { label: string; icon: typeof Globe2 } | null {
  if (doc.is_public) return { label: 'عامة', icon: Globe2 }
  if (doc.visible_departments.length > 0) return { label: 'إدارة', icon: Building2 }
  if (doc.visible_committees.length > 0) return { label: 'لجنة', icon: Users2 }
  if (doc.visible_users.length > 0) return { label: 'مستخدمون محددون', icon: UserRound }
  return null
}

/**
 * الهدف:
 * قائمة الوثائق (Phase 6 — إدارة الوثائق) — بحث وفلترة بالتصنيف (كلاهما
 * يُنفَّذ فعليًا في الباك-إند وليس تصفية محلية، لأن البحث قد يشمل محتوى
 * الوثيقة النصي content_text حسب صلاحية documents.search_content لدى
 * المستخدم؛ الفلترة المحلية كانت ستُخفي هذا الفرق). القائمة المُعادة من
 * الـAPI مُصفّاة أصلًا حسب can_view_document في الباك-إند، فلا حاجة لأي
 * فحص رؤية إضافي هنا على مستوى العميل.
 *
 * كل زر إجراء (رفع/تعديل/حذف/تنزيل) يظهر فقط إن ملك المستخدم صلاحيته
 * الفعلية (documents.upload/update/delete/download) — بلا أي تجاوز تلقائي
 * لـsuper_admin، مطابقةً تمامًا لسلوك require_permission في الباك-إند
 * (لا تجاوز تلقائي موثّق في core/dependencies.py). إخفاء الزر مجرد تجربة
 * استخدام أفضل، وليس وسيلة الأمان — الأمان الفعلي مطبَّق في الباك-إند.
 */
export function DocumentsPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { showToast } = useToast()
  const [searchParams, setSearchParams] = useSearchParams()

  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')

  const scopeFilterParam = searchParams.get('scope')
  const scopeFilter: DocumentScopeFilter | 'all' =
    scopeFilterParam === 'public' ||
    scopeFilterParam === 'department' ||
    scopeFilterParam === 'committee' ||
    scopeFilterParam === 'shared'
      ? scopeFilterParam
      : 'all'

  function setScopeFilter(value: DocumentScopeFilter | 'all') {
    const next = new URLSearchParams(searchParams)
    if (value === 'all') next.delete('scope')
    else next.set('scope', value)
    setSearchParams(next, { replace: true })
  }

  useEffect(() => {
    const timeout = setTimeout(() => setDebouncedSearch(search.trim()), 350)
    return () => clearTimeout(timeout)
  }, [search])

  const { data: documents, isLoading, isError, refetch } = useDocuments({
    q: debouncedSearch || undefined,
    category_id: categoryFilter || undefined,
    scope: scopeFilter === 'all' ? undefined : scopeFilter,
  })
  const { data: categories } = useDocumentCategories()
  // إدارات ولجان الرفع مُصفَّاة مسبقًا حسب مبدأ أقل صلاحية ممكنة (راجعي
  // DocumentFormModal وdocument_service.get_publish_targets) — وليست
  // القوائم الكاملة لكل إدارات/لجان الشركة كما كانت سابقًا.
  const { data: publishTargets } = useDocumentPublishTargets()
  const { data: users } = useUsers()

  const uploadMutation = useUploadDocument()
  const updateMutation = useUpdateDocument()
  const deleteMutation = useDeleteDocument()
  const downloadMutation = useDownloadDocument()

  const [formOpen, setFormOpen] = useState(false)
  const [editingDoc, setEditingDoc] = useState<Document | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Document | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [categoriesModalOpen, setCategoriesModalOpen] = useState(false)

  const permissions = user?.permissions ?? []
  const canUpload = permissions.includes('documents.upload')
  const canUpdate = permissions.includes('documents.update')
  const canDelete = permissions.includes('documents.delete')
  const canDownload = permissions.includes('documents.download')
  const canManageCategories =
    !!user?.role.is_super_admin ||
    ['create_global', 'create_department', 'update_global', 'update_department', 'delete_global', 'delete_department'].some(
      (suffix) => permissions.includes(`document_categories.${suffix}`),
    )

  const categoryOptions = useMemo(
    () => (categories ?? []).map((c) => ({ value: c.category_id, label: c.name })),
    [categories],
  )

  function openCreateForm() {
    setEditingDoc(null)
    setFormError(null)
    setFormOpen(true)
  }

  function openEditForm(doc: Document) {
    setEditingDoc(doc)
    setFormError(null)
    setFormOpen(true)
  }

  function handleSubmit(values: DocumentFormSubmitValues & { file?: File }) {
    setFormError(null)
    if (editingDoc) {
      updateMutation.mutate(
        { documentId: editingDoc.document_id, payload: values },
        {
          onSuccess: () => {
            setFormOpen(false)
            showToast('تم تحديث بيانات الوثيقة بنجاح', 'success')
          },
          onError: (err) => setFormError(extractErrorMessage(err)),
        },
      )
    } else if (values.file) {
      uploadMutation.mutate(
        { ...values, file: values.file },
        {
          onSuccess: () => {
            setFormOpen(false)
            showToast('تم رفع الوثيقة بنجاح', 'success')
          },
          onError: (err) => setFormError(extractErrorMessage(err)),
        },
      )
    }
  }

  function handleDelete() {
    if (!deleteTarget) return
    setDeleteError(null)
    deleteMutation.mutate(deleteTarget.document_id, {
      onSuccess: () => {
        setDeleteTarget(null)
        showToast('تم حذف الوثيقة بنجاح', 'success')
      },
      onError: (err) => setDeleteError(extractErrorMessage(err)),
    })
  }

  function handleDownload(doc: Document) {
    downloadMutation.mutate(
      { documentId: doc.document_id, fileName: doc.file_name },
      { onError: (err) => showToast(extractErrorMessage(err), 'error') },
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-xl font-bold text-text-primary">الوثائق</h1>
          <p className="mt-1 text-sm text-text-muted">رفع وإدارة وثائق ومستندات الشركة</p>
        </div>
        <div className="flex items-center gap-2">
          {canManageCategories && (
            <Button variant="secondary" icon={<Layers size={16} />} onClick={() => setCategoriesModalOpen(true)}>
              تصنيفات الوثائق
            </Button>
          )}
          {canUpload && (
            <Button icon={<Plus size={16} />} onClick={openCreateForm}>
              رفع وثيقة
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <StatCard label="عدد الوثائق" value={documents?.length ?? 0} icon={<FileText size={20} />} tone="brand" />
        <StatCard
          label="وثائق عامة"
          value={documents?.filter((d) => d.is_public).length ?? 0}
          icon={<Globe2 size={20} />}
          tone="teal"
        />
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput value={search} onChange={setSearch} placeholder="ابحث بعنوان الوثيقة أو وصفها..." />
        <div className="sm:w-64">
          <Select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            placeholder="كل التصنيفات"
            options={categoryOptions}
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5 rounded-sm border border-border-default bg-bg-surface p-1.5">
        {SCOPE_FILTER_OPTIONS.map(({ value, label, icon: Icon }) => {
          const active = scopeFilter === value
          return (
            <button
              key={value}
              type="button"
              onClick={() => setScopeFilter(value)}
              className={cn(
                'flex items-center gap-1.5 rounded-xs px-2.5 py-1.5 text-xs font-semibold transition-colors',
                active
                  ? 'bg-brand-primary text-white'
                  : 'text-text-secondary hover:bg-bg-elevated',
              )}
            >
              <Icon size={13} />
              {label}
            </button>
          )
        })}
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : !documents || documents.length === 0 ? (
        <EmptyState
          icon={<FileText size={26} />}
          title={search || categoryFilter || scopeFilter !== 'all' ? 'لا توجد نتائج مطابقة' : 'لا توجد وثائق بعد'}
          description={
            search || categoryFilter || scopeFilter !== 'all'
              ? 'جرّب كلمات بحث أو تصنيفًا أو قسمًا مختلفًا'
              : 'ابدأ برفع أول وثيقة في النظام'
          }
          action={
            canUpload &&
            !search &&
            !categoryFilter &&
            scopeFilter === 'all' && (
              <Button size="sm" icon={<Plus size={14} />} onClick={openCreateForm}>
                رفع وثيقة
              </Button>
            )
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {documents.map((doc, i) => {
            const menuItems = [
              ...(canDownload
                ? [{ label: 'تنزيل', icon: <Download size={14} />, onClick: () => handleDownload(doc) }]
                : []),
              ...(canUpdate
                ? [{ label: 'تعديل', icon: <Pencil size={14} />, onClick: () => openEditForm(doc) }]
                : []),
              ...(canDelete
                ? [
                    {
                      label: 'حذف',
                      icon: <Trash2 size={14} />,
                      tone: 'danger' as const,
                      onClick: () => {
                        setDeleteError(null)
                        setDeleteTarget(doc)
                      },
                    },
                  ]
                : []),
            ]
            const scopeBadge = documentScopeBadge(doc)
            return (
              <motion.div
                key={doc.document_id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2, delay: Math.min(i * 0.03, 0.3) }}
              >
                <Card
                  interactive
                  onClick={() => navigate(`/documents/${doc.document_id}`)}
                  className={cn('flex h-full flex-col gap-3', cardToneClass(i))}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-sm bg-brand-primary/10 text-brand-primary">
                      <FileText size={18} />
                    </div>
                    {menuItems.length > 0 && (
                      <div onClick={(e) => e.stopPropagation()}>
                        <ActionMenu items={menuItems} />
                      </div>
                    )}
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-text-primary">{doc.title}</h3>
                    <p className="mt-1 line-clamp-2 text-sm text-text-muted">
                      {doc.description || 'لا يوجد وصف'}
                    </p>
                  </div>
                  <div className="mt-auto flex flex-wrap items-center gap-2 text-xs text-text-secondary">
                    {doc.category && (
                      <span className="rounded-xs bg-bg-elevated px-1.5 py-0.5 font-semibold text-text-muted">
                        {doc.category.name}
                      </span>
                    )}
                    {scopeBadge && (
                      <span
                        className={cn(
                          'flex items-center gap-1 rounded-xs px-1.5 py-0.5 font-semibold',
                          doc.is_public ? 'bg-success-bg text-success' : 'bg-brand-primary/10 text-brand-primary',
                        )}
                      >
                        <scopeBadge.icon size={11} />
                        {scopeBadge.label}
                      </span>
                    )}
                    <span>{formatFileSize(doc.file_size_bytes)}</span>
                  </div>
                  <p className="text-xs text-text-muted">
                    {doc.uploader.first_name} {doc.uploader.last_name} · {formatDate(doc.created_at)}
                  </p>
                </Card>
              </motion.div>
            )
          })}
        </div>
      )}

      <DocumentFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        document={editingDoc}
        categories={categories ?? []}
        departments={publishTargets?.departments ?? []}
        committees={publishTargets?.committees ?? []}
        users={users ?? []}
        onSubmitCreate={handleSubmit}
        onSubmitEdit={handleSubmit}
        loading={uploadMutation.isPending || updateMutation.isPending}
        serverError={formError}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title="حذف الوثيقة"
        description={`هل أنت متأكد من حذف "${deleteTarget?.title}"؟ لا يمكن التراجع عن هذا الإجراء.`}
        confirmLabel="حذف الوثيقة"
        loading={deleteMutation.isPending}
        errorMessage={deleteError}
      />

      <DocumentCategoriesModal open={categoriesModalOpen} onClose={() => setCategoriesModalOpen(false)} />
    </div>
  )
}
