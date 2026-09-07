import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion } from 'framer-motion'
import { ClipboardList, Loader2, TimerOff } from 'lucide-react'
import { useMeetingDetail } from '@/hooks/useMeetings'
import { useAuthStore } from '@/store/authStore'
import { useMeetingRealtime } from '@/hooks/useMeetingRealtime'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { useAgoraConnection } from './room/useAgoraConnection'
import { useAudioRecorder } from './room/useAudioRecorder'
import { MeetingRoomAppRail } from './room/MeetingRoomAppRail'
import { MeetingRoomSidebar, type RoomPanelKey } from './room/MeetingRoomSidebar'
import { MeetingRoomHeader } from './room/MeetingRoomHeader'
import { MeetingStage } from './room/MeetingStage'
import { MeetingControls } from './room/MeetingControls'
import { ParticipantsPanel } from './room/panels/ParticipantsPanel'
import { AgendaPanel } from './room/panels/AgendaPanel'
import { DecisionsPanel } from './room/panels/DecisionsPanel'
import { AttachmentsPanel } from './room/panels/AttachmentsPanel'
import { ChatPanel } from './room/panels/ChatPanel'
import { ActivityPanel } from './room/panels/ActivityPanel'
import { RecordingPanel } from './room/panels/RecordingPanel'
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
 * غرفة الاجتماع — إعادة تصميم 2026-09-06 المسائية لمطابقة الواجهة
 * المرجعية الثانية التي رسمتها لاما بالضبط (بعد الإصدار الأول الذي لم
 * يعجبها): شريطان منفصلان يمين الشاشة — شريط عام داكن بشعار الشركة
 * وتنقّل عام (MeetingRoomAppRail.tsx)، ثم لوحة ديناميكية بيضاء (340px)
 * تبويباتها صف أفقي صغير أعلاها (MeetingRoomSidebar.tsx، لم يعد شريطًا
 * جانبيًا) — المحادثة تُفتح من الشريط العام، ولوحة التسجيل+الذكاء
 * الاصطناعي من زر "المزيد" بشريط التحكم السفلي، لا من تبويب بلوحة
 * المشاركين. التسجيل الصوتي رُفع لهذا المستوى (useAudioRecorder) ليكون
 * مصدرًا حيًا واحدًا لثلاث واجهات: زر التسجيل بالتحكم السفلي، شارة
 * "جاري التسجيل" أعلى الفيديو، ولوحة الذكاء الاصطناعي.
 *
 * الواجهة الخارجية (props) لم تتغيّر عمدًا — MeetingDetailPage.tsx ما
 * زال يستدعيها بنفس الشكل: <MeetingRoom meetingId meetingTitle onClose />.
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
  // Polling أثناء بقاء الغرفة مفتوحة فقط (راجعي useMeetingDetail) — يكشف
  // انتهاء وقت الاجتماع (status → finished) بدون حاجة لإعادة فتح الصفحة.
  const meetingQuery = useMeetingDetail(meetingId, { refetchIntervalMs: MEETING_STATUS_POLL_MS })
  const agora = useAgoraConnection(meetingId)
  const realtime = useMeetingRealtime(meetingId)
  const recorder = useAudioRecorder(meetingId)

  const [activePanel, setActivePanel] = useState<RoomPanelKey>('participants')
  const [confirmLeaveOpen, setConfirmLeaveOpen] = useState(false)
  const [leaving, setLeaving] = useState(false)

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

  const participantNames = useMemo(() => {
    const map = new Map<string, string>()
    meetingQuery.data?.participants.forEach((p) => {
      map.set(p.user_id, `${p.first_name} ${p.last_name}`)
    })
    return map
  }, [meetingQuery.data?.participants])

  function handleStartDiscussing(item: MeetingAgendaItem) {
    realtime.announceDiscussing(item.agenda_item_id, item.title)
  }

  async function handleConfirmLeave() {
    setLeaving(true)
    if (recorder.isRecording) recorder.stop()
    await agora.leave()
    setLeaving(false)
    setConfirmLeaveOpen(false)
    onClose()
  }

  async function handleToggleRecording() {
    if (recorder.isRecording) {
      recorder.stop()
    } else {
      await recorder.start()
    }
  }

  const meeting = meetingQuery.data

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
    const timeout = setTimeout(() => {
      setLeaving(true)
      if (recorder.isRecording) recorder.stop()
      agora
        .leave()
        .catch(() => {})
        .finally(() => {
          setLeaving(false)
          onClose()
        })
    }, AUTO_LEAVE_GRACE_MS)
    return () => clearTimeout(timeout)
    // عمدًا: agora/recorder/onClose لا تدخل بالـdeps — agora كائن جديد كل
    // render (سيُعيد تشغيل المؤقّت باستمرار لو أُدرِج)، والاعتماد الفعلي
    // الوحيد للتشغيل هو meetingEnded نفسه (الحارس أعلاه autoLeaveTriggeredRef
    // يمنع أي تكرار على أي حال، بنفس نمط useAgoraConnection.ts).
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
                  />
                )}
                {activePanel === 'decisions' && (
                  <DecisionsPanel
                    meetingId={meetingId}
                    committeeId={meeting.committee_id}
                    currentUserId={currentUser?.user_id ?? ''}
                  />
                )}
                {activePanel === 'attachments' && <AttachmentsPanel meetingId={meetingId} />}
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
                {activePanel === 'ai' && (
                  <RecordingPanel meetingId={meetingId} recorder={recorder} />
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

              {agora.phase === 'connecting' && (
                <div className="flex flex-1 flex-col items-center justify-center gap-3 text-white/60">
                  <Loader2 size={26} className="animate-spin" />
                  <p className="text-sm">جاري الاتصال بالاجتماع...</p>
                </div>
              )}
              {agora.phase === 'error' && (
                <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
                  <p className="max-w-sm text-sm text-danger">
                    {agora.errorMessage ?? 'تعذّر الاتصال بالاجتماع.'}
                  </p>
                </div>
              )}
              {agora.phase === 'connected' && (
                <MeetingStage
                  localName={currentUser ? `${currentUser.first_name} ${currentUser.last_name}` : 'أنتِ'}
                  localDisplayTrack={agora.localDisplayTrack}
                  micEnabled={agora.micEnabled}
                  camEnabled={agora.camEnabled}
                  sharingScreen={agora.sharingScreen}
                  localAudioLevel={agora.localAudioLevel}
                  remoteParticipants={agora.remoteParticipants}
                  participantNames={participantNames}
                  raisedHandUserIds={raisedHandUserIds}
                  localUserId={currentUser?.user_id ?? ''}
                  isRecording={recorder.isRecording}
                  recordingElapsedSeconds={recorder.elapsedSeconds}
                  onStopRecording={recorder.stop}
                />
              )}

              {agora.phase === 'connected' && (
                <MeetingControls
                  micEnabled={agora.micEnabled}
                  camEnabled={agora.camEnabled}
                  sharingScreen={agora.sharingScreen}
                  handRaised={iRaisedHand}
                  isRecording={recorder.isRecording}
                  onToggleMic={agora.toggleMic}
                  onToggleCamera={agora.toggleCamera}
                  onToggleScreenShare={agora.toggleScreenShare}
                  onToggleHand={() => (iRaisedHand ? realtime.lowerHand() : realtime.raiseHand())}
                  onToggleRecording={handleToggleRecording}
                  onOpenMore={() => handleSelectPanel('ai')}
                  onLeave={() => setConfirmLeaveOpen(true)}
                />
              )}
            </div>
          </div>
        </>
      )}

      <ConfirmDialog
        open={confirmLeaveOpen}
        onClose={() => setConfirmLeaveOpen(false)}
        onConfirm={handleConfirmLeave}
        title="مغادرة الاجتماع"
        description="هل أنتِ متأكدة أنك تريدين مغادرة الاجتماع؟"
        confirmLabel="مغادرة"
        variant="danger"
        loading={leaving}
      />
    </motion.div>,
    document.body,
  )
}
