import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueries } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { CheckCircle2, ClipboardList, FileSignature, ShieldAlert, SquarePen, UserRound, Users2 } from 'lucide-react'
import { useMeetings } from '@/hooks/useMeetings'
import { useCommittees } from '@/hooks/useCommittees'
import * as minutesApi from '@/api/meetingMinutes'
import { Card } from '@/components/ui/Card'
import { SearchInput } from '@/components/ui/SearchInput'
import { Select } from '@/components/ui/Select'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { CardSkeleton } from '@/components/ui/Skeleton'
import { StatCard, type StatTone } from '@/components/ui/StatCard'
import { errorStatusOf, MinutesStageBadge, STAGE_META, STAGE_ORDER, StageTimeline } from './minutesShared'
import { cardToneClass, cn, formatDate } from '@/lib/utils'
import type { MeetingMinutes, MeetingMinutesStage } from '@/types'

/**
 * قائمة "المحاضر" — إعادة تصميم كاملة 2026-09-09 (طلب لاما، بمرجع بصري
 * كامل أعطتنا إياه): النسخة الأولى كانت صفوفًا مختصرة تشبه قائمة
 * الاجتماعات حرفيًا بلا أي قيمة مضافة خاصة بالمحاضر — لا فائدة من قسم
 * مستقل يعرض نفس الشكل. الآن كل بطاقة تحمل معلومات المحضر نفسه فقط
 * (لا تكرار لبيانات الاجتماع): المسؤول عن الإعداد، تقدّم المراجعين
 * والتوقيعات فعليًا (من نفس MeetingMinutes المجلوب أصلًا عبر useQueries —
 * لا حاجة لأي طلب إضافي)، وخط زمني كامل لحالة المحضر (StageTimeline من
 * minutesShared.tsx، نفس المكوّن المستخدَم بصفحة المحضر التفصيلية).
 *
 * فصل تام عن قسم الاجتماعات (طلب لاما 2026-09-09 الصريح): الوجهة عند
 * الضغط على بطاقة صارت /minutes/:meetingId (لا /meetings/:id/minutes
 * كما كانت) — راجعي رأس App.tsx لسبب النقل الكامل (تعارض NavLink
 * بالسايد بار وصلاحية meetings.view الخاطئة). زر "محضر الاجتماع" بصفحة
 * تفاصيل الاجتماع (MeetingDetailPage.tsx) يبقى كما هو تمامًا، فقط
 * وجهته حُدّثت لنفس المسار الجديد.
 *
 * إصلاح 2026-09-09 (ملاحظة لاما: "ليش الببلاين موجود في اول اجتماع بس"):
 * السبب الفعلي لم يكن صلاحيات — الباك-إند (get_or_create_minutes بملف
 * meeting_minutes_service.py) يرفض إنشاء/جلب المحضر بخطأ 409 صراحةً ما
 * لم ينتهِ الاجتماع فعليًا (_require_meeting_finished)، وكنا نعامل أي
 * خطأ جلب كـ"لا صلاحية" بلا تمييز، فتختفي البطاقة زمنية بالكامل بدل أن
 * تُظهر حالة "لم ينتهِ بعد" الطبيعية. الآن نميّز 409 (لم ينتهِ الاجتماع
 * بعد — حالة متوقعة لا خطأ) عن 403 (لا صلاحية فعليًا) عن أي خطأ آخر،
 * ونعرض الخط الزمني على كل البطاقات دائمًا (بمرحلة none افتراضيًا) بدل
 * إخفائه عند أي خطأ.
 */

type StageFilter = 'all' | MeetingMinutesStage

const STAT_TONES: Record<MeetingMinutesStage, StatTone> = {
  none: 'brand',
  preparing: 'brand',
  review: 'orange',
  approval: 'purple',
  signature: 'teal',
  completed: 'success',
}

export function MinutesListPage() {
  const navigate = useNavigate()
  const { data: meetings, isLoading, isError, refetch } = useMeetings()
  const { data: committees } = useCommittees()

  const [search, setSearch] = useState('')
  const [stageFilter, setStageFilter] = useState<StageFilter>('all')
  const [committeeFilter, setCommitteeFilter] = useState<string>('all')

  const committeeNames = useMemo(() => {
    const map = new Map<string, string>()
    for (const c of committees ?? []) map.set(c.committee_id, c.name)
    return map
  }, [committees])

  /** الاجتماعات المؤهَّلة لعرض محضر — بدأ وقتها فعليًا بالساعة والدقيقة
   * (status الاجتماع محسوب بالباك-إند من scheduled_at/scheduled_end_at
   * الكاملين، لا من التاريخ فقط) وليست upcoming. تشمل عمدًا الاجتماعات
   * الجارية (لم تنتهِ بعد) لا المكتملة فقط — الباك-إند يرفض إنشاء
   * المحضر لها بـ409 وهذا متوقَّع ومعروض بوضوح بالبطاقة (انظر أعلاه). */
  const started = useMemo(() => (meetings ?? []).filter((m) => m.status !== 'upcoming'), [meetings])

  const minutesQueries = useQueries({
    queries: started.map((m) => ({
      queryKey: ['meetings', m.meeting_id, 'minutes'],
      queryFn: () => minutesApi.fetchMeetingMinutes(m.meeting_id),
      staleTime: 30_000,
      retry: false,
    })),
  })

  const queryFor = (meetingId: string) => {
    const idx = started.findIndex((m) => m.meeting_id === meetingId)
    return idx === -1 ? undefined : minutesQueries[idx]
  }

  /** خريطة meeting_id → المحضر كامل (لا المرحلة فقط) — نحتاج المراجعين
   * والتوقيعات والمسؤول لكل بطاقة، وكلها موجودة أصلًا بنفس الاستجابة. */
  const minutesByMeeting = useMemo(() => {
    const map = new Map<string, MeetingMinutes | null>()
    started.forEach((m, i) => {
      const q = minutesQueries[i]
      map.set(m.meeting_id, q.data ?? null)
    })
    return map
  }, [started, minutesQueries])

  const stageOf = (meetingId: string): MeetingMinutesStage | null => minutesByMeeting.get(meetingId)?.stage ?? null

  const searched = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return started
    return started.filter(
      (m) => m.title.toLowerCase().includes(q) || committeeNames.get(m.committee_id)?.toLowerCase().includes(q),
    )
  }, [started, search, committeeNames])

  const filtered = useMemo(() => {
    return searched.filter((m) => {
      if (committeeFilter !== 'all' && m.committee_id !== committeeFilter) return false
      if (stageFilter !== 'all' && stageOf(m.meeting_id) !== stageFilter) return false
      return true
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searched, stageFilter, committeeFilter, minutesByMeeting])

  const stats = useMemo(() => {
    const counts: Record<MeetingMinutesStage, number> = {
      none: 0,
      preparing: 0,
      review: 0,
      approval: 0,
      signature: 0,
      completed: 0,
    }
    for (const m of started) {
      const s = stageOf(m.meeting_id)
      if (s && s !== 'none') counts[s] += 1
    }
    return counts
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [started, minutesByMeeting])

  const sorted = useMemo(
    () => [...filtered].sort((a, b) => new Date(b.scheduled_at).getTime() - new Date(a.scheduled_at).getTime()),
    [filtered],
  )

  const committeeOptions = useMemo(
    () => [
      { value: 'all', label: 'كل اللجان' },
      ...(committees ?? []).map((c) => ({ value: c.committee_id, label: c.name })),
    ],
    [committees],
  )

  const stageOptions = useMemo(
    () => [
      { value: 'all', label: 'كل الحالات' },
      { value: 'none', label: STAGE_META.none.label },
      ...STAGE_ORDER.map((s) => ({ value: s, label: STAGE_META[s].label })),
    ],
    [],
  )

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-bold text-text-primary">إدارة المحاضر</h1>
        <p className="mt-1 text-sm text-text-muted">متابعة محاضر اللجان من الإعداد حتى اكتمال التوقيعات</p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {STAGE_ORDER.map((s, i) => (
          <motion.div
            key={s}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: i * 0.05, ease: 'easeOut' }}
          >
            <StatCard
              label={STAGE_META[s].label}
              value={stats[s]}
              icon={s === 'completed' ? <CheckCircle2 size={20} /> : s === 'signature' ? <FileSignature size={20} /> : <ClipboardList size={20} />}
              tone={STAT_TONES[s]}
              tintCard
            />
          </motion.div>
        ))}
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="sm:w-48">
          <Select
            value={stageFilter}
            onChange={(e) => setStageFilter(e.target.value as StageFilter)}
            options={stageOptions}
          />
        </div>
        <div className="sm:w-56">
          <Select
            value={committeeFilter}
            onChange={(e) => setCommitteeFilter(e.target.value)}
            options={committeeOptions}
          />
        </div>
        <div className="flex-1">
          <SearchInput value={search} onChange={setSearch} placeholder="ابحث عن محضر باسم الاجتماع أو اللجنة..." />
        </div>
      </div>

      {isLoading ? (
        <div className="flex flex-col gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : sorted.length === 0 ? (
        <EmptyState
          icon={<ClipboardList size={26} />}
          title={search || stageFilter !== 'all' || committeeFilter !== 'all' ? 'لا توجد نتائج مطابقة' : 'لا توجد محاضر بعد'}
          description={
            search || stageFilter !== 'all' || committeeFilter !== 'all'
              ? 'جرّبي تعديل الفلاتر أو كلمات بحث مختلفة'
              : 'تظهر محاضر الاجتماعات هنا فور بدء وقتها'
          }
        />
      ) : (
        <AnimatePresence mode="wait">
          <motion.div
            key="minutes-list"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="flex flex-col gap-4"
          >
            {sorted.map((meeting, i) => {
              const minutes = minutesByMeeting.get(meeting.meeting_id)
              const stage = minutes?.stage ?? null
              const query = queryFor(meeting.meeting_id)
              const status = query?.isError ? errorStatusOf(query.error) : null
              const notFinishedYet = status === 409
              const forbidden = status === 403
              const otherError = Boolean(query?.isError) && !notFinishedYet && !forbidden

              return (
                <motion.div
                  key={meeting.meeting_id}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2, delay: Math.min(i * 0.03, 0.3) }}
                >
                  <Card className={cn(cardToneClass(i), 'flex flex-col gap-4')}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-base font-semibold text-text-primary">{meeting.title}</h3>
                          {stage ? (
                            <MinutesStageBadge stage={stage} />
                          ) : notFinishedYet ? (
                            <span className="rounded-xs border border-neutral-border/30 bg-neutral-bg px-1.5 py-0.5 text-[10px] font-semibold text-neutral">
                              لم ينتهِ الاجتماع بعد
                            </span>
                          ) : forbidden ? (
                            <span className="inline-flex items-center gap-1 rounded-xs border border-danger/30 bg-danger-bg px-1.5 py-0.5 text-[10px] font-semibold text-danger">
                              <ShieldAlert size={11} /> لا تملكين صلاحية العرض
                            </span>
                          ) : otherError ? (
                            <span className="rounded-xs border border-neutral-border/30 bg-neutral-bg px-1.5 py-0.5 text-[10px] font-semibold text-neutral">
                              تعذّر تحميل حالة المحضر
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-text-secondary">
                          <span className="inline-flex items-center gap-1">
                            <Users2 size={12} /> {committeeNames.get(meeting.committee_id) ?? '—'}
                          </span>
                          <span className="text-text-muted">·</span>
                          <span>تاريخ الاجتماع {formatDate(meeting.scheduled_at)}</span>
                          {minutes?.owner && (
                            <>
                              <span className="text-text-muted">·</span>
                              <span className="inline-flex items-center gap-1">
                                <UserRound size={12} /> المسؤول عن الإعداد: {minutes.owner.first_name} {minutes.owner.last_name}
                              </span>
                            </>
                          )}
                        </p>
                      </div>
                      <Button
                        size="sm"
                        icon={stage === 'completed' ? <CheckCircle2 size={14} /> : <SquarePen size={14} />}
                        disabled={notFinishedYet || forbidden}
                        onClick={() => navigate(`/minutes/${meeting.meeting_id}`)}
                      >
                        {stage === 'completed'
                          ? 'عرض المحضر'
                          : notFinishedYet
                            ? 'بانتظار انتهاء الاجتماع'
                            : forbidden
                              ? 'لا صلاحية'
                              : 'متابعة الإجراء'}
                      </Button>
                    </div>

                    {minutes && (
                      <div className="flex flex-wrap gap-2">
                        <span className="rounded-full border border-border-default bg-bg-surface px-3 py-1.5 text-xs text-text-secondary">
                          حالة المراجعة: {minutes.reviewers.filter((r) => r.status === 'approved').length}/
                          {minutes.reviewers.length} مراجع
                        </span>
                        <span className="rounded-full border border-border-default bg-bg-surface px-3 py-1.5 text-xs text-text-secondary">
                          حالة الاعتماد: {minutes.approved_at ? 'معتمد' : 'بانتظار الاعتماد'}
                        </span>
                        <span className="rounded-full border border-border-default bg-bg-surface px-3 py-1.5 text-xs text-text-secondary">
                          حالة التوقيعات: {minutes.signatures.filter((s) => s.signed).length}/{minutes.signatures.length} توقيع
                        </span>
                      </div>
                    )}

                    {!forbidden && <StageTimeline stage={stage ?? 'none'} />}

                    {otherError && (
                      <p className="text-xs text-neutral">تعذّر تحميل تفاصيل هذا المحضر، حاولي مرة أخرى.</p>
                    )}
                  </Card>
                </motion.div>
              )
            })}
          </motion.div>
        </AnimatePresence>
      )}
    </div>
  )
}
