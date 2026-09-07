import {
  Circle,
  Hand,
  LogOut,
  Maximize,
  Mic,
  MicOff,
  MonitorUp,
  MoreHorizontal,
  ScreenShareOff,
  Video,
  VideoOff,
} from 'lucide-react'
import { cn } from '@/lib/utils'

function ControlButton({
  onClick,
  active,
  danger,
  label,
  children,
}: {
  onClick: () => void
  active?: boolean
  danger?: boolean
  label: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={cn(
        'flex h-11 w-11 items-center justify-center rounded-full transition-all active:scale-95',
        danger
          ? 'bg-danger text-white hover:brightness-95'
          : active
            ? 'bg-white/10 text-white hover:bg-white/20'
            : 'bg-white/[0.06] text-white/40 hover:bg-white/10',
      )}
    >
      {children}
    </button>
  )
}

/**
 * شريط التحكم السفلي — تعديل لاما 2026-09-06 لمطابقة ترتيب الواجهة
 * المرجعية بالضبط (يمين→يسار RTL): رفع اليد (بفاصل)، الميكروفون،
 * الكاميرا، [مغادرة — بارز أحمر بالمنتصف]، مشاركة الشاشة، تسجيل، المزيد،
 * ملء الشاشة. "تسجيل" هنا يتحكم بنفس حالة التسجيل الحقيقية المستخدَمة
 * بلوحة الذكاء الاصطناعي وبشارة الفيديو (useAudioRecorder بمستوى
 * MeetingRoom.tsx) — وليس مجرد أيقونة شكلية. "المزيد" يفتح لوحة
 * "التسجيل + الذكاء الاصطناعي" الجانبية (بديل مكان تبويبها القديم).
 */
export function MeetingControls({
  micEnabled,
  camEnabled,
  sharingScreen,
  handRaised,
  isRecording,
  onToggleMic,
  onToggleCamera,
  onToggleScreenShare,
  onToggleHand,
  onToggleRecording,
  onOpenMore,
  onLeave,
}: {
  micEnabled: boolean
  camEnabled: boolean
  sharingScreen: boolean
  handRaised: boolean
  isRecording: boolean
  onToggleMic: () => void
  onToggleCamera: () => void
  onToggleScreenShare: () => void
  onToggleHand: () => void
  onToggleRecording: () => void
  onOpenMore: () => void
  onLeave: () => void
}) {
  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {})
    } else {
      document.exitFullscreen().catch(() => {})
    }
  }

  return (
    <div className="flex h-20 shrink-0 items-center justify-center gap-2.5 border-t border-white/10 bg-[#161c2c] px-4">
      <ControlButton onClick={onToggleHand} active={handRaised} label={handRaised ? 'إنزال اليد' : 'رفع اليد'}>
        <Hand size={18} />
      </ControlButton>

      <span className="mx-1 h-7 w-px bg-white/10" />

      <ControlButton onClick={onToggleMic} active={micEnabled} label={micEnabled ? 'كتم الصوت' : 'تشغيل الصوت'}>
        {micEnabled ? <Mic size={18} /> : <MicOff size={18} />}
      </ControlButton>
      <ControlButton onClick={onToggleCamera} active={camEnabled} label={camEnabled ? 'إيقاف الكاميرا' : 'تشغيل الكاميرا'}>
        {camEnabled ? <Video size={18} /> : <VideoOff size={18} />}
      </ControlButton>

      <button
        type="button"
        onClick={onLeave}
        aria-label="مغادرة الاجتماع"
        title="مغادرة الاجتماع"
        className="flex h-11 items-center gap-2 rounded-full bg-danger px-5 text-sm font-semibold text-white transition-all hover:brightness-95 active:scale-95"
      >
        <LogOut size={17} />
        مغادرة
      </button>

      <ControlButton
        onClick={onToggleScreenShare}
        active={sharingScreen}
        label={sharingScreen ? 'إيقاف مشاركة الشاشة' : 'مشاركة الشاشة'}
      >
        {sharingScreen ? <ScreenShareOff size={18} /> : <MonitorUp size={18} />}
      </ControlButton>
      <ControlButton onClick={onToggleRecording} active={isRecording} danger={isRecording} label={isRecording ? 'إيقاف التسجيل' : 'بدء التسجيل'}>
        <Circle size={18} className={isRecording ? 'fill-current' : undefined} />
      </ControlButton>
      <ControlButton onClick={onOpenMore} label="المزيد">
        <MoreHorizontal size={18} />
      </ControlButton>
      <ControlButton onClick={toggleFullscreen} label="ملء الشاشة">
        <Maximize size={18} />
      </ControlButton>
    </div>
  )
}
