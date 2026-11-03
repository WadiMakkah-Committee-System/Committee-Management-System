import { useCallback, useEffect, useRef, useState } from 'react'
import { Mic, MicOff, Video, VideoOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getDevicePrefs, saveDevicePrefs, type DevicePrefs } from './devicePrefs'

interface DeviceLists {
  cameras: MediaDeviceInfo[]
  microphones: MediaDeviceInfo[]
  speakers: MediaDeviceInfo[]
}

/**
 * فحص الكاميرا والمايك (قرار لاما 2026-11-03):
 * - قبل الدخول: يطلع أول مرة فقط على الجهاز (mode="prejoin") — معاينة الكاميرا،
 *   مؤشر صوت المايك، اختيار الأجهزة، والكاميرا/المايك شغالين ولا لا ⇒ "دخول الآن".
 * - داخل الاجتماع: نفس الشاشة كنافذة "إعدادات الأجهزة" (mode="settings").
 *
 * يستخدم واجهات المتصفح مباشرة (getUserMedia/enumerateDevices) — ما يحتاج
 * مكتبة الاجتماع، فيشتغل قبل الاتصال. الإعدادات تنحفظ بالجهاز (devicePrefs).
 *
 * المدخلات: mode، onDone(prefs) بعد الحفظ، onCancel (للإعدادات فقط).
 */
export function DeviceCheck({
  mode,
  onDone,
  onCancel,
}: {
  mode: 'prejoin' | 'settings'
  onDone: (prefs: DevicePrefs) => void
  onCancel?: () => void
}) {
  const [prefs, setPrefs] = useState<DevicePrefs>(() => getDevicePrefs())
  const [devices, setDevices] = useState<DeviceLists>({ cameras: [], microphones: [], speakers: [] })
  const [level, setLevel] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const rafRef = useRef<number | null>(null)

  const stopPreview = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    void audioCtxRef.current?.close().catch(() => {})
    audioCtxRef.current = null
  }, [])

  // معاينة حيّة حسب الأجهزة المختارة: كاميرا + مقياس صوت المايك.
  useEffect(() => {
    let cancelled = false
    async function startPreview() {
      stopPreview()
      setError(null)
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: prefs.cameraOn ? (prefs.cameraId ? { deviceId: { exact: prefs.cameraId } } : true) : false,
          audio: prefs.microphoneId ? { deviceId: { exact: prefs.microphoneId } } : true,
        })
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        streamRef.current = stream
        if (videoRef.current) videoRef.current.srcObject = prefs.cameraOn ? stream : null
        const all = await navigator.mediaDevices.enumerateDevices()
        setDevices({
          cameras: all.filter((d) => d.kind === 'videoinput'),
          microphones: all.filter((d) => d.kind === 'audioinput'),
          speakers: all.filter((d) => d.kind === 'audiooutput'),
        })
        const ctx = new AudioContext()
        audioCtxRef.current = ctx
        const analyser = ctx.createAnalyser()
        analyser.fftSize = 256
        ctx.createMediaStreamSource(stream).connect(analyser)
        const data = new Uint8Array(analyser.frequencyBinCount)
        const tick = () => {
          analyser.getByteFrequencyData(data)
          const avg = data.reduce((a, b) => a + b, 0) / data.length
          setLevel(Math.min(1, avg / 60))
          rafRef.current = requestAnimationFrame(tick)
        }
        tick()
      } catch {
        if (!cancelled) setError('المتصفح ما سمح بالكاميرا أو المايك — اسمح لها من أيقونة القفل بشريط العنوان.')
      }
    }
    void startPreview()
    return () => {
      cancelled = true
      stopPreview()
    }
  }, [prefs.cameraId, prefs.microphoneId, prefs.cameraOn, stopPreview])

  function finish() {
    stopPreview()
    saveDevicePrefs(prefs)
    onDone(prefs)
  }

  const select = (label: string, list: MediaDeviceInfo[], value: string | null, key: keyof DevicePrefs) =>
    list.length > 0 && (
      <label className="flex flex-col gap-1 text-[12px] text-white/70">
        {label}
        <select
          value={value ?? list[0]?.deviceId ?? ''}
          onChange={(e) => setPrefs((p) => ({ ...p, [key]: e.target.value }))}
          className="h-9 rounded-sm border border-white/10 bg-[#0d1220] px-2 text-[12px] text-white focus:border-brand-primary focus:outline-none"
        >
          {list.map((d, i) => (
            <option key={d.deviceId || i} value={d.deviceId}>
              {d.label || `${label} ${i + 1}`}
            </option>
          ))}
        </select>
      </label>
    )

  return (
    <div className="flex flex-1 items-center justify-center p-4">
      <div className="flex w-full max-w-2xl flex-col gap-4 rounded-lg bg-[#1b2338] p-5 ring-1 ring-white/10">
        <div>
          <h2 className="text-lg font-semibold text-white">
            {mode === 'prejoin' ? 'جهّز الكاميرا والمايك' : 'إعدادات الأجهزة'}
          </h2>
          {mode === 'prejoin' && (
            <p className="text-xs text-white/50">مرة وحدة على هالجهاز — بعدها تدخل الاجتماعات مباشرة.</p>
          )}
        </div>

        <div className="grid gap-4 sm:grid-cols-[1.4fr_1fr]">
          <div className="relative aspect-video overflow-hidden rounded-md bg-black">
            {prefs.cameraOn ? (
              <video ref={videoRef} autoPlay muted playsInline className="h-full w-full -scale-x-100 object-cover" />
            ) : (
              <div className="flex h-full items-center justify-center text-white/30">
                <VideoOff size={36} />
              </div>
            )}
            <div className="absolute inset-x-3 bottom-3 flex items-center gap-2">
              <Mic size={14} className="text-white/80" />
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/15">
                <div className="h-full rounded-full bg-status-success-main transition-[width] duration-75" style={{ width: `${level * 100}%` }} />
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-3">
            {select('الكاميرا', devices.cameras, prefs.cameraId, 'cameraId')}
            {select('المايك', devices.microphones, prefs.microphoneId, 'microphoneId')}
            {select('السماعة', devices.speakers, prefs.speakerId, 'speakerId')}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPrefs((p) => ({ ...p, micOn: !p.micOn }))}
                className={cn(
                  'flex flex-1 items-center justify-center gap-1.5 rounded-full py-2 text-[12px] font-medium',
                  prefs.micOn ? 'bg-white/10 text-white' : 'bg-danger text-white',
                )}
              >
                {prefs.micOn ? <Mic size={14} /> : <MicOff size={14} />}
                {prefs.micOn ? 'المايك شغال' : 'المايك مكتوم'}
              </button>
              <button
                type="button"
                onClick={() => setPrefs((p) => ({ ...p, cameraOn: !p.cameraOn }))}
                className={cn(
                  'flex flex-1 items-center justify-center gap-1.5 rounded-full py-2 text-[12px] font-medium',
                  prefs.cameraOn ? 'bg-white/10 text-white' : 'bg-danger text-white',
                )}
              >
                {prefs.cameraOn ? <Video size={14} /> : <VideoOff size={14} />}
                {prefs.cameraOn ? 'الكاميرا شغالة' : 'الكاميرا مطفية'}
              </button>
            </div>
          </div>
        </div>

        {error && <p className="text-[12px] text-danger">{error}</p>}

        <div className="flex justify-end gap-2">
          {onCancel && (
            <button
              type="button"
              onClick={() => {
                stopPreview()
                onCancel()
              }}
              className="h-10 rounded-full px-5 text-sm text-white/70 hover:text-white"
            >
              إلغاء
            </button>
          )}
          <button
            type="button"
            onClick={finish}
            className="h-10 rounded-full bg-brand-primary px-6 text-sm font-semibold text-white transition-all hover:brightness-110"
          >
            {mode === 'prejoin' ? 'دخول الآن' : 'حفظ'}
          </button>
        </div>
      </div>
    </div>
  )
}
