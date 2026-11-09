import { useEffect, useRef, useState } from 'react'
import { Check, ExternalLink, FileText, Loader2 } from 'lucide-react'
import type { Socket } from 'socket.io-client'
import * as minutesApi from '@/api/meetingMinutes'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { Spinner } from '@/components/ui/Spinner'
import { Textarea } from '@/components/ui/Textarea'
import { useMeetingMinutesDetail, useSelectMinutesTemplate, useUpdateMinutesSections } from '@/hooks/useMeetingMinutes'
import { useMinutesRealtime } from '@/hooks/useMinutesRealtime'
import { useAuthStore } from '@/store/authStore'
import { cn, extractErrorMessage, scopeFor } from '@/lib/utils'
import type { MinutesSection } from '@/types'
import { errorStatusOf, MinutesStageBadge } from '../../minutesShared'

/**
 * لوحة المحضر داخل غرفة الاجتماع (طلب لاما 2026-11-09 — "النائب يقدر يشاركني
 * المحضر وأنا بنفس الاجتماع؟"): نسخة مختصرة من تبويب "محرر المحضر" بصفحة
 * MeetingMinutesPage.tsx — نفس الـAPI ونفس منطق Autosave (1200ms) ونفس القفل
 * البصري للقسم الذي يكتب فيه عضو آخر (LOCK_TTL_MS)، فالتعديل من هنا ومن صفحة
 * المحضر يتزامن لحظيًا بالاتجاهين (FR-MIN-005).
 *
 * الفرق الوحيد بالاتصال: تستخدم اتصال Socket.IO الخاص بالغرفة (sharedSocket)
 * بدل فتح اتصال ثانٍ — راجعي تعليق sharedSocket بـuseMinutesRealtime.ts.
 *
 * باقي مراحل المحضر (المراجعة/الاعتماد/التوقيع) تبقى بصفحة المحضر الكاملة —
 * زر "فتح المحضر كاملًا" يفتحها بتبويب جديد حتى لا يغادر المستخدم الاجتماع.
 *
 * الصلاحيات هنا تقريب بصري فقط — التحقق الفعلي بالباك-إند (minutes.update).
 */

// نفس القيمة بـMeetingMinutesPage.tsx (أطول من فاصل Autosave حتى لا يرمش القفل).
const LOCK_TTL_MS = 4000
const AUTOSAVE_MS = 1200

export function MinutesPanel({ meetingId, sharedSocket }: { meetingId: string; sharedSocket: Socket | null }) {
  const user = useAuthStore((s) => s.user)
  const detailQuery = useMeetingMinutesDetail(meetingId)
  const detail = detailQuery.data
  const committee = detail?.committee
  const minutes = detail?.minutes
  const templates = detail?.templates ?? []

  const isChair = !!committee && committee.chair_user_id === user?.user_id
  // اختيار القالب: يكفي أن يُرجع الباك-إند قائمة القوالب (فارغة لمن لا يملك
  // minutes.templates.view). الكتابة: can_edit المحسوبة بالباك-إند (نفس فحص PUT
  // /minutes/sections) — لا scopeFor محليًا حتى لا تُفتح الكتابة لمن لا يملك
  // minutes.update فيفشل الحفظ بصمت. رئاسة اللجنة شبكة أمان فقط.
  const canPickTemplate =
    isChair || scopeFor(user, 'minutes.templates.select') === 'all'
  const approvableStage =
    minutes?.stage === 'preparing' || minutes?.stage === 'review' || minutes?.stage === 'approval'
  const editable = (isChair || !!detail?.can_edit) && approvableStage

  const { collaborators, remoteSections, announceEditing, broadcastUpdate } = useMinutesRealtime(
    meetingId,
    sharedSocket,
  )
  const updateSectionsMutation = useUpdateMinutesSections()
  const selectTemplateMutation = useSelectMinutesTemplate()

  const [sections, setSections] = useState<MinutesSection[]>([])
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // آخر نسخة لم تُحفظ بعد — تُحفظ فورًا لو أُغلقت الغرفة قبل انتهاء مهلة Autosave.
  const pendingRef = useRef<MinutesSection[] | null>(null)

  const [, tick] = useState(0)
  useEffect(() => {
    if (collaborators.length === 0) return
    const id = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [collaborators.length])

  useEffect(() => {
    if (!minutes) return
    if (!dirty) setSections(minutes.sections)
  }, [minutes, dirty])

  // نفس إصلاح 2026-09-15 بصفحة المحضر: لا نستبدل ما يكتبه المستخدم الآن ببث بعيد.
  useEffect(() => {
    if (!remoteSections) return
    if (dirty) return
    setSections(remoteSections.sections)
  }, [remoteSections, dirty])

  // بث وصل ونحن بلا قالب ⇒ رئيس اللجنة اختار القالب للتو: نعيد جلب المحضر
  // (stage/template_id) بدل البقاء على شاشة "لم يتم اختيار قالب".
  const noTemplateNow = !minutes || minutes.stage === 'none' || !minutes.template_id
  const { refetch: refetchDetail } = detailQuery
  useEffect(() => {
    if (remoteSections && noTemplateNow) void refetchDetail()
  }, [remoteSections, noTemplateNow, refetchDetail])

  // بعد انقطاع اتصال الغرفة ورجوعه قد تكون فاتتنا تحديثات minutes.updated —
  // نعيد جلب النسخة المحفوظة (تُطبَّق فقط إن لم يكن لدينا تعديل محلي معلّق).
  useEffect(() => {
    if (!sharedSocket) return
    const onReconnect = () => void refetchDetail()
    sharedSocket.io.on('reconnect', onReconnect)
    return () => {
      sharedSocket.io.off('reconnect', onReconnect)
    }
  }, [sharedSocket, refetchDetail])

  useEffect(() => {
    return () => {
      if (autosaveTimer.current) clearTimeout(autosaveTimer.current)
      if (pendingRef.current) {
        void minutesApi.updateMinutesSections(meetingId, pendingRef.current).catch(() => undefined)
      }
    }
  }, [meetingId])

  function lockedSectionEditor(sectionId: string) {
    const entry = collaborators.find((c) => c.sectionId === sectionId && c.userId !== user?.user_id)
    if (!entry) return null
    if (Date.now() - entry.at > LOCK_TTL_MS) return null
    return entry
  }

  function persistSections(next: MinutesSection[]) {
    updateSectionsMutation.mutate(
      { meetingId, sections: next },
      {
        onSuccess: () => {
          setError(null)
          broadcastUpdate(next)
          // لا نعتبر المسودة محفوظة إن كتب المستخدم شيئًا أحدث أثناء هذا
          // الطلب — الحفظ التالي (المجدول أصلًا) هو اللي يصفّرها.
          if (pendingRef.current === next) {
            pendingRef.current = null
            setDirty(false)
          }
        },
        onError: (err) => setError(extractErrorMessage(err)),
      },
    )
  }

  function updateSectionBody(sectionId: string, body: string) {
    setDirty(true)
    const next = sections.map((s) => (s.id === sectionId ? { ...s, body } : s))
    setSections(next)
    pendingRef.current = next
    announceEditing(sectionId)
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current)
    autosaveTimer.current = setTimeout(() => persistSections(next), AUTOSAVE_MS)
  }

  function handleSelectTemplate(templateId: (typeof templates)[number]['id']) {
    setError(null)
    selectTemplateMutation.mutate(
      { meetingId, templateId },
      {
        // إبلاغ بقية الحاضرين فاتحين اللوحة — راجعي effect noTemplateNow أعلاه.
        onSuccess: (saved) => broadcastUpdate(saved.sections),
        onError: (err) => setError(extractErrorMessage(err)),
      },
    )
  }

  function openFullMinutes() {
    window.open(`/minutes/${meetingId}`, '_blank', 'noopener')
  }

  if (detailQuery.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center py-10">
        <Spinner />
      </div>
    )
  }

  if (detailQuery.isError) {
    const status = errorStatusOf(detailQuery.error)
    return (
      <EmptyState
        icon={<FileText size={22} />}
        title={status === 403 ? 'لا تملك صلاحية عرض هذا المحضر' : 'تعذّر تحميل المحضر'}
        action={
          status === 403 ? undefined : (
            <Button size="sm" variant="secondary" onClick={() => detailQuery.refetch()}>
              إعادة المحاولة
            </Button>
          )
        }
      />
    )
  }

  if (!minutes) return null

  const noTemplate = minutes.stage === 'none' || !minutes.template_id
  const saving = updateSectionsMutation.isPending

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border-default bg-bg-surface px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <MinutesStageBadge stage={minutes.stage} />
          {!noTemplate && editable && (
            <span className="flex items-center gap-1 text-[11px] text-text-muted">
              {saving ? (
                <>
                  <Loader2 size={12} className="animate-spin" /> جاري الحفظ...
                </>
              ) : dirty ? (
                'تعديلات غير محفوظة'
              ) : (
                <>
                  <Check size={12} className="text-success" /> محفوظ
                </>
              )}
            </span>
          )}
        </div>
        <Button size="sm" variant="ghost" icon={<ExternalLink size={13} />} onClick={openFullMinutes}>
          المحضر كاملًا
        </Button>
      </div>

      {collaborators.filter((c) => c.userId !== user?.user_id).length > 0 && (
        <div className="shrink-0 border-b border-border-default bg-info-bg px-3 py-1.5 text-[11px] text-info">
          يحرر معك الآن:{' '}
          <span className="font-semibold">
            {collaborators
              .filter((c) => c.userId !== user?.user_id)
              .map((c) => c.fullName)
              .join('، ')}
          </span>
        </div>
      )}

      {error && (
        <div className="shrink-0 border-b border-danger-border/30 bg-danger-bg px-3 py-1.5 text-[11px] text-danger">
          {error}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {noTemplate ? (
          canPickTemplate && templates.length > 0 ? (
            <div className="flex flex-col gap-2">
              <p className="text-xs font-semibold text-text-primary">اختر قالب المحضر للبدء</p>
              {templates.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  disabled={selectTemplateMutation.isPending}
                  onClick={() => handleSelectTemplate(t.id)}
                  className="rounded-md border border-border-default bg-bg-surface p-3 text-right transition-colors hover:border-brand-primary hover:bg-brand-primary/[0.06] disabled:opacity-50"
                >
                  <p className="text-sm font-semibold text-text-primary">{t.name}</p>
                  <p className="mt-0.5 text-[11px] text-text-muted">{t.description}</p>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={<FileText size={22} />}
              title="لم يتم اختيار قالب بعد"
              description="يبدأ إعداد المحضر بعد أن يختار رئيس اللجنة قالب المحضر."
            />
          )
        ) : (
          <div className="flex flex-col gap-3">
            {sections.map((s) => {
              const editorHere = lockedSectionEditor(s.id)
              const lockedForMe = !!editorHere
              return (
                <div key={s.id} className="rounded-md border border-border-default bg-bg-surface p-3">
                  <h3 className="mb-1.5 text-[13px] font-bold text-text-primary">{s.title || 'بلا عنوان'}</h3>
                  {editable ? (
                    <Textarea
                      value={s.body}
                      onChange={(e) => updateSectionBody(s.id, e.target.value)}
                      readOnly={lockedForMe}
                      rows={Math.max(3, Math.ceil(s.body.length / 45))}
                      placeholder="اكتب هنا..."
                      className={cn(
                        'resize-none text-sm leading-7',
                        lockedForMe && 'cursor-not-allowed opacity-60',
                      )}
                    />
                  ) : (
                    <p className="whitespace-pre-wrap text-sm leading-7 text-text-secondary">
                      {s.body || <span className="text-text-muted">لا يوجد محتوى بعد.</span>}
                    </p>
                  )}
                  {editorHere && (
                    <p className="mt-1.5 text-[11px] text-info">
                      <span className="font-semibold">{editorHere.fullName}</span> يحرر هذا القسم الآن.
                    </p>
                  )}
                </div>
              )
            })}
            {!editable && (
              <p className="text-center text-[11px] text-text-muted">
                عرض فقط — تحتاج صلاحية تعديل المحضر للكتابة.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
