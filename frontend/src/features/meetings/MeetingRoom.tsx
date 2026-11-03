import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion } from 'framer-motion'
import { ClipboardList, Loader2, TimerOff } from 'lucide-react'
import { useMeetingDetail } from '@/hooks/useMeetings'
import { useCommittees } from '@/hooks/useCommittees'
import { useAuthStore } from '@/store/authStore'
import { useMeetingRealtime } from '@/hooks/useMeetingRealtime'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/components/ui/Toast'
import { MeetingRoomAppRail } from './room/MeetingRoomAppRail'
import { MeetingRoomSidebar, type RoomPanelKey } from './room/MeetingRoomSidebar'
import { MeetingRoomHeader } from './room/MeetingRoomHeader'
import { TeamsMeetingStage } from './room/TeamsMeetingStage'
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
 * غرفة الاجتماع — مساحة إدارة الجلسة بجانب Microsoft Teams (تحديث 2026-11-02:
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
  const embeddedCall = useTeamsEmbeddedCall(meetingId, {
    onAutoAdmitted: (name) => showToast(`دخل ${name} (عضو باللجنة)`, 'info'),
  })

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
  async function handleStartDiscussing(item: MeetingAgendaItem) {
    setPendingAgendaItemId(item.agenda_item_id)
    try {
      const result = await realtime.announceDiscussing(item.agenda_item_id, item.title)
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
    await embeddedCall.leave()
    onClose()
  }

  const meeting = meetingQuery.data

  // تحديث لاما 2026-11-03: زر "دخول الاجتماع" (خارج الغرفة) هو الدخول نفسه —
  // أول ما تفتح الغرفة يبدأ الاتصال تلقائيًا، بدون زر انضمام ثاني داخل الإطار.
  // مرة واحدة فقط لكل فتح للغرفة؛ إعادة المحاولة بعدها من زر "إعادة الانضمام".
  const autoStartedRef = useRef(false)
  useEffect(() => {
    if (!meeting?.has_teams_meeting || autoStartedRef.current) return
    if (meeting.status === 'finished' || meeting.status === 'recorded') return
    autoStartedRef.current = true
    void embeddedCall.start(false)
  }, [meeting?.has_teams_meeting, meeting?.status, embeddedCall])

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

            <div className="flex min-h-0 flex-1 flex-col gap-3 p-3">
              {/* تعديل لاما 2026-09-06: "بدأ مناقشة البند ما ظهر إشعار أعلى
                  الصفحة" — بث agenda.discussing كان يُسجَّل بسجل النشاط فقط
                  بلا أي عنصر ظاهر بمنطقة الفيديو الرئيسية نفسها. */}
              {realtime.discussingAgendaItem && (
                <div className="flex items-center gap-2 rounded-md border border-brand-primary/30 bg-brand-primary/10 px-3 py-2 text-[12px] font-medium text-white">
                  <ClipboardList size={14} className="shrink-0 text-brand-accent" />
                  <span className="truncate">
                    جارٍ الآن مناقشة: {realtime.discussingAgendaItem.title}
                  </span>
                </div>
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
                <TeamsMeetingStage meeting={meeting} canRecord={canRecord} />
              )}

              <MeetingControls
                handRaised={iRaisedHand}
                onToggleHand={() => (iRaisedHand ? realtime.lowerHand() : realtime.raiseHand())}
                onLeave={() => setConfirmLeaveOpen(true)}
                media={
                  embeddedCall.phase === 'connected'
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
