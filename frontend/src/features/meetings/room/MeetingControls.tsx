import { Hand, LogOut, Maximize, Mic, MicOff, MonitorUp, ScreenShareOff, Video, VideoOff } from 'lucide-react'
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
 * شريط التحكم السفلي لغرفة الاجتماع — مبسّط 2026-11-02 بعد الانتقال لـ
 * Microsoft Teams: الميكروفون/الكاميرا/مشاركة الشاشة/التسجيل كلها داخل تيمز
 * نفسه الآن، فيبقى هنا ما يخص الجلسة بنظامنا فقط: رفع اليد (يظهر للرئيس
 * بلوحة المشاركين لحظيًا)، مغادرة الغرفة، وملء الشاشة.
 *
 * المدخلات: handRaised (حالة يدي الحالية)، onToggleHand، onLeave، و media
 * (اختياري — تجربة الانضمام المدمج عبر Azure Communication Services): عند
 * تمريره تظهر أزرار المايك والكاميرا ومشاركة الشاشة للاتصال الجاري داخل المنصة.
 */
export function MeetingControls({
  handRaised,
  onToggleHand,
  onLeave,
  media,
}: {
  handRaised: boolean
  onToggleHand: () => void
  onLeave: () => void
  media?: {
    micMuted: boolean
    cameraOn: boolean
    screenSharing: boolean
    onToggleMic: () => void
    onToggleCamera: () => void
    onToggleScreenShare: () => void
  }
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

      {media && (
        <>
          <span className="mx-1 h-7 w-px bg-white/10" />
          <ControlButton
            onClick={media.onToggleMic}
            active={!media.micMuted}
            label={media.micMuted ? 'تشغيل الصوت' : 'كتم الصوت'}
          >
            {media.micMuted ? <MicOff size={18} /> : <Mic size={18} />}
          </ControlButton>
          <ControlButton
            onClick={media.onToggleCamera}
            active={media.cameraOn}
            label={media.cameraOn ? 'إيقاف الكاميرا' : 'تشغيل الكاميرا'}
          >
            {media.cameraOn ? <Video size={18} /> : <VideoOff size={18} />}
          </ControlButton>
        </>
      )}

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

      {media && (
        <ControlButton
          onClick={media.onToggleScreenShare}
          active={media.screenSharing}
          label={media.screenSharing ? 'إيقاف مشاركة الشاشة' : 'مشاركة الشاشة'}
        >
          {media.screenSharing ? <ScreenShareOff size={18} /> : <MonitorUp size={18} />}
        </ControlButton>
      )}
      <ControlButton onClick={toggleFullscreen} label="ملء الشاشة">
        <Maximize size={18} />
      </ControlButton>
    </div>
  )
}
