import { useCallback, useEffect, useRef, useState } from 'react'
import { startRecordingSession, stopRecordingSession, uploadRecordingChunk, type RecordingState } from '@/api/meetings'
import { extractErrorMessage } from '@/lib/utils'
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

/**
 * الهدف (الرجوع لـAgora — قرار لاما 2026-11-04):
 * تسجيل صوت **كل أعضاء الاجتماع** من جهاز رئيس اللجنة، صوت فقط، بزر.
 *
 * كيف (أدوات مدمجة بالمتصفح — بدون مكتبات إضافية):
 * 1) AudioContext يخلط مايك الرئيس + صوت كل عضو (من Agora مباشرة — مو من
 *    السماعات، فالجودة نظيفة) في مسار واحد (MediaStreamAudioDestinationNode).
 *    كأنها InputStream كثير تندمج في OutputStream واحد (Java).
 * 2) MediaRecorder يسجّل المسار المخلوط ويطلّع قطعة كل 30 ثانية.
 * 3) كل قطعة ترتفع بالترتيب للخادم مع إعادة محاولة لو النت تقطّع
 *    (القطع تنتظر بالذاكرة لين ترتفع — ما يضيع شي).
 * 4) عضو جديد يدخل/يطلع أو يكتم ويرجع ⇒ يُضاف/يُشال من الخلط بدون إيقاف التسجيل
 *    (audioVersion من useAgoraCall).
 * 5) إيقاف ⇒ آخر قطعة + انتظار رفع الكل ⇒ الخادم يدمجها بملف واحد للمسودة.
 *
 * لو انقفلت الصفحة فجأة: الخادم يدمج اللي وصل تلقائيًا بعد 3 دقائق (المجدوِل).
 *
 * المدخلات: meetingId، getAudioSources + audioVersion (من useAgoraCall)،
 * onStateChange (تحديث مؤشر "جاري التسجيل" فورًا عندي).
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

  const ctxRef = useRef<AudioContext | null>(null)
  const destRef = useRef<MediaStreamAudioDestinationNode | null>(null)
  const sourcesRef = useRef(new Map<string, { track: MediaStreamTrack; node: MediaStreamAudioSourceNode }>())
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
    const wanted = new Map<string, MediaStreamTrack>(remote)
    if (local) wanted.set('__local__', local)
    for (const [key, entry] of sourcesRef.current) {
      if (wanted.get(key) !== entry.track) {
        entry.node.disconnect()
        sourcesRef.current.delete(key)
      }
    }
    for (const [key, track] of wanted) {
      if (sourcesRef.current.has(key) || track.readyState !== 'live') continue
      const node = ctx.createMediaStreamSource(new MediaStream([track]))
      node.connect(dest)
      sourcesRef.current.set(key, { track, node })
    }
  }, [])

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
    for (const entry of sourcesRef.current.values()) entry.node.disconnect()
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

  return { status, error, pendingUploads, start, stop, isSupported: pickMimeType() !== null }
}
