import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import SignatureCanvas from 'react-signature-canvas'
import {
  CalendarDays,
  CheckCircle2,
  Check,
  Clock,
  Eye,
  FileText,
  ListChecks,
  PenLine,
  Plus,
  Printer,
  RotateCcw,
  Send,
  Sparkles,
  Stamp,
  Trash2,
  Users as UsersIcon,
  type LucideIcon,
} from 'lucide-react'

import { useMeetingDetailForMinutes, useMeetingExtractedItems } from '@/hooks/useMeetings'
import { useCommitteeDetail } from '@/hooks/useCommittees'
import {
  useApproveMinutes,
  useApproveMinutesReview,
  useMeetingMinutes,
  useMinutesTemplates,
  useReturnMinutesForEdit,
  useReturnMinutesReview,
  useSelectMinutesTemplate,
  useSendMinutesForSignature,
  useSignMinutes,
  useUpdateMinutesSections,
} from '@/hooks/useMeetingMinutes'
import { useMinutesRealtime } from '@/hooks/useMinutesRealtime'
import { useAuthStore } from '@/store/authStore'
import { scopeFor, cn, cardToneClass, iconToneClass, extractErrorMessage, formatDate, formatDateTime, formatRelativeTime } from '@/lib/utils'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Textarea } from '@/components/ui/Textarea'
import { Avatar } from '@/components/ui/Avatar'
import { Tabs, type TabItem } from '@/components/ui/Tabs'
import { Modal } from '@/components/ui/Modal'
import { useToast } from '@/components/ui/Toast'
import { ErrorState } from '@/components/ui/ErrorState'
import { Skeleton } from '@/components/ui/Skeleton'
import type { MinutesSection, MinutesTemplateId } from '@/types'
import { errorStatusOf, MinutesStageBadge, StageTimeline } from './minutesShared'

/**
 * الهدف:
 * "محضر الاجتماع" (SRS §7) — منفذ من تصميم Lovable المرفق من لمى
 * (minutes.id.tsx/status.tsx/store.tsx) بنفس تجربة المستخدم (6 تبويبات:
 * القوالب/المحرر/العرض/المراجعة/الاعتماد/التوقيع)، مُعاد بناؤه بمكوّنات
 * ورموز Design System الحالية (Card/Button/Tabs/Textarea/...) بدل مكوّنات
 * shadcn الأصلية. المسار /minutes/:meetingId (مستقل كليًا عن قسم
 * الاجتماعات — راجعي رأس App.tsx) نفس مسار Lovable الأصلي /minutes/$id
 * تمامًا (كان مؤقتًا /meetings/:meetingId/minutes حتى 2026-09-09، عُدّل
 * لأن البادئة المشتركة كانت تجعل السايد بار يُفعّل "الاجتماعات" بدل
 * "المحاضر" أثناء عرض هذه الصفحة تحديدًا) — راجعي رأس
 * app/services/meeting_minutes_service.py للتصميم الكامل بالباك-إند.
 *
 * الصلاحيات هنا تقريب بصري فقط (إظهار/إخفاء الأزرار) — التحقق الفعلي دائمًا
 * بالباك-إند (minutes.* عبر _has_access)، تمامًا كنمط canManage بصفحة
 * تفاصيل الاجتماع.
 */

const TEMPLATE_ICONS: Record<string, LucideIcon> = {
  executive: Sparkles,
  formal: FileText,
  detailed: ListChecks,
}

const TAB_ITEMS: TabItem[] = [
  { key: 'templates', label: 'القوالب', icon: <FileText size={15} /> },
  { key: 'editor', label: 'محرر المحضر', icon: <PenLine size={15} /> },
  { key: 'view', label: 'عرض المحضر', icon: <Eye size={15} /> },
  { key: 'review', label: 'المراجعة', icon: <Check size={15} /> },
  { key: 'approval', label: 'الاعتماد', icon: <Stamp size={15} /> },
  { key: 'signature', label: 'التوقيع الإلكتروني', icon: <PenLine size={15} /> },
]

export function MeetingMinutesPage() {
  const { meetingId } = useParams<{ meetingId: string }>()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)

  const meetingQuery = useMeetingDetailForMinutes(meetingId)
  const meeting = meetingQuery.data
  const committeeQuery = useCommitteeDetail(meeting?.committee_id)
  const committee = committeeQuery.data

  const minutesQuery = useMeetingMinutes(meetingId)
  const minutes = minutesQuery.data
  const templatesQuery = useMinutesTemplates(meetingId)
  const templates = templatesQuery.data ?? []

  const extractedItemsQuery = useMeetingExtractedItems(meetingId)
  const linkedItems = (extractedItemsQuery.data ?? []).filter((i) => i.status !== 'pending')

  const { collaborators, remoteSections, announceEditing, broadcastUpdate } = useMinutesRealtime(meetingId)
  const { showToast } = useToast()

  const [tab, setTab] = useState('editor')
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null)
  const [sections, setSections] = useState<MinutesSection[]>([])
  const [dirty, setDirty] = useState(false)
  const [reviewComment, setReviewComment] = useState('')
  const [returnComment, setReturnComment] = useState('')
  const [returnDialogOpen, setReturnDialogOpen] = useState<'review' | 'approval' | null>(null)
  const [signatureOpen, setSignatureOpen] = useState(false)
  const [mutationError, setMutationError] = useState<string | null>(null)

  const sigPadRef = useRef<SignatureCanvas>(null)
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!minutes) return
    if (!dirty) setSections(minutes.sections)
  }, [minutes, dirty])

  useEffect(() => {
    if (!remoteSections) return
    setSections(remoteSections.sections)
  }, [remoteSections])

  useEffect(() => {
    if (sections.length > 0 && !activeSectionId) setActiveSectionId(sections[0].id)
  }, [sections, activeSectionId])

  useEffect(() => {
    return () => {
      if (autosaveTimer.current) clearTimeout(autosaveTimer.current)
    }
  }, [])

  const updateSectionsMutation = useUpdateMinutesSections()
  const selectTemplateMutation = useSelectMinutesTemplate()
  const approveReviewMutation = useApproveMinutesReview()
  const returnReviewMutation = useReturnMinutesReview()
  const approveMutation = useApproveMinutes()
  const returnForEditMutation = useReturnMinutesForEdit()
  const sendForSignatureMutation = useSendMinutesForSignature()
  const signMutation = useSignMinutes()

  const meetingEnded = !!meeting && (meeting.status === 'finished' || meeting.status === 'recorded')

  const canManage =
    scopeFor(user, 'minutes.update', 'minutes.templates.select') === 'all' ||
    (!!committee && committee.chair_user_id === user?.user_id)

  const canApprove =
    scopeFor(user, 'minutes.approve') === 'all' || (!!committee && committee.chair_user_id === user?.user_id)

  const myReviewer = minutes?.reviewers.find((r) => r.user.user_id === user?.user_id) ?? null
  // تحديث 2026-09-10: محاضر قديمة تكوّنت قبل هذا التحديث ممكن تكون
  // متوقفة فعليًا بمرحلة 'review' أو 'approval' (القيم القديمة قبل حذف
  // خطوة "إرسال للمراجعة") — لازم نتعامل معهم هنا كـ"قابل للاعتماد/تعديل"
  // بالضبط متل approve_minutes بالباك-إند، وإلا تظهر أزرار الاعتماد مقفلة
  // لأي محضر قديم عالق بإحدى هالمرحلتين.
  const approvableStage =
    minutes?.stage === 'preparing' || minutes?.stage === 'review' || minutes?.stage === 'approval'
  const editable = canManage && approvableStage

  const sortedAgendaItems = useMemo(
    () => (meeting ? [...meeting.agenda_items].sort((a, b) => a.sort_order - b.sort_order) : []),
    [meeting],
  )

  function persistSections(next: MinutesSection[]) {
    if (!meetingId) return
    updateSectionsMutation.mutate(
      { meetingId, sections: next },
      {
        onSuccess: () => {
          setDirty(false)
          broadcastUpdate(next)
        },
        onError: (err) => setMutationError(extractErrorMessage(err)),
      },
    )
  }

  function scheduleAutosave(next: MinutesSection[]) {
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current)
    autosaveTimer.current = setTimeout(() => persistSections(next), 1200)
  }

  function updateSectionBody(sectionId: string, body: string) {
    setDirty(true)
    const next = sections.map((s) => (s.id === sectionId ? { ...s, body } : s))
    setSections(next)
    announceEditing(sectionId)
    scheduleAutosave(next)
  }

  function updateSectionTitle(sectionId: string, title: string) {
    setDirty(true)
    const next = sections.map((s) => (s.id === sectionId ? { ...s, title } : s))
    setSections(next)
    scheduleAutosave(next)
  }

  function addSection() {
    setDirty(true)
    const id = `s-${Date.now().toString(36)}`
    const next = [...sections, { id, title: 'قسم جديد', body: '', order: sections.length }]
    setSections(next)
    setActiveSectionId(id)
    scheduleAutosave(next)
  }

  function removeSection(sectionId: string) {
    if (sections.length <= 1) return
    setDirty(true)
    const next = sections.filter((s) => s.id !== sectionId).map((s, i) => ({ ...s, order: i }))
    setSections(next)
    if (activeSectionId === sectionId) setActiveSectionId(next[0]?.id ?? null)
    scheduleAutosave(next)
  }

  function saveNow() {
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current)
    persistSections(sections)
  }

  function handleSelectTemplate(templateId: MinutesTemplateId) {
    if (!meetingId) return
    setMutationError(null)
    selectTemplateMutation.mutate(
      { meetingId, templateId },
      { onSuccess: () => setTab('editor'), onError: (err) => setMutationError(extractErrorMessage(err)) },
    )
  }

  function handleApproveReview() {
    if (!meetingId) return
    setMutationError(null)
    approveReviewMutation.mutate(
      { meetingId, comment: reviewComment || undefined },
      { onSuccess: () => setReviewComment(''), onError: (err) => setMutationError(extractErrorMessage(err)) },
    )
  }

  function handleReturnReview() {
    if (!meetingId || !returnComment.trim()) return
    setMutationError(null)
    returnReviewMutation.mutate(
      { meetingId, comment: returnComment },
      {
        onSuccess: () => {
          setReturnDialogOpen(null)
          setReturnComment('')
          setTab('editor')
        },
        // تحديث 2026-09-10: هذا الزر داخل Modal (z-50 يغطي كامل الشاشة) —
        // شريط mutationError يترسم بجسم الصفحة الأساسي (خلف الـModal
        // تمامًا)، فأي فشل هنا كان يمر بصمت من غير ما تشوفه المستخدمة.
        // الـToast (z-100) يترسم فوق كل شي فيبقى ظاهر حتى والـModal مفتوح.
        onError: (err) => {
          const msg = extractErrorMessage(err)
          setMutationError(msg)
          showToast(msg, 'error')
        },
      },
    )
  }

  function handleApprove() {
    if (!meetingId) return
    setMutationError(null)
    approveMutation.mutate(
      { meetingId },
      { onSuccess: () => setTab('signature'), onError: (err) => setMutationError(extractErrorMessage(err)) },
    )
  }

  function handleReturnForApprovalEdit() {
    if (!meetingId || !returnComment.trim()) return
    setMutationError(null)
    returnForEditMutation.mutate(
      { meetingId, comment: returnComment },
      {
        onSuccess: () => {
          setReturnDialogOpen(null)
          setReturnComment('')
          setTab('editor')
        },
        onError: (err) => {
          const msg = extractErrorMessage(err)
          setMutationError(msg)
          showToast(msg, 'error')
        },
      },
    )
  }

  function handleSendForSignature() {
    if (!meetingId) return
    setMutationError(null)
    sendForSignatureMutation.mutate({ meetingId }, { onError: (err) => setMutationError(extractErrorMessage(err)) })
  }

  function handleSaveSignature() {
    if (!meetingId || !sigPadRef.current || sigPadRef.current.isEmpty()) return
    // تحديث 2026-09-10 (بلاغ لاما — "زر الحفظ ما يشتغل"): السبب الفعلي
    // (تأكّدنا منه من Console المتصفح): getTrimmedCanvas() بمكتبة
    // react-signature-canvas@1.1.0-alpha.2 يستخدم داخليًا حزمة trim-canvas
    // (تصدير CommonJS)، وVite يفشل بتحويلها الصحيح ضمن dependency
    // pre-bundling فيرمي فورًا "TypeError: (0 , import_build.default) is
    // not a function" — قبل حتى ما نوصل لـsignMutation.mutate. يعني ما
    // فيه طلب شبكة أصلًا ولا خطأ يبان — الزر "يتجمد" فعليًا. الحل: نتجاوز
    // getTrimmedCanvas() كليًا ونستخدم toDataURL() مباشرة (تفويض مباشر
    // لمكتبة signature_pad الأساسية، بدون المرور بـtrim-canvas المعطوبة) —
    // الفرق الوحيد إن الصورة ما تُقصّ تلقائيًا للهامش الشفاف حول التوقيع،
    // وهذا شكلي بحت ومالوش أي أثر على صحة التوقيع نفسه.
    const dataUrl = sigPadRef.current.toDataURL('image/png')
    setMutationError(null)
    signMutation.mutate(
      { meetingId, signatureImage: dataUrl },
      {
        onSuccess: () => setSignatureOpen(false),
        // إبقاء الـToast (بالإضافة لـmutationError) — الـModal (z-50) يغطي
        // شريط mutationError اللي يترسم بجسم الصفحة الأساسي، فأي فشل فعلي
        // لاحق (401/403/422 من الباك-إند) يبقى خفي بدون هذا التنبيه.
        onError: (err) => {
          const msg = extractErrorMessage(err)
          setMutationError(msg)
          showToast(msg, 'error')
        },
      },
    )
  }

  if (!meetingId) return null

  if (meetingQuery.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (meetingQuery.isError || !meeting) {
    return <ErrorState title="تعذّر تحميل الاجتماع" onRetry={() => meetingQuery.refetch()} />
  }

  if (!meetingEnded) {
    return (
      <Card className="flex flex-col items-center gap-3 px-6 py-16 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-info-bg text-info">
          <Clock size={24} />
        </div>
        <p className="text-sm font-semibold text-text-primary">محضر الاجتماع غير متاح بعد</p>
        <p className="max-w-sm text-sm text-text-secondary">
          يُتاح إعداد محضر الاجتماع بعد انتهائه (FR-MIN-001). عودي إلى هذه الصفحة بعد اكتمال الاجتماع.
        </p>
        <Button variant="secondary" onClick={() => navigate(`/meetings/${meetingId}`)}>
          العودة إلى الاجتماع
        </Button>
      </Card>
    )
  }

  const headerAction = (() => {
    if (!minutes) return null
    // تحديث 2026-09-10 (قرار لاما): ما فيه خطوة "إرسال للمراجعة" — المراجعة
    // مفتوحة تلقائيًا لكل أعضاء اللجنة بمجرد اختيار القالب. رئيس اللجنة
    // يقدر يعتمد من مرحلة "التحضير" مباشرة في أي وقت (بدون انتظار
    // المراجعين)، وإلا فالمراجع العادي يشوف زر اعتماد مراجعته الخاصة.
    if (approvableStage && canApprove)
      return (
        <Button
          icon={<Stamp size={16} />}
          disabled={sections.length === 0}
          loading={approveMutation.isPending}
          onClick={handleApprove}
        >
          اعتماد المحضر
        </Button>
      )
    if (approvableStage && myReviewer && myReviewer.status === 'pending')
      return (
        <Button icon={<Check size={16} />} loading={approveReviewMutation.isPending} onClick={handleApproveReview}>
          اعتماد المراجعة
        </Button>
      )
    if (minutes.stage === 'signature' && canManage && minutes.signatures.length === 0)
      return (
        <Button
          icon={<Send size={16} />}
          loading={sendForSignatureMutation.isPending}
          onClick={handleSendForSignature}
        >
          إرسال للتوقيع
        </Button>
      )
    return null
  })()

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-xl font-bold text-text-primary">محضر الاجتماع</h1>
          <p className="mt-1 text-sm text-text-muted">
            {meeting.title} · {committee?.name ?? '—'} · {formatDate(meeting.scheduled_at)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => navigate(`/meetings/${meetingId}`)}>
            الاجتماع
          </Button>
          {headerAction}
        </div>
      </div>

      {mutationError && (
        <div className="rounded-sm border border-danger-border/30 bg-danger-bg px-4 py-3 text-sm font-medium text-danger">
          {mutationError}
        </div>
      )}

      {minutesQuery.isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : minutesQuery.isError ? (
        (() => {
          const status = errorStatusOf(minutesQuery.error)
          if (status === 409) {
            return (
              <ErrorState
                title="الاجتماع لم ينتهِ بعد"
                description="إعداد المحضر يبدأ تلقائيًا بعد انتهاء وقت الاجتماع فعليًا — حاولي مرة أخرى بعد انتهائه"
                onRetry={() => minutesQuery.refetch()}
              />
            )
          }
          if (status === 403) {
            return (
              <ErrorState
                title="لا تملكين صلاحية عرض هذا المحضر"
                description="تحتاجين صلاحية minutes.view أو عضوية فعلية بلجنة هذا الاجتماع"
              />
            )
          }
          return <ErrorState title="تعذّر تحميل المحضر" onRetry={() => minutesQuery.refetch()} />
        })()
      ) : !minutes ? (
        <ErrorState title="تعذّر تحميل المحضر" onRetry={() => minutesQuery.refetch()} />
      ) : (
        <>
          <Card>
            <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-primary/15 text-brand-primary">
                  <Stamp size={18} />
                </span>
                <div>
                  <MinutesStageBadge stage={minutes.stage} />
                  <span className="mt-1 block text-xs text-text-muted">
                    القالب: {templates.find((t) => t.id === minutes.template_id)?.name ?? 'لم يُختر بعد'} · آخر
                    تحديث: {formatRelativeTime(minutes.updated_at)}
                  </span>
                </div>
              </div>
              {minutes.owner && (
                <div className="flex items-center gap-2 rounded-full bg-brand-teal/10 px-3 py-1.5 text-xs font-medium text-brand-teal">
                  <UsersIcon size={14} /> المسؤول عن الإعداد: {minutes.owner.first_name} {minutes.owner.last_name}
                </div>
              )}
            </div>
            <StageTimeline stage={minutes.stage} />
          </Card>

          <Tabs items={TAB_ITEMS} value={tab} onChange={setTab} />

          {tab === 'templates' && (
            <div className="grid gap-4 lg:grid-cols-3">
              {templatesQuery.isLoading ? (
                <>
                  <Skeleton className="h-64 w-full" />
                  <Skeleton className="h-64 w-full" />
                  <Skeleton className="h-64 w-full" />
                </>
              ) : (
                templates.map((t, i) => {
                  const isCurrent = minutes.template_id === t.id
                  const canPick = canManage && (minutes.stage === 'none' || minutes.stage === 'preparing')
                  const TemplateIcon = TEMPLATE_ICONS[t.id] ?? FileText
                  return (
                    <Card
                      key={t.id}
                      className={cn('flex flex-col', cardToneClass(i), isCurrent && 'ring-2 ring-brand-accent')}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-2.5">
                          <span
                            className={cn(
                              'flex h-9 w-9 shrink-0 items-center justify-center rounded-full',
                              iconToneClass(i),
                            )}
                          >
                            <TemplateIcon size={17} />
                          </span>
                          <h3 className="text-sm font-semibold text-text-primary">{t.name}</h3>
                        </div>
                        {isCurrent && (
                          <span className="shrink-0 rounded-xs bg-success-bg px-2 py-0.5 text-[11px] font-semibold text-success">
                            مختار
                          </span>
                        )}
                      </div>
                      <p className="mt-2.5 text-xs leading-6 text-text-muted">{t.description}</p>
                      <div className="my-4 flex-1 space-y-1.5 rounded-md border border-border-default bg-bg-surface p-3">
                        <p className="mb-2 text-[11px] font-medium text-text-muted">معاينة الأقسام</p>
                        {t.sections.length > 0 ? (
                          t.sections.map((s, si) => (
                            <div key={s} className="flex items-center gap-2 text-xs">
                              <span
                                className={cn(
                                  'flex h-4 w-4 items-center justify-center rounded text-[9px] font-bold',
                                  iconToneClass(i),
                                )}
                              >
                                {si + 1}
                              </span>
                              <span className="text-text-secondary">{s}</span>
                            </div>
                          ))
                        ) : (
                          <p className="text-xs text-text-muted">
                            تُبنى الأقسام تلقائيًا من بنود جدول أعمال الاجتماع، بند لكل قسم.
                          </p>
                        )}
                      </div>
                      <Button
                        className="mt-auto"
                        variant={isCurrent ? 'secondary' : 'primary'}
                        disabled={!canPick}
                        loading={selectTemplateMutation.isPending}
                        onClick={() => handleSelectTemplate(t.id)}
                      >
                        {isCurrent ? 'القالب الحالي' : 'اختيار القالب'}
                      </Button>
                    </Card>
                  )
                })
              )}
            </div>
          )}

          {tab === 'editor' && (
            <>
              {minutes.stage === 'none' || !minutes.template_id ? (
                <Card className="flex flex-col items-center gap-3 px-6 py-14 text-center">
                  <div className="flex h-12 w-12 items-center justify-center rounded-full bg-neutral-bg text-neutral">
                    <FileText size={22} />
                  </div>
                  <p className="text-sm font-semibold text-text-primary">لم يتم اختيار قالب بعد</p>
                  <p className="max-w-sm text-sm text-text-secondary">
                    اختاري أحد قوالب المحاضر المعتمدة لبدء إعداد المحضر.
                  </p>
                  {canManage && <Button onClick={() => setTab('templates')}>عرض القوالب</Button>}
                </Card>
              ) : (
                <div className="grid gap-4 xl:grid-cols-[220px_1fr_300px]">
                  <Card className="h-fit p-3">
                    <p className="px-2 pb-2 text-xs font-medium text-text-muted">محتويات المحضر</p>
                    {sections.map((s, i) => (
                      <button
                        key={s.id}
                        onClick={() => setActiveSectionId(s.id)}
                        className={cn(
                          'flex w-full items-center gap-2 rounded-sm px-3 py-2 text-right text-xs transition-colors',
                          activeSectionId === s.id
                            ? 'bg-brand-primary/10 font-semibold text-text-primary'
                            : 'text-text-muted hover:bg-bg-elevated',
                        )}
                      >
                        <span
                          className={cn(
                            'flex h-4 w-4 shrink-0 items-center justify-center rounded text-[9px] font-bold',
                            iconToneClass(i),
                          )}
                        >
                          {i + 1}
                        </span>
                        <span className="line-clamp-1">{s.title || 'بلا عنوان'}</span>
                      </button>
                    ))}
                    {editable && (
                      <button
                        onClick={addSection}
                        className="mt-1 flex w-full items-center gap-2 rounded-sm px-3 py-2 text-right text-xs font-medium text-brand-primary hover:bg-brand-primary/5"
                      >
                        <Plus size={13} /> إضافة قسم
                      </button>
                    )}
                  </Card>

                  <Card className="p-0">
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-default px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-text-muted">
                          {templates.find((t) => t.id === minutes.template_id)?.name ?? minutes.template_id}
                        </span>
                        {editable && (
                          <Button size="sm" variant="ghost" onClick={() => setTab('templates')}>
                            تغيير القالب
                          </Button>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="flex -space-x-2 space-x-reverse">
                          {collaborators.map((c) => (
                            <Avatar
                              key={c.userId}
                              firstName={c.fullName.split(' ')[0] ?? ''}
                              lastName={c.fullName.split(' ')[1] ?? ''}
                              size={26}
                              className="border-2 border-bg-surface"
                            />
                          ))}
                        </div>
                        {editable && (
                          <Button size="sm" icon={<Check size={14} />} loading={updateSectionsMutation.isPending} onClick={saveNow}>
                            حفظ
                          </Button>
                        )}
                      </div>
                    </div>
                    <div className="m-4 rounded-md border border-border-default bg-bg-app p-6 md:p-10">
                      <div className="mb-6 border-b border-border-default pb-4 text-center">
                        <p className="text-xs text-text-muted">{committee?.name}</p>
                        <h2 className="mt-1 text-lg font-bold text-text-primary">محضر {meeting.title}</h2>
                        <p className="mt-1 text-xs text-text-muted">
                          {formatDateTime(meeting.scheduled_at)}
                          {meeting.location ? ` · ${meeting.location}` : ''}
                        </p>
                      </div>
                      {sections.map((s) => {
                        const editorHere = collaborators.find((c) => c.sectionId === s.id)
                        return (
                          <div
                            key={s.id}
                            className={cn(
                              'mb-6 rounded-md p-3 transition-colors',
                              activeSectionId === s.id && 'bg-brand-primary/5 ring-1 ring-brand-accent/30',
                            )}
                          >
                            <div className="mb-2 flex items-center justify-between gap-2">
                              {editable ? (
                                <input
                                  value={s.title}
                                  onChange={(e) => updateSectionTitle(s.id, e.target.value)}
                                  onFocus={() => setActiveSectionId(s.id)}
                                  className="w-full rounded-sm border-0 bg-transparent text-sm font-bold text-text-primary focus:outline-none focus:ring-1 focus:ring-brand-accent/40"
                                />
                              ) : (
                                <h3 className="text-sm font-bold text-text-primary">{s.title}</h3>
                              )}
                              {editable && sections.length > 1 && (
                                <button
                                  onClick={() => removeSection(s.id)}
                                  className="shrink-0 rounded-sm p-1 text-text-muted transition-colors hover:bg-danger-bg hover:text-danger"
                                  aria-label="حذف القسم"
                                >
                                  <Trash2 size={14} />
                                </button>
                              )}
                            </div>
                            <Textarea
                              value={s.body}
                              onFocus={() => setActiveSectionId(s.id)}
                              onChange={(e) => updateSectionBody(s.id, e.target.value)}
                              readOnly={!editable}
                              rows={Math.max(3, Math.ceil(s.body.length / 90))}
                              className="resize-none border-0 bg-transparent p-0 text-sm leading-8 shadow-none focus:ring-0"
                            />
                            {editorHere && (
                              <div className="mt-2 rounded-sm border border-info-border/30 bg-info-bg px-3 py-2 text-[11px] text-info">
                                <span className="font-semibold">{editorHere.fullName}</span> تُحرّر هذا القسم الآن…
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </Card>

                  <div className="flex flex-col gap-4">
                    <Card className={cardToneClass(3)}>
                      <p className="mb-3 flex items-center gap-2 text-sm font-semibold text-text-primary">
                        <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-full', iconToneClass(3))}>
                          <UsersIcon size={14} />
                        </span>
                        التحرير التعاوني
                      </p>
                      {collaborators.length === 0 ? (
                        <p className="text-xs text-text-muted">لا يوجد أحد آخر يحرر المحضر الآن.</p>
                      ) : (
                        collaborators.map((c) => (
                          <div
                            key={c.userId}
                            className="mb-2 flex items-center gap-2 rounded-sm border border-border-default bg-bg-surface p-2 text-xs"
                          >
                            <span className="h-2 w-2 rounded-full bg-info" />
                            <div className="min-w-0">
                              <p className="font-medium text-text-primary">{c.fullName}</p>
                              <p className="truncate text-[11px] text-text-muted">يحرر الآن</p>
                            </div>
                          </div>
                        ))
                      )}
                      <p className="mt-3 flex items-center gap-1.5 text-[11px] text-text-muted">
                        <Clock size={12} /> آخر تحديث: {formatRelativeTime(minutes.updated_at)}
                      </p>
                    </Card>

                    <Card className={cardToneClass(0)}>
                      <p className="mb-3 flex items-center gap-2 text-sm font-semibold text-text-primary">
                        <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-full', iconToneClass(0))}>
                          <Sparkles size={14} />
                        </span>
                        أدوات مساعدة
                      </p>
                      <div className="flex flex-col gap-2">
                        <Button
                          variant="secondary"
                          size="sm"
                          className="justify-start"
                          onClick={() => navigate(`/meetings/${meetingId}`)}
                        >
                          عرض ملخص الاجتماع (AI)
                        </Button>
                        <Button variant="secondary" size="sm" className="justify-start" onClick={() => setTab('view')}>
                          معاينة المحضر النهائي
                        </Button>
                      </div>
                    </Card>

                    <Card className={cn(cardToneClass(4), 'text-xs')}>
                      <p className="mb-2 flex items-center gap-2 text-sm font-semibold text-text-primary">
                        <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-full', iconToneClass(4))}>
                          <CalendarDays size={14} />
                        </span>
                        بيانات الاجتماع
                      </p>
                      <p className="text-text-muted">اللجنة: {committee?.name ?? '—'}</p>
                      <p className="text-text-muted">الحضور: {meeting.participants.length} مشارك</p>
                      <p className="text-text-muted">بنود جدول الأعمال: {meeting.agenda_items.length}</p>
                    </Card>
                  </div>
                </div>
              )}
            </>
          )}

          {tab === 'view' && (
            <Card className="p-0">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-default px-4 py-3">
                <div className="flex items-center gap-2">
                  <MinutesStageBadge stage={minutes.stage} />
                  <span className="text-xs text-text-muted">
                    {minutes.signatures.filter((s) => s.signed).length}/{minutes.signatures.length} توقيع
                  </span>
                </div>
                <Button size="sm" variant="secondary" icon={<Printer size={14} />} onClick={() => window.print()}>
                  طباعة
                </Button>
              </div>
              <div className="bg-bg-elevated p-4 md:p-8">
                <article className="mx-auto max-w-3xl rounded-md border border-border-default bg-bg-surface p-8 md:p-12">
                  <div className="mb-6 border-b-2 border-brand-primary pb-4 text-center">
                    <p className="text-xs tracking-wide text-text-muted">{committee?.name}</p>
                    <h2 className="mt-2 text-xl font-bold text-text-primary">محضر {meeting.title}</h2>
                    <p className="mt-2 text-xs text-text-muted">
                      {formatDateTime(meeting.scheduled_at)}
                      {meeting.location ? ` · ${meeting.location}` : ''}
                    </p>
                  </div>

                  <section className="mb-6">
                    <h3 className="mb-2 text-sm font-bold text-text-primary">الحضور</h3>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {meeting.participants.map((p) => (
                        <div
                          key={p.user_id}
                          className="flex items-center justify-between rounded-sm bg-bg-elevated px-3 py-1.5 text-xs"
                        >
                          <span>
                            {p.first_name} {p.last_name}
                          </span>
                        </div>
                      ))}
                    </div>
                  </section>

                  <section className="mb-6">
                    <h3 className="mb-2 text-sm font-bold text-text-primary">جدول الأعمال</h3>
                    <ol className="space-y-1.5 text-sm leading-7">
                      {sortedAgendaItems.map((a, i) => (
                        <li key={a.agenda_item_id} className="flex gap-2">
                          <span className="font-semibold text-brand-primary">{String(i + 1).padStart(2, '0')}</span>{' '}
                          {a.title}
                        </li>
                      ))}
                    </ol>
                  </section>

                  {minutes.sections.map((s) => (
                    <section key={s.id} className="mb-6">
                      <h3 className="mb-2 text-sm font-bold text-text-primary">{s.title}</h3>
                      <p className="whitespace-pre-line text-sm leading-8 text-text-secondary">{s.body || '—'}</p>
                    </section>
                  ))}

                  {linkedItems.length > 0 && (
                    <section className="mb-6">
                      <h3 className="mb-2 text-sm font-bold text-text-primary">البنود المرتبطة (مهام وقرارات)</h3>
                      <ul className="space-y-1.5 text-sm leading-7 text-text-secondary">
                        {linkedItems.map((item) => (
                          <li key={item.item_id} className="flex items-center gap-2">
                            <span
                              className={cn(
                                'rounded-xs px-1.5 py-0.5 text-[10px] font-semibold',
                                item.status === 'assigned_task' ? 'bg-info-bg text-info' : 'bg-success-bg text-success',
                              )}
                            >
                              {item.status === 'assigned_task' ? 'مهمة' : 'قرار'}
                            </span>
                            {item.text}
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}

                  <section className="mt-10 border-t border-border-default pt-6">
                    <h3 className="mb-4 text-sm font-bold text-text-primary">التواقيع</h3>
                    {minutes.signatures.length === 0 ? (
                      <p className="text-xs text-text-muted">لم تُرسَل طلبات توقيع بعد.</p>
                    ) : (
                      <div className="grid gap-4 sm:grid-cols-2">
                        {minutes.signatures.map((s) => (
                          <div key={s.signature_id} className="rounded-md border border-border-default p-3 text-xs">
                            <p className="font-semibold text-text-primary">
                              {s.user.first_name} {s.user.last_name}
                            </p>
                            {s.signed ? (
                              <p className="mt-2 flex items-center gap-1.5 text-success">
                                <CheckCircle2 size={14} /> موقّع إلكترونيًا — {formatDateTime(s.signed_at)}
                              </p>
                            ) : (
                              <p className="mt-2 text-text-muted">بانتظار التوقيع</p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </section>
                </article>
              </div>
            </Card>
          )}

          {tab === 'review' && (
            <div className="grid gap-4 lg:grid-cols-3">
              <Card className="lg:col-span-2">
                <h3 className="text-sm font-semibold text-text-primary">مراجعة المحضر قبل الاعتماد</h3>
                <p className="mt-1 text-xs text-text-muted">
                  المراجعة مفتوحة تلقائيًا لكل أعضاء اللجنة بمجرد اختيار القالب — راجعي محتوى المحضر وسجّلي
                  ملاحظاتك، ورئيس اللجنة يقدر يعتمد المحضر في أي وقت دون انتظار اكتمال المراجعات.
                </p>

                {minutes.stage === 'none' || !minutes.template_id ? (
                  <p className="mt-4 text-xs text-text-muted">لم يتم اختيار قالب بعد — لا يوجد محتوى للمراجعة.</p>
                ) : (
                  <>
                    <div className="mt-4 max-h-96 space-y-4 overflow-y-auto rounded-md border border-border-default bg-bg-elevated p-4">
                      {minutes.sections.map((s) => (
                        <div key={s.id}>
                          <p className="text-sm font-semibold text-text-primary">{s.title}</p>
                          <p className="mt-1 whitespace-pre-line text-sm leading-7 text-text-secondary">
                            {s.body || '—'}
                          </p>
                        </div>
                      ))}
                    </div>
                    {myReviewer && myReviewer.status === 'pending' && approvableStage && (
                      <>
                        <Textarea
                          value={reviewComment}
                          onChange={(e) => setReviewComment(e.target.value)}
                          rows={3}
                          placeholder="اكتبي ملاحظات المراجعة (اختياري)…"
                          className="mt-4"
                        />
                        <div className="mt-3 flex flex-wrap gap-2">
                          <Button icon={<Check size={14} />} loading={approveReviewMutation.isPending} onClick={handleApproveReview}>
                            اعتماد المراجعة
                          </Button>
                          <Button
                            variant="secondary"
                            icon={<RotateCcw size={14} />}
                            onClick={() => setReturnDialogOpen('review')}
                          >
                            إعادة للتعديل
                          </Button>
                        </div>
                      </>
                    )}
                  </>
                )}
              </Card>

              <Card className="h-fit">
                <p className="mb-3 text-sm font-semibold text-text-primary">المراجعون</p>
                {minutes.reviewers.length === 0 ? (
                  <p className="text-xs text-text-muted">لم يُحدَّد مراجعون بعد.</p>
                ) : (
                  minutes.reviewers.map((r, i) => (
                    <div
                      key={r.reviewer_id}
                      className={cn('mb-2 flex gap-3 rounded-md border p-3 text-xs', cardToneClass(i))}
                    >
                      <Avatar firstName={r.user.first_name} lastName={r.user.last_name} size={32} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <p className="font-medium text-text-primary">
                            {r.user.first_name} {r.user.last_name}
                          </p>
                          <span
                            className={cn(
                              'shrink-0 rounded-xs border px-1.5 py-0.5 text-[10px] font-semibold',
                              r.status === 'approved' && 'border-success-border/30 bg-success-bg text-success',
                              r.status === 'returned' && 'border-danger-border/30 bg-danger-bg text-danger',
                              r.status === 'pending' && 'border-warning-border/30 bg-warning-bg text-warning',
                            )}
                          >
                            {r.status === 'approved' ? 'اعتمد' : r.status === 'returned' ? 'أعاد للتعديل' : 'بانتظار المراجعة'}
                          </span>
                        </div>
                        {r.comment && <p className="mt-2 rounded-sm bg-bg-surface p-2 text-[11px]">{r.comment}</p>}
                      </div>
                    </div>
                  ))
                )}
              </Card>
            </div>
          )}

          {tab === 'approval' && (
            <Card className={cardToneClass(2)}>
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <span className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-full', iconToneClass(2))}>
                    <Stamp size={18} />
                  </span>
                  <div>
                    <h3 className="text-sm font-semibold text-text-primary">اعتماد المحضر</h3>
                    <p className="mt-1 text-xs text-text-muted">
                      رئيس اللجنة يقدر يعتمد المحضر في أي وقت دون انتظار اكتمال مراجعة الأعضاء (
                      {minutes.reviewers.filter((r) => r.status === 'approved').length}/{minutes.reviewers.length}
                      موافقة مسجَّلة حتى الآن).
                    </p>
                  </div>
                </div>
                <MinutesStageBadge stage={minutes.stage} />
              </div>
              <div className="mt-5 rounded-md border border-border-default bg-bg-surface p-4 text-sm leading-7 text-text-secondary">
                بعد الاعتماد يُقفل تحرير المحضر وينتقل تلقائيًا إلى مرحلة التوقيع الإلكتروني، ويُرسل إشعار لجميع
                الموقّعين.
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  icon={<Stamp size={14} />}
                  disabled={!approvableStage || !canApprove}
                  loading={approveMutation.isPending}
                  onClick={handleApprove}
                >
                  اعتماد المحضر
                </Button>
                <Button variant="secondary" icon={<Eye size={14} />} onClick={() => setTab('view')}>
                  عرض المحضر
                </Button>
                {canApprove && minutes.stage === 'signature' && (
                  <Button
                    variant="secondary"
                    icon={<RotateCcw size={14} />}
                    onClick={() => setReturnDialogOpen('approval')}
                  >
                    إعادة للتعديل
                  </Button>
                )}
              </div>
            </Card>
          )}

          {tab === 'signature' &&
            (minutes.stage === 'completed' ? (
              <Card className="flex flex-col items-center gap-3 px-6 py-14 text-center">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-success-bg text-success">
                  <CheckCircle2 size={32} />
                </div>
                <h3 className="text-lg font-bold text-text-primary">اكتملت توقيعات المحضر</h3>
                <p className="max-w-sm text-sm text-text-secondary">
                  تم توقيع المحضر من جميع الأعضاء، وأصبح وثيقة رسمية غير قابلة للتعديل.
                </p>
                <Button icon={<Eye size={14} />} onClick={() => setTab('view')}>
                  عرض المحضر النهائي
                </Button>
              </Card>
            ) : (
              <div className="grid gap-4 lg:grid-cols-3">
                <Card className="lg:col-span-2">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-text-primary">حالة التوقيعات</h3>
                    {minutes.signatures.length > 0 && (
                      <span className="text-xs text-text-muted">
                        {minutes.signatures.filter((s) => s.signed).length} من {minutes.signatures.length}
                      </span>
                    )}
                  </div>
                  {minutes.signatures.length === 0 ? (
                    <p className="mt-4 text-xs text-text-muted">لم تُرسَل طلبات التوقيع بعد.</p>
                  ) : (
                    <div className="mt-4 flex flex-col gap-2">
                      {minutes.signatures.map((s, i) => (
                        <div
                          key={s.signature_id}
                          className={cn('flex flex-wrap items-center gap-3 rounded-md border p-3', cardToneClass(i))}
                        >
                          <Avatar firstName={s.user.first_name} lastName={s.user.last_name} size={36} />
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium text-text-primary">
                              {s.user.first_name} {s.user.last_name}
                            </p>
                          </div>
                          {s.signed ? (
                            <div className="text-left">
                              <p className="flex items-center gap-1.5 text-xs font-medium text-success">
                                <CheckCircle2 size={14} /> تم التوقيع
                              </p>
                              <p className="text-[11px] text-text-muted">{formatDateTime(s.signed_at)}</p>
                            </div>
                          ) : s.user.user_id === user?.user_id ? (
                            <Button size="sm" icon={<PenLine size={14} />} onClick={() => setSignatureOpen(true)}>
                              توقيع
                            </Button>
                          ) : (
                            <span className="rounded-xs border border-warning-border/30 bg-warning-bg px-1.5 py-0.5 text-[10px] font-semibold text-warning">
                              بانتظار التوقيع
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
                <Card className={cn('h-fit', cardToneClass(1))}>
                  <div className="flex items-center gap-3">
                    <span className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-full', iconToneClass(1))}>
                      <Send size={16} />
                    </span>
                    <p className="text-sm font-semibold text-text-primary">إرسال للتوقيع</p>
                  </div>
                  <p className="mt-2 text-xs leading-6 text-text-muted">
                    يرسل النظام إشعارًا لكل عضو مطلوب توقيعه، ويسجّل تاريخ ووقت التوقيع.
                  </p>
                  {canManage && minutes.signatures.length === 0 && (
                    <Button
                      className="mt-4 w-full"
                      icon={<Send size={14} />}
                      loading={sendForSignatureMutation.isPending}
                      onClick={handleSendForSignature}
                    >
                      إرسال طلبات التوقيع
                    </Button>
                  )}
                  <div className="mt-4 border-t border-border-default pt-4">
                    <p className="text-xs text-text-muted">سجل التدقيق</p>
                    <ul className="mt-2 space-y-2 text-[11px] text-text-muted">
                      {minutes.owner && (
                        <li>
                          أُنشئ المحضر بواسطة {minutes.owner.first_name} {minutes.owner.last_name}
                        </li>
                      )}
                      {minutes.sent_to_review_at && <li>أُرسل للمراجعة: {formatDateTime(minutes.sent_to_review_at)}</li>}
                      {minutes.approved_at && <li>اعتُمد المحضر: {formatDateTime(minutes.approved_at)}</li>}
                      {minutes.sent_for_signature_at && (
                        <li>أُرسل للتوقيع: {formatDateTime(minutes.sent_for_signature_at)}</li>
                      )}
                    </ul>
                  </div>
                </Card>
              </div>
            ))}
        </>
      )}

      <Modal
        open={signatureOpen}
        onClose={() => setSignatureOpen(false)}
        title="التوقيع الإلكتروني"
        description="ارسمي توقيعك داخل الإطار أدناه، ثم اضغطي حفظ التوقيع."
        footer={
          <>
            <Button variant="ghost" onClick={() => sigPadRef.current?.clear()}>
              مسح
            </Button>
            <Button loading={signMutation.isPending} onClick={handleSaveSignature}>
              حفظ التوقيع
            </Button>
          </>
        }
      >
        <div className="rounded-md border border-dashed border-border-default bg-bg-app">
          <SignatureCanvas
            ref={sigPadRef}
            penColor="#0f172a"
            canvasProps={{ className: 'h-48 w-full touch-none' }}
          />
        </div>
      </Modal>

      <Modal
        open={returnDialogOpen !== null}
        onClose={() => {
          setReturnDialogOpen(null)
          setReturnComment('')
        }}
        title="إعادة المحضر للتعديل"
        description={
          returnDialogOpen === 'approval'
            ? 'سيُلغى اعتماد المحضر ويعود قابلاً للتعديل من جديد، وسيُشعَر المسؤول عن الإعداد بالملاحظات المسجلة.'
            : 'سيُسجَّل رأيك كإعادة للتعديل مع ملاحظاتك، وسيُشعَر المسؤول عن الإعداد بها — المحضر يبقى مفتوحًا للتعديل دون انتظار.'
        }
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => {
                setReturnDialogOpen(null)
                setReturnComment('')
              }}
            >
              تراجع
            </Button>
            <Button
              variant="danger"
              disabled={!returnComment.trim()}
              loading={returnReviewMutation.isPending || returnForEditMutation.isPending}
              onClick={() => (returnDialogOpen === 'review' ? handleReturnReview() : handleReturnForApprovalEdit())}
            >
              إعادة للتعديل
            </Button>
          </>
        }
      >
        <Textarea
          value={returnComment}
          onChange={(e) => setReturnComment(e.target.value)}
          rows={3}
          placeholder="سبب الإعادة والملاحظات المطلوبة…"
        />
      </Modal>
    </div>
  )
}
