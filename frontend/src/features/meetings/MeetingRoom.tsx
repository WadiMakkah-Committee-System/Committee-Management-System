import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion } from 'framer-motion'
import { Captions, CaptionsOff, Circle, Loader2, Settings2, Square, TimerOff } from 'lucide-react'
import { useMeetingDetail } from '@/hooks/useMeetings'
import { useCommittees } from '@/hooks/useCommittees'
import { useAuthStore } from '@/store/authStore'
import { useMeetingRealtime } from '@/hooks/useMeetingRealtime'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/components/ui/Toast'
import { MeetingRoomAppRail } from './room/MeetingRoomAppRail'
import { MeetingRoomSidebar, type RoomPanelKey } from './room/MeetingRoomSidebar'
import { MeetingRoomHeader } from './room/MeetingRoomHeader'
import { AgoraMeetingStage } from './room/AgoraMeetingStage'
import { useAgoraCall } from './room/useAgoraCall'
import { useMeetingRecorder } from './room/useMeetingRecorder'
import { useSpeechCaptions, type OwnFinalCaption } from './room/useSpeechCaptions'
import { EmbeddedTeamsStage } from './room/EmbeddedTeamsStage'
import { useTeamsEmbeddedCall } from './room/useTeamsEmbeddedCall'
import { MeetingControls } from './room/MeetingControls'
import { ParticipantsPanel } from './room/panels/ParticipantsPanel'
import { AgendaPanel } from './room/panels/AgendaPanel'
import { DecisionsPanel } from './room/panels/DecisionsPanel'
import { AttachmentsPanel } from './room/panels/AttachmentsPanel'
import { ChatPanel } from './room/panels/ChatPanel'
import { ActivityPanel } from './room/panels/ActivityPanel'
import { LobbyPanel } from './room/panels/LobbyPanel'
import { GuestWaitingScreen } from './room/GuestWaitingScreen'
import { VotingOverlay } from './room/VotingOverlay'
import { AgendaTimerBanner } from './room/AgendaTimerBanner'
import { ReactionsButton } from './room/ReactionsButton'
import { DeviceCheck } from './room/DeviceCheck'
import { isDeviceCheckDone, type DevicePrefs } from './room/devicePrefs'
import { useMeetingAttendance } from './room/useMeetingAttendance'
import { CaptionsOverlay } from './room/CaptionsOverlay'
import { CatchUpButton } from './room/CatchUpButton'
import { saveTranscriptSegments } from '@/api/meetings'
import type { CaptionLine, FinalCaption } from './room/useTeamsEmbeddedCall'
import { scopeFor } from '@/lib/utils'
import type { MeetingAgendaItem } from '@/types'

/** كل كم مللي ثانية تُحدَّث تفاصيل الاجتماع (الحالة تحديدًا) أثناء بقاء
 * الغرفة مفتوحة — يكفي للكشف عن انتهاء وقت الاجتماع (_maybe_transition_status
 * بالباك-إند، قرار موثّق مع لاما 2026-09-05: تحويل كسول بلا Scheduler
 * منفصل) خلال دقيقة تقريبًا من انتهائه الفعلي، بلا إغراق الخادم بطلبات. */
const MEETING_STATUS_POLL_MS = 20_000
/** مهلة السماح قبل إغلاق الغرفة تلقائيًا بعد اكتشاف انتهاء وقت الاجتماع —
 * تعطي فرصة لقراءة رسالة "انتهى الاجتماع" قبل الإخراج الفعلي. */
const AUTO_LEAVE_GRACE_MS = 6_000

/**
 * تحديث 2026-11-04 (قرار لاما — الرجوع لـAgora مع حفظ Teams):
 * - اجتماع عن بعد غير مربوط بـTeams ⇒ فيديو/صوت Agora داخل الغرفة (AgoraMeetingStage +
 *   useAgoraCall)، تسجيل صوت كل الأعضاء بزر الرئيس (useMeetingRecorder)، وترجمة نصية
 *   مجانية من متصفح كل عضو (useSpeechCaptions). التفاعلات ومشاركة الشاشة عبر القناة اللحظية.
 * - اجتماع Teams قديم ⇒ نفس مساره السابق (EmbeddedTeamsStage) بدون أي تغيير.
 *
 * (السابق) غرفة الاجتماع — مساحة إدارة الجلسة بجانب Microsoft Teams (تحديث 2026-11-02:
 * أُزيل فيديو Agora بالكامل بقرار لاما، والصوت/الفيديو/التسجيل داخل تيمز).
 * التصميم نفسه (تعديل 2026-09-06 لمطابقة الواجهة المرجعية) باقٍ كما هو:
 * شريط عام داكن (MeetingRoomAppRail.tsx)، ولوحة ديناميكية بيضاء (340px)
 * بتبويبات أعلاها (MeetingRoomSidebar.tsx)، والمساحة الرئيسية صارت
 * TeamsMeetingStage.tsx (زر الانضمام عبر تيمز) بدل مربعات الفيديو، مع شريط
 * تحكم مبسّط (رفع اليد/مغادرة/ملء الشاشة).
 *
 * الواجهة الخارجية (props) لم تتغيّر — MeetingDetailPage.tsx ما زال يستدعيها
 * بنفس الشكل: <MeetingRoom meetingId meetingTitle onClose />.
 */
export function MeetingRoom({
  meetingId,
  onClose,
}: {
  meetingId: string
  meetingTitle: string
  onClose: () => void
}) {
  const currentUser = useAuthStore((s) => s.user)
  const authMethod = useAuthStore((s) => s.authMethod)
  const { showToast } = useToast()
  // Polling أثناء بقاء الغرفة مفتوحة فقط (راجعي useMeetingDetail) — يكشف
  // انتهاء وقت الاجتماع (status → finished) بدون حاجة لإعادة فتح الصفحة.
  const meetingQuery = useMeetingDetail(meetingId, { refetchIntervalMs: MEETING_STATUS_POLL_MS })
  // بلاغ لاما 2026-09-13 (لايف): زر "قرار جديد" داخل غرفة الاجتماع كان
  // يظهر لأي مشارك بلا أي فحص صلاحية (بخلاف DecisionsPage.tsx خارج
  // الغرفة اللي تحجبه خلف canCreateAnyDecision بشكل صحيح). نفس منطق
  // الفحص هنا بالضبط: رئيس هذه اللجنة تحديدًا، أو decisions.create
  // بنطاق 'all' فعليًا.
  const { data: committees } = useCommittees()
  const realtime = useMeetingRealtime(meetingId)
  // تجربة الانضمام المدمج (Azure Communication Services): فيديو اجتماع Teams
  // داخل الغرفة نفسها بدل فتح تطبيق تيمز — راجعي useTeamsEmbeddedCall.ts.
  // onAutoAdmitted: أعضاء اللجنة اللي دخلوا كضيوف يُقبلون تلقائيًا — نبلّغ الموظف.
  // جمل الترجمة النصية المكتملة — جهاز رئيس اللجنة يجمعها ويرسلها كل 5 ثواني
  // (مصدر واحد للحفظ). البند الحالي يُربط مع كل جملة للإحصائيات.
  const captionBufferRef = useRef<(FinalCaption & { agendaItemId: string | null })[]>([])
  const discussingIdRef = useRef<string | null>(null)
  const isCaptionsSaverRef = useRef(false)
  const embeddedCall = useTeamsEmbeddedCall(meetingId, {
    onAutoAdmitted: (name) => showToast(`دخل ${name} (عضو باللجنة)`, 'info'),
    onFinalCaption: (c) => {
      if (isCaptionsSaverRef.current) captionBufferRef.current.push({ ...c, agendaItemId: discussingIdRef.current })
    },
  })

  // ============================== Agora (قرار لاما 2026-11-04) ==============================
  // الاجتماعات عن بعد غير المربوطة بـTeams تفتح بـAgora داخل المنصة. اجتماعات Teams
  // القديمة تبقى على مسارها أعلاه (embeddedCall) — الاثنين محفوظين.
  const meetingForNames = meetingQuery.data
  const namesById = useMemo(() => {
    const map = new Map<string, string>()
    for (const p of meetingForNames?.participants ?? []) map.set(p.user_id, `${p.first_name} ${p.last_name}`)
    return map
  }, [meetingForNames?.participants])
  const namesRef = useRef(namesById)
  namesRef.current = namesById
  const agoraCall = useAgoraCall(meetingId, { nameOf: (id) => namesRef.current.get(id) ?? 'مشارك' })
  const recorder = useMeetingRecorder(meetingId, {
    getAudioSources: agoraCall.getAudioSources,
    audioVersion: agoraCall.audioVersion,
    onStateChange: (state) =>
      realtime.applyRecordingState({
        active: state.active,
        sessionId: state.session_id,
        startedBy: state.started_by,
        startedByName: state.started_by_name,
        startedAt: state.started_at,
      }),
  })
  // الترجمة النصية المجانية (Web Speech): كل عضو يحوّل كلامه هو ويحفظه (own_speech).
  const ownCaptionBufferRef = useRef<(OwnFinalCaption & { agendaItemId: string | null })[]>([])

  const [activePanel, setActivePanel] = useState<RoomPanelKey>('participants')
  const [confirmLeaveOpen, setConfirmLeaveOpen] = useState(false)
  const [pendingAgendaItemId, setPendingAgendaItemId] = useState<string | null>(null)

  // عدد رسائل المحادثة "المُشاهَدة" — State حقيقي يُحدَّث فقط داخل معالج
  // الحدث عند التنقل إلى لوحة "المحادثة" (انظر handleSelectPanel)، لا أثناء
  // الـrender ولا داخل useEffect. طالما اللوحة مفتوحة، شارة "غير مقروءة"
  // بالشريط العام مخفية أصلًا (!isActive بـMeetingRoomAppRail)، فلا حاجة
  // لتحديث مستمر أثناء بقاء اللوحة مفتوحة — فقط عند لحظة الدخول إليها.
  const [seenChatCount, setSeenChatCount] = useState(0)
  const hasNewChatMessage = realtime.liveMessages.length > seenChatCount

  function handleSelectPanel(key: RoomPanelKey) {
    setActivePanel(key)
    if (key === 'chat') {
      setSeenChatCount(realtime.liveMessages.length)
    }
  }

  const raisedHandUserIds = useMemo(
    () => new Set(realtime.raisedHands.map((h) => h.userId)),
    [realtime.raisedHands],
  )
  const iRaisedHand = currentUser ? raisedHandUserIds.has(currentUser.user_id) : false


  // إصلاح 2026-09-14 (بلاغ لاما الثاني — ضغط رئيس اللجنة "بدء المناقشة"
  // لا يعطيه أي مؤشر، كأن الزر ثابت لا يفعل شيئًا): announceDiscussing
  // الآن Promise حقيقي بنتيجة واضحة (راجعي useMeetingRealtime.ts) —
  // pendingAgendaItemId يعطّل البند أثناء الإرسال (يمنع ضغط مزدوج)،
  // وtoast فوري يوضّح النجاح أو سبب الفشل الحقيقي، بدل انتظار بثّ
  // "agenda.discussing" فقط كمؤشر وحيد على حدوث شيء.
  async function handleStartDiscussing(item: MeetingAgendaItem, durationSeconds: number | null = null) {
    setPendingAgendaItemId(item.agenda_item_id)
    try {
      const result = await realtime.announceDiscussing(item.agenda_item_id, item.title, durationSeconds)
      if (result.ok) {
        showToast(`بدأت مناقشة: ${item.title}`, 'success')
      } else {
        showToast(result.error || 'تعذر بدء المناقشة.', 'error')
      }
    } finally {
      setPendingAgendaItemId(null)
    }
  }

  // المغادرة هنا تُغلق غرفة النظام فقط — نافذة تيمز مستقلة يغادرها
  // المستخدم من تيمز نفسه (لا يوجد اتصال وسائط بالمتصفح لإنهائه بعد Agora).
  async function handleConfirmLeave() {
    setConfirmLeaveOpen(false)
    // التسجيل شغّال ⇒ نوقفه ونرفع آخر قطعة قبل الخروج (ما يضيع شي).
    if (recorder.status === 'recording') await recorder.stop()
    await embeddedCall.leave()
    await agoraCall.leave()
    onClose()
  }

  const meeting = meetingQuery.data
  const isAgoraMeeting = Boolean(meeting && meeting.mode === 'remote' && !meeting.has_teams_meeting)
  const connected = isAgoraMeeting ? agoraCall.phase === 'connected' : embeddedCall.phase === 'connected'
  // الحضور التلقائي: جلسة لحظة الدخول الفعلي للاجتماع + نبضات + خروج.
  useMeetingAttendance(meetingId, connected)

  // الترجمة النصية (قرار لاما 2026-11-03): رئيس اللجنة يشغّلها للكل عبر القناة
  // اللحظية ⇒ كل جهاز داخل الاجتماع يشغّلها عنده. كل عضو يقدر يخفي العرض عنده.
  const [captionsHidden, setCaptionsHidden] = useState(false)
  const captionsWanted = realtime.captionsState.enabled && embeddedCall.phase === 'connected'
  useEffect(() => {
    if (captionsWanted && !embeddedCall.captionsActive) void embeddedCall.startCaptions(realtime.captionsState.language)
    if (!captionsWanted && (embeddedCall.captionsActive || embeddedCall.captionsError)) void embeddedCall.stopCaptions()
  }, [captionsWanted, realtime.captionsState.language, embeddedCall])

  // Agora: كل جهاز يتعرف على كلام صاحبه فقط (وما يسمع وهو كاتم)، ويبثه ويحفظه.
  const speech = useSpeechCaptions({
    enabled: isAgoraMeeting && realtime.captionsState.enabled && agoraCall.phase === 'connected',
    muted: agoraCall.micMuted,
    language: realtime.captionsState.language,
    onLine: realtime.sendCaptionLine,
    onFinal: (c) => ownCaptionBufferRef.current.push({ ...c, agendaItemId: discussingIdRef.current }),
  })
  const agoraCaptionLines = useMemo<CaptionLine[]>(() => {
    const lines: CaptionLine[] = realtime.remoteCaptions.map((l) => ({
      id: l.id,
      speakerName: l.speakerName,
      text: l.text,
      final: l.final,
    }))
    if (speech.ownLine) {
      lines.push({ id: `me:${speech.ownLine.key}`, speakerName: 'أنت', text: speech.ownLine.text, final: speech.ownLine.final })
    }
    return lines
  }, [realtime.remoteCaptions, speech.ownLine])

  useEffect(() => {
    discussingIdRef.current = realtime.discussingAgendaItem?.id ?? null
  }, [realtime.discussingAgendaItem])

  // Agora: جملي المكتملة تنحفظ كل 5 ثواني (الخادم يحدد المتحدث = أنا).
  useEffect(() => {
    const id = setInterval(() => {
      const batch = ownCaptionBufferRef.current.splice(0, 200)
      if (batch.length === 0) return
      saveTranscriptSegments(
        meetingId,
        batch.map((c) => ({
          client_key: c.clientKey,
          speaker_raw_id: null,
          speaker_name: '',
          text: c.text,
          spoken_at: c.spokenAt,
          language: c.language,
          agenda_item_id: c.agendaItemId,
        })),
        true,
      ).catch(() => {
        ownCaptionBufferRef.current.unshift(...batch)
      })
    }, 5000)
    return () => clearInterval(id)
  }, [meetingId])

  useEffect(() => {
    const id = setInterval(() => {
      const batch = captionBufferRef.current.splice(0, 200)
      if (batch.length === 0) return
      saveTranscriptSegments(
        meetingId,
        batch.map((c) => ({
          client_key: c.clientKey,
          speaker_raw_id: c.speakerRawId,
          speaker_name: c.speakerName,
          text: c.text,
          spoken_at: c.spokenAt,
          language: c.language,
          agenda_item_id: c.agendaItemId,
        })),
      ).catch(() => {
        // فشل مؤقت (نت) ⇒ نرجعها للطابور ونحاول بعد 5 ثواني.
        captionBufferRef.current.unshift(...batch)
      })
    }, 5000)
    return () => clearInterval(id)
  }, [meetingId])

  async function toggleMeetingCaptions() {
    const result = await realtime.setCaptions(!realtime.captionsState.enabled)
    if (!result.ok) showToast(result.error || 'تعذر تغيير الترجمة النصية.', 'error')
  }

  // تحديث لاما 2026-11-03: زر "دخول الاجتماع" (خارج الغرفة) هو الدخول نفسه —
  // أول ما تفتح الغرفة يبدأ الاتصال تلقائيًا، بدون زر انضمام ثاني داخل الإطار.
  // مرة واحدة فقط لكل فتح للغرفة؛ إعادة المحاولة بعدها من زر "إعادة الانضمام".
  // فحص الكاميرا والمايك أول مرة على الجهاز (قرار لاما 2026-11-03) — بعده
  // الدخول تلقائي. needsDeviceCheck=true ⇒ شاشة الفحص بدل الغرفة لين "دخول الآن".
  const [needsDeviceCheck, setNeedsDeviceCheck] = useState(() => !isDeviceCheckDone())
  const [deviceSettingsOpen, setDeviceSettingsOpen] = useState(false)
  const autoStartedRef = useRef(false)
  useEffect(() => {
    if (!meeting || autoStartedRef.current || needsDeviceCheck) return
    if (!meeting.has_teams_meeting && !isAgoraMeeting) return
    if (meeting.status === 'finished' || meeting.status === 'recorded') return
    autoStartedRef.current = true
    if (isAgoraMeeting) void agoraCall.start()
    else void embeddedCall.start(false)
  }, [meeting, isAgoraMeeting, embeddedCall, agoraCall, needsDeviceCheck])

  /** حفظ إعدادات الأجهزة أثناء الاجتماع ⇒ تبديل الأجهزة + الكاميرا/المايك حسب الاختيار. */
  async function applyDeviceSettings(prefs: DevicePrefs) {
    setDeviceSettingsOpen(false)
    const active = isAgoraMeeting ? agoraCall : embeddedCall
    await active.switchDevices(prefs)
    if (prefs.micOn === active.micMuted) await active.toggleMic()
    if (prefs.cameraOn !== active.cameraOn) await active.toggleCamera()
  }

  /** مشاركة الشاشة (Agora): نبلّغ الكل عشان يعرضونها كبيرة تلقائيًا. */
  async function handleAgoraScreenShare() {
    const sharing = await agoraCall.toggleScreenShare()
    if (sharing !== null) realtime.announceScreenShare(sharing)
  }

  /** زر التسجيل (رئيس اللجنة): بدء/إيقاف — صوت كل الأعضاء. */
  async function handleToggleRecording() {
    if (recorder.status === 'recording') {
      await recorder.stop()
      showToast('توقف التسجيل — انحفظ للمسودة', 'success')
    } else if (recorder.status === 'idle') {
      await recorder.start()
    }
  }
  useEffect(() => {
    if (recorder.error) showToast(recorder.error, 'error')
  }, [recorder.error, showToast])

  // طابور المتحدثين: تنبيه لما الرئيس يعطي أحد الكلمة.
  const floorGiven = realtime.floorGiven
  useEffect(() => {
    if (!floorGiven) return
    if (floorGiven.userId === currentUser?.user_id) showToast('رئيس اللجنة أعطاك الكلمة 🎤', 'success')
    else if (floorGiven.fullName) showToast(`الكلمة الآن لـ ${floorGiven.fullName}`, 'info')
  }, [floorGiven, currentUser?.user_id, showToast])

  async function handleStopDiscussing() {
    const result = await realtime.stopDiscussing()
    if (!result.ok) showToast(result.error || 'تعذر إيقاف المناقشة.', 'error')
  }

  async function handleGiveFloor(userId: string) {
    const result = await realtime.giveFloor(userId)
    if (!result.ok) showToast(result.error || 'تعذر إعطاء الكلمة.', 'error')
  }

  // ضيف (دخل المنصة بدون حساب Microsoft بالشركة) ⇒ شاشة انتظار كاملة لين
  // ينقبل — ما يشوف الأجندة/المرفقات/القرارات/المشاركين قبل القبول.
  const isGuest =
    embeddedCall.identity === 'guest' || (embeddedCall.identity === null && authMethod !== 'microsoft')
  const showGuestGate = Boolean(meeting?.has_teams_meeting) && isGuest && embeddedCall.phase !== 'connected'

  // قاعة الانتظار: تظهر لمن يقدر يقبل (داخل بحساب Microsoft). تنبيه منبثق لكل
  // منتظر جديد ما انقبل تلقائيًا خلال ثانيتين (يعني مو عضو دخل من المنصة).
  const canSeeLobby = embeddedCall.identity === 'teams_user' && embeddedCall.phase === 'connected'
  const lobbyRef = useRef(embeddedCall.lobbyParticipants)
  const announcedLobbyRef = useRef(new Set<string>())
  useEffect(() => {
    lobbyRef.current = embeddedCall.lobbyParticipants
    if (!canSeeLobby) return
    const timers = embeddedCall.lobbyParticipants
      .filter((p) => !announcedLobbyRef.current.has(p.key))
      .map((p) => {
        announcedLobbyRef.current.add(p.key)
        return setTimeout(() => {
          if (lobbyRef.current.some((w) => w.key === p.key)) {
            showToast(`${p.name} ينتظر الدخول — من تبويب "الانتظار"`, 'info')
          }
        }, 2000)
      })
    return () => timers.forEach(clearTimeout)
  }, [embeddedCall.lobbyParticipants, canSeeLobby, showToast])

  const canCreateDecision = Boolean(
    currentUser &&
      meeting &&
      (scopeFor(currentUser, 'decisions.create') === 'all' ||
        committees?.some(
          (c) => c.committee_id === meeting.committee_id && c.chair_user_id === currentUser.user_id,
        )),
  )

  // إصلاح 2026-09-14 (بلاغ لاما — الرئيس يضغط "بدء المناقشة" وأي عضو
  // ثاني بالغرفة يقدر يضغط بند غيره فتتغيّر الحالة لحظيًا فوق ضغطته،
  // فتبدو الواجهة "ما تستجيب صح" من منظورها): بس رئيس اللجنة (أو صاحب
  // صلاحية meetings.agenda.item.update عامة) يقدر يبدأ/يغيّر بند
  // المناقشة الحالي — الأعضاء يشوفون الجدول للقراءة فقط. نفس نمط
  // canCreateDecision أعلاه بالضبط؛ التحقق الفعلي مكرَّر بالباك-إند
  // (require_agenda_manage_access) لأن هذا مجرد تحسين واجهة.
  const canManageAgenda = Boolean(
    currentUser &&
      meeting &&
      (scopeFor(currentUser, 'meetings.agenda.item.update') === 'all' ||
        committees?.some(
          (c) => c.committee_id === meeting.committee_id && c.chair_user_id === currentUser.user_id,
        )),
  )

  // جهاز رئيس اللجنة هو اللي يحفظ الترجمة النصية (مصدر واحد).
  useEffect(() => {
    isCaptionsSaverRef.current = canManageAgenda
  }, [canManageAgenda])

  // يحدد ظهور تنبيه "شغّل التسجيل والتفريغ من داخل تيمز" (TeamsMeetingStage)
  // — نفس قاعدة من يسجّل (رئيس اللجنة أو meetings.record_audio عامة). أصل
  // الشرط: إصلاح 2026-09-14 (بلاغ لاما — عضو اللجنة العادي كان يقدر يبدأ
  // التسجيل الصوتي من شريط التحكم السفلي، والمفترض يكون لرئيس اللجنة فقط):
  // الباك-إند أصلًا يرفض حفظ/رفع التسجيل لغير صاحب صلاحية
  // meetings.record_audio (راجعي meeting_service.py::upload_recording)،
  // لكن الواجهة كانت تعرض زر "تسجيل" بلا أي فحص — فيدخل العضو بتجربة
  // تسجيل كاملة (getUserMedia + MediaRecorder محليًا، لا تحتاج إذن خادم
  // لتبدأ) لتفشل فقط عند الرفع النهائي. نفس نمط canManageAgenda أعلاه
  // بالضبط: رئيس اللجنة، أو صاحب صلاحية meetings.record_audio بنطاق عام.
  const canRecord = Boolean(
    currentUser &&
      meeting &&
      (scopeFor(currentUser, 'meetings.record_audio') === 'all' ||
        committees?.some(
          (c) => c.committee_id === meeting.committee_id && c.chair_user_id === currentUser.user_id,
        )),
  )

  // تعديل لاما 2026-09-06: "انتهى وقت الاجتماع وما اغلق تلقائيًا" — الحالة
  // نفسها تُحسَب فعليًا بالباك-إند (_maybe_transition_status، تحويل كسول
  // موثّق بلا Scheduler منفصل)، لكن أحدًا لم يكن يطلب قراءة جديدة أثناء
  // بقاء الغرفة مفتوحة (بلا Polling سابقًا) فتبقى الحالة القديمة ظاهرة
  // بالواجهة إلى الأبد. الـPolling أعلاه يحل هذا، وهنا نتصرف فعليًا عند
  // اكتشاف finished/recorded: نعرض تنبيهًا ثم نُخرج الجميع تلقائيًا بعد
  // مهلة سماح قصيرة (بدل تركهم بغرفة "منتهية" بلا أي إجراء).
  const meetingEnded = meeting?.status === 'finished' || meeting?.status === 'recorded'
  const autoLeaveTriggeredRef = useRef(false)

  useEffect(() => {
    if (!meetingEnded || autoLeaveTriggeredRef.current) return
    autoLeaveTriggeredRef.current = true
    const timeout = setTimeout(onClose, AUTO_LEAVE_GRACE_MS)
    return () => clearTimeout(timeout)
    // عمدًا: onClose لا يدخل بالـdeps — الاعتماد الفعلي الوحيد للتشغيل هو
    // meetingEnded نفسه (الحارس autoLeaveTriggeredRef يمنع أي تكرار).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetingEnded])

  return createPortal(
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.18 }}
      dir="rtl"
      // z-[45]: أسفل ConfirmDialog/Modal العامّة (z-50 — components/ui/Modal.tsx)
      // عمدًا، وإلا فأي Modal يُفتح من داخل الغرفة (تأكيد المغادرة تحديدًا)
      // يُرسَم خلف خلفية الغرفة المعتمة فيبدو "بلا استجابة" عند الضغط
      // (كان z-[60] سابقًا — أعلى من Modal — وهذا سبب عطل زر "مغادرة
      // الاجتماع" الذي رصدته لاما 2026-09-06). ما زال أعلى من الشريط
      // الجانبي للتطبيق (z-40 — Sidebar.tsx) لتغطية كامل الشاشة كما يجب.
      className="fixed inset-0 z-[45] flex flex-col bg-[#0d1220]"
    >
      {!meeting ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-white/70">
          <Loader2 size={28} className="animate-spin" />
          <p className="text-sm">جاري تحميل بيانات الاجتماع...</p>
        </div>
      ) : needsDeviceCheck && (meeting.has_teams_meeting || isAgoraMeeting) ? (
        <DeviceCheck mode="prejoin" onDone={() => setNeedsDeviceCheck(false)} />
      ) : showGuestGate ? (
        <GuestWaitingScreen meeting={meeting} call={embeddedCall} onLeave={() => setConfirmLeaveOpen(true)} />
      ) : (
        <>
          <MeetingRoomHeader meeting={meeting} onOpenParticipants={() => handleSelectPanel('participants')} />

          <div className="flex min-h-0 flex-1">
            <MeetingRoomAppRail
              onExitClick={() => setConfirmLeaveOpen(true)}
              onChatClick={() => handleSelectPanel('chat')}
              chatActive={activePanel === 'chat'}
              hasUnreadChat={hasNewChatMessage}
            />

            <aside className="flex w-[340px] shrink-0 flex-col overflow-hidden border-l border-border-default bg-bg-app">
              <MeetingRoomSidebar
                active={activePanel}
                onSelect={handleSelectPanel}
                raisedHandCount={realtime.raisedHands.length}
                showLobby={canSeeLobby}
                lobbyCount={embeddedCall.lobbyParticipants.length}
              />

              <div className="min-h-0 flex-1 overflow-hidden">
                {activePanel === 'participants' && (
                  <ParticipantsPanel
                    participants={meeting.participants}
                    onlineUserIds={realtime.onlineUserIds}
                    raisedHandUserIds={raisedHandUserIds}
                    currentUserId={currentUser?.user_id ?? ''}
                    speakerQueue={realtime.raisedHands}
                    canGiveFloor={canManageAgenda}
                    onGiveFloor={(id) => void handleGiveFloor(id)}
                  />
                )}
                {activePanel === 'agenda' && (
                  <AgendaPanel
                    agendaItems={meeting.agenda_items}
                    discussingAgendaItemId={realtime.discussingAgendaItem?.id ?? null}
                    onStartDiscussing={handleStartDiscussing}
                    canManage={canManageAgenda}
                    pendingItemId={pendingAgendaItemId}
                  />
                )}
                {activePanel === 'decisions' && (
                  <DecisionsPanel
                    meetingId={meetingId}
                    committeeId={meeting.committee_id}
                    currentUserId={currentUser?.user_id ?? ''}
                    canCreate={canCreateDecision}
                    meetingScheduledAt={meeting.scheduled_at}
                    meetingScheduledEndAt={meeting.scheduled_end_at}
                  />
                )}
                {activePanel === 'attachments' && (
                  <AttachmentsPanel meetingId={meetingId} />
                )}
                {activePanel === 'chat' && (
                  <ChatPanel
                    meetingId={meetingId}
                    liveMessages={realtime.liveMessages}
                    currentUserId={currentUser?.user_id ?? ''}
                    onSend={realtime.sendChatMessage}
                    connectionStatus={realtime.status}
                  />
                )}
                {activePanel === 'activity' && <ActivityPanel events={realtime.activityEvents} />}
                {activePanel === 'lobby' && canSeeLobby && (
                  <LobbyPanel
                    participants={embeddedCall.lobbyParticipants}
                    onAdmit={embeddedCall.admit}
                    onReject={embeddedCall.reject}
                  />
                )}
              </div>
            </aside>

            <div className="relative flex min-h-0 flex-1 flex-col gap-3 p-3">
              {/* تعديل لاما 2026-09-06: "بدأ مناقشة البند ما ظهر إشعار أعلى
                  الصفحة" — بث agenda.discussing كان يُسجَّل بسجل النشاط فقط
                  بلا أي عنصر ظاهر بمنطقة الفيديو الرئيسية نفسها. */}
              {realtime.discussingAgendaItem && (
                <AgendaTimerBanner
                  item={realtime.discussingAgendaItem}
                  onStop={canManageAgenda ? () => void handleStopDiscussing() : undefined}
                />
              )}

              {meetingEnded && (
                <div className="flex items-center gap-2 rounded-md border border-warning/30 bg-warning-bg px-3 py-2 text-[12px] font-medium text-warning">
                  <TimerOff size={14} className="shrink-0" />
                  <span>انتهى الوقت المحدد لهذا الاجتماع — سيتم إغلاق الغرفة تلقائيًا خلال لحظات.</span>
                </div>
              )}

              {meeting.has_teams_meeting ? (
                <EmbeddedTeamsStage
                  meeting={meeting}
                  call={embeddedCall}
                  localName={currentUser ? `${currentUser.first_name} ${currentUser.last_name}` : 'أنت'}
                  canRecord={canRecord}
                />
              ) : (
                <AgoraMeetingStage
                  call={agoraCall}
                  localName={currentUser ? `${currentUser.first_name} ${currentUser.last_name}` : 'أنت'}
                  selfUserId={currentUser?.user_id ?? ''}
                  reactions={realtime.reactions}
                  screenSharerIds={realtime.screenSharerIds}
                  recordingState={realtime.recordingState}
                />
              )}

              {embeddedCall.captionsActive && !captionsHidden && (
                <CaptionsOverlay lines={embeddedCall.captionLines} error={null} />
              )}
              {realtime.captionsState.enabled && embeddedCall.captionsError && (
                <CaptionsOverlay lines={[]} error={embeddedCall.captionsError} />
              )}
              {isAgoraMeeting && realtime.captionsState.enabled && !captionsHidden && (
                <CaptionsOverlay lines={agoraCaptionLines} error={speech.error} />
              )}

              {currentUser && (
                <VotingOverlay
                  meetingId={meetingId}
                  currentUserId={currentUser.user_id}
                  onOpenDecisions={() => handleSelectPanel('decisions')}
                />
              )}

              <MeetingControls
                extra={
                  connected ? (
                    <>
                      {isAgoraMeeting && canRecord && (
                        <button
                          type="button"
                          onClick={() => void handleToggleRecording()}
                          disabled={recorder.status === 'starting' || recorder.status === 'stopping'}
                          aria-label={recorder.status === 'recording' ? 'إيقاف التسجيل' : 'تسجيل صوت الاجتماع'}
                          title={
                            recorder.status === 'recording'
                              ? 'إيقاف التسجيل (يُحفظ للمسودة)'
                              : 'تسجيل صوت كل الأعضاء'
                          }
                          className={
                            recorder.status === 'recording'
                              ? 'flex h-11 items-center gap-1.5 rounded-full bg-danger px-4 text-[12px] font-semibold text-white transition-all hover:brightness-110 active:scale-95'
                              : 'flex h-11 items-center gap-1.5 rounded-full bg-white/10 px-4 text-[12px] font-semibold text-white transition-all hover:bg-white/20 active:scale-95 disabled:opacity-50'
                          }
                        >
                          {recorder.status === 'recording' ? (
                            <Square size={14} className="fill-white" />
                          ) : recorder.status === 'idle' ? (
                            <Circle size={14} className="fill-danger text-danger" />
                          ) : (
                            <Loader2 size={14} className="animate-spin" />
                          )}
                          {recorder.status === 'recording'
                            ? 'إيقاف التسجيل'
                            : recorder.status === 'stopping'
                              ? 'جاري الحفظ...'
                              : 'تسجيل'}
                        </button>
                      )}
                      <ReactionsButton
                        onReact={(type) =>
                          isAgoraMeeting
                            ? realtime.sendReaction(type, currentUser?.user_id ?? '')
                            : void embeddedCall.sendReaction(type)
                        }
                      />
                      <button
                        type="button"
                        onClick={() =>
                          canManageAgenda ? void toggleMeetingCaptions() : setCaptionsHidden((v) => !v)
                        }
                        disabled={!canManageAgenda && !realtime.captionsState.enabled}
                        aria-label="الترجمة النصية"
                        title={
                          canManageAgenda
                            ? realtime.captionsState.enabled
                              ? 'إيقاف الترجمة النصية للكل'
                              : 'تشغيل الترجمة النصية للكل'
                            : realtime.captionsState.enabled
                              ? captionsHidden
                                ? 'إظهار الترجمة النصية'
                                : 'إخفاء الترجمة النصية عندي'
                              : 'الترجمة النصية مطفية (يشغّلها رئيس اللجنة)'
                        }
                        className={
                          realtime.captionsState.enabled && !captionsHidden
                            ? 'flex h-11 w-11 items-center justify-center rounded-full bg-brand-primary text-white transition-all hover:brightness-110 active:scale-95'
                            : 'flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-white transition-all hover:bg-white/20 active:scale-95 disabled:opacity-40'
                        }
                      >
                        {realtime.captionsState.enabled && !captionsHidden ? <Captions size={18} /> : <CaptionsOff size={18} />}
                      </button>
                      <CatchUpButton meetingId={meetingId} />
                      <button
                        type="button"
                        onClick={() => setDeviceSettingsOpen(true)}
                        aria-label="إعدادات الأجهزة"
                        title="إعدادات الأجهزة"
                        className="flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-white transition-all hover:bg-white/20 active:scale-95"
                      >
                        <Settings2 size={18} />
                      </button>
                    </>
                  ) : undefined
                }
                handRaised={iRaisedHand}
                onToggleHand={() => (iRaisedHand ? realtime.lowerHand() : realtime.raiseHand())}
                onLeave={() => setConfirmLeaveOpen(true)}
                media={
                  isAgoraMeeting && agoraCall.phase === 'connected'
                    ? {
                        micMuted: agoraCall.micMuted,
                        cameraOn: agoraCall.cameraOn,
                        screenSharing: agoraCall.screenSharing,
                        onToggleMic: () => void agoraCall.toggleMic(),
                        onToggleCamera: () => void agoraCall.toggleCamera(),
                        onToggleScreenShare: () => void handleAgoraScreenShare(),
                      }
                    : embeddedCall.phase === 'connected'
                    ? {
                        micMuted: embeddedCall.micMuted,
                        cameraOn: embeddedCall.cameraOn,
                        screenSharing: embeddedCall.screenSharing,
                        onToggleMic: () => void embeddedCall.toggleMic(),
                        onToggleCamera: () => void embeddedCall.toggleCamera(),
                        onToggleScreenShare: () => void embeddedCall.toggleScreenShare(),
                      }
                    : undefined
                }
              />
            </div>
          </div>
        </>
      )}

      {deviceSettingsOpen && (
        <div className="fixed inset-0 z-50 flex bg-black/60 backdrop-blur-sm">
          <DeviceCheck
            mode="settings"
            onDone={(prefs) => void applyDeviceSettings(prefs)}
            onCancel={() => setDeviceSettingsOpen(false)}
          />
        </div>
      )}

      <ConfirmDialog
        open={confirmLeaveOpen}
        onClose={() => setConfirmLeaveOpen(false)}
        onConfirm={handleConfirmLeave}
        title="مغادرة الاجتماع"
        description="هل أنت متأكد أنك تريد مغادرة الاجتماع؟"
        confirmLabel="مغادرة"
        variant="danger"
      />
    </motion.div>,
    document.body,
  )
}
