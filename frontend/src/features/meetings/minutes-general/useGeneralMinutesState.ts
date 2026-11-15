import { useCallback, useEffect, useRef, useState } from 'react'
import * as minutesApi from '@/api/meetingMinutes'
import { useSetMinutesInCache } from '@/hooks/useMeetingMinutes'
import { useToast } from '@/components/ui/Toast'
import { extractErrorMessage } from '@/lib/utils'
import type { MeetingMinutes, MinutesSection } from '@/types'

/**
 * الهدف:
 * حالة محرر "القالب العام" وحفظها — قسم قسم، أثناء التحرير الجماعي.
 *
 * المسؤولية:
 * - نسخة محلية من الأقسام يكتب فيها المستخدم مباشرة (بدون انتظار الخادم).
 * - حفظ تلقائي لكل قسم بعد توقف الكتابة (SAVE_DELAY_MS) عبر PATCH لقسم واحد —
 *   فتعديلان متزامنان على قسمين مختلفين لا يمسح أحدهما الآخر.
 * - دمج التحديثات الواردة (من الخادم أو أعضاء آخرين) في الأقسام اللي ما فيها
 *   كتابة معلّقة فقط — لا يضيع ما يكتبه المستخدم الآن.
 * - تعارض النسخ (409): القسم تغيّر من شخص آخر أو من بيانات الاجتماع ⇒ نعرض
 *   النسخة الحالية وننبّه المستخدم يعيد تعديله.
 * - عمليات هيكلية (إضافة/حذف موضوع) عبر الحفظ الكامل (PUT).
 *
 * المدخلات: meetingId، المحضر من الخادم، والتحديثات اللحظية من useMinutesRealtime.
 * المخرجات: الأقسام الحالية، دوال التعديل، وحالة الحفظ (جارٍ/خطأ/آخر حفظ).
 * التأثيرات الجانبية: طلبات PATCH/PUT، تحديث cache صفحة المحضر، Toast للتنبيهات.
 */

const SAVE_DELAY_MS = 900

function sortSections(sections: MinutesSection[]): MinutesSection[] {
  return [...sections].sort((a, b) => a.order - b.order)
}

interface Options {
  meetingId: string
  minutes: MeetingMinutes
  remoteSections: { sections: MinutesSection[]; at: number } | null
  remoteSection: { section: MinutesSection; at: number } | null
}

export function useGeneralMinutesState({ meetingId, minutes, remoteSections, remoteSection }: Options) {
  const { showToast } = useToast()
  const setMinutesInCache = useSetMinutesInCache()

  const [sections, setSections] = useState<MinutesSection[]>(() => sortSections(minutes.sections))
  const sectionsRef = useRef(sections)
  const dirty = useRef(new Set<string>())
  const inflight = useRef(new Set<string>())
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>())
  const [savingCount, setSavingCount] = useState(0)
  const [structuralSaving, setStructuralSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(null)

  const commit = useCallback((next: MinutesSection[]) => {
    sectionsRef.current = next
    setSections(next)
  }, [])

  const replaceOne = useCallback(
    (section: MinutesSection) => {
      commit(sectionsRef.current.map((s) => (s.id === section.id ? section : s)))
    },
    [commit],
  )

  /** نسخة الخادم تحل محل المحلية إلا للأقسام اللي فيها كتابة معلّقة أو حفظ جارٍ. */
  const mergeServer = useCallback(
    (server: MinutesSection[]) => {
      const local = new Map(sectionsRef.current.map((s) => [s.id, s]))
      const next = sortSections(server).map((s) => {
        const mine = local.get(s.id)
        if (mine && (dirty.current.has(s.id) || inflight.current.has(s.id))) {
          return mine.order === s.order ? mine : { ...mine, order: s.order }
        }
        return s
      })
      commit(next)
    },
    [commit],
  )

  useEffect(() => {
    mergeServer(minutes.sections)
  }, [minutes.sections, mergeServer])

  useEffect(() => {
    if (remoteSections) mergeServer(remoteSections.sections)
  }, [remoteSections, mergeServer])

  useEffect(() => {
    if (!remoteSection) return
    const { section } = remoteSection
    if (dirty.current.has(section.id) || inflight.current.has(section.id)) return
    if (!sectionsRef.current.some((s) => s.id === section.id)) return
    replaceOne(section)
  }, [remoteSection, replaceOne])

  // مرجع لأحدث save — لإعادة الجدولة من داخلها بدون مرجع ذاتي أثناء التعريف.
  const saveRef = useRef<(sectionId: string) => Promise<void>>(async () => undefined)

  const save = useCallback(
    async (sectionId: string) => {
      timers.current.delete(sectionId)
      if (inflight.current.has(sectionId)) {
        // حفظ سابق لنفس القسم ما خلص — نعيد المحاولة بعده حتى نرسل rev الصحيح.
        timers.current.set(sectionId, setTimeout(() => void saveRef.current(sectionId), 300))
        return
      }
      const sent = sectionsRef.current.find((s) => s.id === sectionId)
      if (!sent) return
      inflight.current.add(sectionId)
      dirty.current.delete(sectionId)
      setSavingCount((n) => n + 1)
      try {
        const result = await minutesApi.updateMinutesSection(meetingId, sent)
        const saved = result.sections.find((s) => s.id === sectionId)
        const current = sectionsRef.current.find((s) => s.id === sectionId)
        if (saved && current) {
          if (current !== sent) {
            // كتب المستخدم أثناء الحفظ: نبقي كتابته ونحدّث rev فقط للحفظ التالي.
            replaceOne({ ...current, rev: saved.rev })
          } else {
            replaceOne(saved)
          }
        }
        setMinutesInCache(meetingId, result)
        setError(null)
        setLastSavedAt(Date.now())
      } catch (err) {
        const conflict = minutesApi.sectionConflictOf(err)
        if (conflict) {
          dirty.current.delete(sectionId)
          const pending = timers.current.get(sectionId)
          if (pending) clearTimeout(pending)
          timers.current.delete(sectionId)
          replaceOne(conflict)
          showToast('تغيّر هذا الجزء من شخص آخر أو من بيانات الاجتماع — ظهرت آخر نسخة، أعد تعديلك إذا لزم', 'info')
        } else {
          dirty.current.add(sectionId)
          setError(extractErrorMessage(err))
        }
      } finally {
        inflight.current.delete(sectionId)
        setSavingCount((n) => n - 1)
      }
    },
    [meetingId, replaceOne, setMinutesInCache, showToast],
  )

  useEffect(() => {
    saveRef.current = save
  }, [save])

  /** تعديل قسم محليًا وجدولة حفظه بعد توقف الكتابة. */
  const updateSection = useCallback(
    (next: MinutesSection) => {
      replaceOne(next)
      dirty.current.add(next.id)
      const pending = timers.current.get(next.id)
      if (pending) clearTimeout(pending)
      timers.current.set(
        next.id,
        setTimeout(() => void save(next.id), SAVE_DELAY_MS),
      )
    },
    [replaceOne, save],
  )

  /** حفظ فوري لكل الأقسام المعلّقة (زر "حفظ" أو قبل عملية هيكلية). */
  const flush = useCallback(async () => {
    const ids = [...new Set([...dirty.current, ...timers.current.keys()])]
    for (const id of ids) {
      const pending = timers.current.get(id)
      if (pending) clearTimeout(pending)
      timers.current.delete(id)
    }
    await Promise.all(ids.map((id) => save(id)))
  }, [save])

  /** حفظ كامل لعملية هيكلية (إضافة/حذف موضوع) — يرسل القائمة بترتيبها الجديد. */
  const saveStructure = useCallback(
    async (next: MinutesSection[]) => {
      await flush()
      setStructuralSaving(true)
      try {
        const base = new Map(sectionsRef.current.map((s) => [s.id, s]))
        // الأقسام الموجودة بأحدث rev محلي (بعد flush)، والجديدة كما هي.
        const payload = next.map((s, index) => ({ ...(base.get(s.id) ?? s), order: index }))
        const result = await minutesApi.updateMinutesSections(meetingId, payload)
        dirty.current.clear()
        commit(sortSections(result.sections))
        setMinutesInCache(meetingId, result)
        setError(null)
        setLastSavedAt(Date.now())
      } catch (err) {
        if (minutesApi.sectionConflictOf(err)) {
          showToast('تغيّر المحضر من شخص آخر قبل الحفظ — حدّث الصفحة وأعد المحاولة', 'info')
        } else {
          showToast(extractErrorMessage(err), 'error')
        }
      } finally {
        setStructuralSaving(false)
      }
    },
    [commit, flush, meetingId, setMinutesInCache, showToast],
  )

  const addTopic = useCallback(() => {
    const current = sectionsRef.current
    const lastTopic = current.map((s) => s.kind).lastIndexOf('topic')
    const discussion = current.findIndex((s) => s.kind === 'rich' && s.data?.role === 'discussion')
    const insertAt = (lastTopic >= 0 ? lastTopic : discussion) + 1
    const topic: MinutesSection = {
      id: `new-${Date.now().toString(36)}`,
      kind: 'topic',
      title: 'موضوع جديد',
      body: '',
      order: insertAt,
      rev: 0,
      data: { heading: 'موضوع جديد' },
    }
    void saveStructure([...current.slice(0, insertAt), topic, ...current.slice(insertAt)])
  }, [saveStructure])

  const deleteSection = useCallback(
    (sectionId: string) => {
      void saveStructure(sectionsRef.current.filter((s) => s.id !== sectionId))
    },
    [saveStructure],
  )

  // مغادرة الصفحة/إغلاق اللوحة: نرسل أي كتابة معلّقة بدل ما تضيع.
  useEffect(() => {
    const pendingTimers = timers.current
    const pendingDirty = dirty.current
    return () => {
      for (const timer of pendingTimers.values()) clearTimeout(timer)
      for (const id of pendingDirty) {
        const section = sectionsRef.current.find((s) => s.id === id)
        if (section) void minutesApi.updateMinutesSection(meetingId, section).catch(() => undefined)
      }
    }
  }, [meetingId])

  return {
    sections,
    updateSection,
    flush,
    addTopic,
    deleteSection,
    saving: savingCount > 0 || structuralSaving,
    error,
    lastSavedAt,
  }
}
