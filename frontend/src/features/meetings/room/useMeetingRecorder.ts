import { useCallback, useEffect, useRef, useState } from 'react'
import { startRecordingSession, stopRecordingSession, uploadRecordingChunk, type RecordingState } from '@/api/meetings'
import { extractErrorMessage } from '@/lib/utils'
import type { IMicrophoneAudioTrack, IRemoteAudioTrack } from 'agora-rtc-sdk-ng'
import type { AudioSources } from './useAgoraCall'

/** طول القطعة: كل 30 ثانية تنرفع قطعة ⇒ أقصى خسارة لو انقفلت الصفحة فجأة. */
const CHUNK_MS = 30_000
/** جودة صوت الكلام (opus): واضحة ومحجمها صغير (~15 ميقا للساعة). */
const AUDIO_BITS_PER_SECOND = 32_000
const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4']
const RETRY_DELAYS_MS = [1_000, 2_000, 5_000, 10_000, 20_000]

export type RecorderStatus = 'idle' | 'starting' | 'recording' | 'stopping'

function pickMimeType(): string | null {
  if (typeof MediaRecorder === 'undefined') return null
  return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m)) ?? null
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/** أي مسار Agora صوتي يعطي قطع الصوت المفكوكة (مايكي أو عضو). */
type FrameTrack = Pick<IMicrophoneAudioTrack | IRemoteAudioTrack, 'setAudioFrameCallback'>

/** حجم القطعة من Agora (عينات): 2048 ≈ 43ms عند 48kHz. */
const FRAME_SIZE = 2048
/** هامش تأخير بسيط يمتص تذبذب وصول القطع (بدون تقطيع بالصوت). */
const JITTER_SECONDS = 0.15
/** أقل مستوى نعتبره "صوت" (مو صمت تام). */
const SOUND_THRESHOLD = 0.01
/** تنبيه الرئيس لو التسجيل ما التقط أي صوت هالمدة. */
const SILENCE_WARNING_MS = 15_000

/**
 * الهدف (الرجوع لـAgora — قرار لاما 2026-11-04):
 * تسجيل صوت **كل أعضاء الاجتماع** من جهاز رئيس اللجنة، صوت فقط، بزر.
 *
 * إصلاح 2026-11-04 (بلاغ لاما — "سجّلنا 10 دقايق والتسجيل صامت"): النسخة الأولى
 * كانت تربط MediaStreamTrack الخام بـWeb Audio، وكروم يطلّع صمت لمسارات WebRTC
 * بهالطريقة في حالات معروفة. الحين ناخذ الصوت **المفكوك من Agora نفسها**
 * (setAudioFrameCallback — نفس الصوت اللي يطلع بالسماعة) لكل عضو ولمايك الرئيس.
 *
 * كيف (أدوات مدمجة بالمتصفح — بدون مكتبات إضافية):
 * 1) كل مصدر (مايك الرئيس + كل عضو) يعطينا قطع صوت (AudioBuffer) كل ~40ms.
 * 2) كل قطعة تنجدول بالترتيب بمسار المصدر داخل AudioContext واحد، وكل المصادر
 *    تصب بنفس الوجهة فتنخلط (مثل عدة InputStream تندمج في OutputStream واحد بـJava).
 * 3) MediaRecorder يسجّل الوجهة المخلوطة ويطلّع قطعة كل 30 ثانية ⇒ ترتفع بالترتيب
 *    مع إعادة محاولة لو النت تقطّع (القطع تنتظر بالذاكرة لين ترتفع).
 * 4) عضو يدخل/يطلع ⇒ يُضاف/يُشال من الخلط بدون إيقاف (audioVersion من useAgoraCall).
 * 5) مؤشر مستوى الصوت (level) + تنبيه لو التسجيل صامت 15 ثانية — تنكشف المشكلة
 *    وقت الاجتماع مو بعده.
 * 6) إيقاف ⇒ آخر قطعة + انتظار رفع الكل ⇒ الخادم يدمجها ويكتب المدة الصحيحة (ffmpeg).
 *
 * لو انقفلت الصفحة فجأة: الخادم يدمج اللي وصل تلقائيًا بعد 3 دقائق (المجدوِل).
 */
export function useMeetingRecorder(
  meetingId: string,
  options: {
    getAudioSources: () => AudioSources
    audioVersion: number
    onStateChange?: (state: RecordingState) => void
  },
) {
  const [status, setStatus] = useState<RecorderStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [pendingUploads, setPendingUploads] = useState(0)

  const [level, setLevel] = useState(0)
  const [silent, setSilent] = useState(false)

  const ctxRef = useRef<AudioContext | null>(null)
  const destRef = useRef<MediaStreamAudioDestinationNode | null>(null)
  // لكل مصدر: مسار Agora + وقت تشغيل القطعة الجاية بالـAudioContext (جدولة متتالية بدون فجوات).
  const sourcesRef = useRef(new Map<string, { track: FrameTrack; nextTime: number }>())
  const peakRef = useRef(0)
  const lastSoundAtRef = useRef(0)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const sessionRef = useRef<string | null>(null)
  const seqRef = useRef(0)
  const queueRef = useRef<{ seq: number; blob: Blob }[]>([])
  const uploadingRef = useRef<Promise<void> | null>(null)
  const optionsRef = useRef(options)
  optionsRef.current = options

  /** يطابق مصادر الخلط مع مصادر الاجتماع الحالية (إضافة الجديد وشيل القديم). */
  const syncSources = useCallback(() => {
    const ctx = ctxRef.current
    const dest = destRef.current
    if (!ctx || !dest) return
    const { local, remote } = optionsRef.current.getAudioSources()
    const wanted = new Map<string, FrameTrack>(remote)
    if (local) wanted.set('__local__', local)
    for (const [key, entry] of sourcesRef.current) {
      if (wanted.get(key) !== entry.track) {
        entry.track.setAudioFrameCallback(null)
        sourcesRef.current.delete(key)
      }
    }
    for (const [key, track] of wanted) {
      if (sourcesRef.current.has(key)) continue
      const entry = { track, nextTime: 0 }
      sourcesRef.current.set(key, entry)
      track.setAudioFrameCallback((buffer: AudioBuffer) => {
        const liveCtx = ctxRef.current
        const liveDest = destRef.current
        if (!liveCtx || !liveDest) return
        // مستوى الصوت (للمؤشر وكشف الصمت) — أعلى قيمة بالقطعة.
        const data = buffer.getChannelData(0)
        let peak = 0
        for (let i = 0; i < data.length; i += 16) peak = Math.max(peak, Math.abs(data[i]))
        if (peak > peakRef.current) peakRef.current = peak
        // جدولة القطعة مباشرة بعد سابقتها لنفس المصدر؛ لو تأخرنا (فجوة) نبدأ من الآن + هامش.
        const now = liveCtx.currentTime
        if (entry.nextTime < now + 0.02) entry.nextTime = now + JITTER_SECONDS
        const node = liveCtx.createBufferSource()
        node.buffer = buffer
        node.connect(liveDest)
        node.start(entry.nextTime)
        entry.nextTime += buffer.duration
      }, FRAME_SIZE)
    }
  }, [])

  // مؤشر المستوى + كشف الصمت (كل ربع ثانية أثناء التسجيل).
  useEffect(() => {
    if (status !== 'recording') return
    lastSoundAtRef.current = Date.now()
    const id = setInterval(() => {
      const peak = peakRef.current
      peakRef.current = 0
      setLevel(Math.min(1, peak * 3))
      if (peak > SOUND_THRESHOLD) lastSoundAtRef.current = Date.now()
      setSilent(Date.now() - lastSoundAtRef.current > SILENCE_WARNING_MS)
    }, 250)
    return () => {
      clearInterval(id)
      setLevel(0)
      setSilent(false)
    }
  }, [status])

  useEffect(() => {
    if (status === 'recording') syncSources()
  }, [options.audioVersion, status, syncSources])

  /** يرفع القطع المنتظرة بالترتيب، مع إعادة محاولة (نت متقطع) لين تنجح. */
  const drainQueue = useCallback(() => {
    if (uploadingRef.current) return uploadingRef.current
    const run = async () => {
      while (queueRef.current.length > 0) {
        const sessionId = sessionRef.current
        const next = queueRef.current[0]
        if (!sessionId) return
        let attempt = 0
        for (;;) {
          try {
            await uploadRecordingChunk(meetingId, sessionId, next.seq, next.blob)
            break
          } catch (err) {
            const status = (err as { response?: { status?: number } }).response?.status
            // 409 = الجلسة انقفلت بالخادم (الرئيس بدأ من جهاز ثاني) ⇒ ما فيه فايدة من الإعادة.
            if (status === 409 || status === 403) {
              queueRef.current = []
              setError('توقف رفع التسجيل من هذا الجهاز (الجلسة انتهت بالخادم).')
              return
            }
            const delay = RETRY_DELAYS_MS[Math.min(attempt, RETRY_DELAYS_MS.length - 1)]
            attempt += 1
            await sleep(delay)
          }
        }
        queueRef.current.shift()
        setPendingUploads(queueRef.current.length)
      }
    }
    uploadingRef.current = run().finally(() => {
      uploadingRef.current = null
    })
    return uploadingRef.current
  }, [meetingId])

  const teardownAudio = useCallback(() => {
    for (const entry of sourcesRef.current.values()) entry.track.setAudioFrameCallback(null)
    sourcesRef.current.clear()
    void ctxRef.current?.close().catch(() => {})
    ctxRef.current = null
    destRef.current = null
  }, [])

  /** بدء التسجيل (زر الرئيس — لازم من ضغطة عشان المتصفح يسمح بتشغيل AudioContext). */
  const start = useCallback(async () => {
    if (status !== 'idle') return
    const mimeType = pickMimeType()
    if (!mimeType) {
      setError('المتصفح ما يدعم التسجيل — استخدم Chrome أو Edge أو Safari حديث.')
      return
    }
    setError(null)
    setStatus('starting')
    try {
      const state = await startRecordingSession(meetingId, mimeType)
      sessionRef.current = state.session_id
      seqRef.current = 0
      queueRef.current = []

      const ctx = new AudioContext()
      await ctx.resume().catch(() => {})
      ctxRef.current = ctx
      destRef.current = ctx.createMediaStreamDestination()
      syncSources()

      const recorder = new MediaRecorder(destRef.current.stream, {
        mimeType,
        audioBitsPerSecond: AUDIO_BITS_PER_SECOND,
      })
      recorder.ondataavailable = (event) => {
        if (!event.data || event.data.size === 0) return
        queueRef.current.push({ seq: seqRef.current, blob: event.data })
        seqRef.current += 1
        setPendingUploads(queueRef.current.length)
        void drainQueue()
      }
      recorder.start(CHUNK_MS)
      recorderRef.current = recorder
      setStatus('recording')
      optionsRef.current.onStateChange?.(state)
    } catch (err) {
      teardownAudio()
      sessionRef.current = null
      setError(extractErrorMessage(err))
      setStatus('idle')
    }
  }, [status, meetingId, syncSources, drainQueue, teardownAudio])

  /** إيقاف: آخر قطعة ⇒ انتظار رفع الكل ⇒ الخادم يدمج. */
  const stop = useCallback(async () => {
    const recorder = recorderRef.current
    const sessionId = sessionRef.current
    if (!recorder || !sessionId) return
    setStatus('stopping')
    await new Promise<void>((resolve) => {
      recorder.addEventListener('stop', () => resolve(), { once: true })
      try {
        recorder.stop()
      } catch {
        resolve()
      }
    })
    recorderRef.current = null
    teardownAudio()
    try {
      // الـondataavailable الأخير يسبق حدث stop — فالقطعة الأخيرة بالطابور.
      await drainQueue()
      const result = await stopRecordingSession(meetingId, sessionId)
      if (result.status !== 'finalized') setError(result.error_message || 'ما انحفظ تسجيل.')
      optionsRef.current.onStateChange?.({
        active: false,
        session_id: null,
        started_by: null,
        started_by_name: null,
        started_at: null,
      })
    } catch (err) {
      setError(`${extractErrorMessage(err)} — التسجيل محفوظ بالخادم وبيندمج تلقائيًا خلال دقائق.`)
    } finally {
      sessionRef.current = null
      setStatus('idle')
    }
  }, [meetingId, drainQueue, teardownAudio])

  // تحذير قبل إغلاق الصفحة والتسجيل شغّال (المتصفح يعرض رسالته العامة).
  useEffect(() => {
    if (status !== 'recording' && status !== 'stopping') return
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [status])

  // الغرفة انقفلت والتسجيل شغّال (انتهى وقت الاجتماع مثلًا) ⇒ إيقاف ورفع بأفضل جهد.
  const stopRef = useRef(stop)
  stopRef.current = stop
  useEffect(() => {
    return () => {
      if (recorderRef.current) void stopRef.current()
    }
  }, [])

  return { status, error, pendingUploads, level, silent, start, stop, isSupported: pickMimeType() !== null }
}
