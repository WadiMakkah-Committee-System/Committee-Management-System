import { useEffect, useRef, useState } from 'react'

/** أنواع مختصرة لواجهة التعرف على الكلام بالمتصفح (مو ضمن أنواع TypeScript الافتراضية). */
interface SpeechRecognitionAlternativeLike {
  transcript: string
}
interface SpeechRecognitionResultLike {
  isFinal: boolean
  0: SpeechRecognitionAlternativeLike
}
interface SpeechRecognitionEventLike {
  resultIndex: number
  results: ArrayLike<SpeechRecognitionResultLike>
}
interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: SpeechRecognitionCtor; webkitSpeechRecognition?: SpeechRecognitionCtor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

/** جملة مكتملة من كلامي — تنحفظ (المسودة، "وش فاتني؟"، الإحصائيات). */
export interface OwnFinalCaption {
  clientKey: string
  text: string
  spokenAt: string
  language: string
}

/** سطر من كلامي للعرض عندي (الجملة اللي لسا تنقال باهتة). */
export interface OwnCaptionLine {
  key: string
  text: string
  final: boolean
}

const INTERIM_THROTTLE_MS = 350
const RESTART_DELAY_MS = 300

/**
 * الهدف (الترجمة النصية المجانية — قرار لاما 2026-11-04 "أي خدمة مجانية"):
 * كل عضو يحوّل **كلامه هو** لنص بمتصفحه (Web Speech API — مدمجة بالمتصفح،
 * مجانية)، ويبثه للكل لحظيًا ويحفظ الجمل المكتملة. المتحدث معروف 100% لأن كل
 * جهاز يسمع صاحبه فقط.
 *
 * حدود موثّقة (قيلت لاما قبل البدء):
 * - تشتغل على Chrome وEdge (وSafari جزئيًا)؛ Firefox ما يدعمها ⇒ error واضح.
 * - Chrome يرسل الصوت لخدمة Google لتحويله لنص (نقطة خصوصية).
 * - تستخدم مايك الجهاز الافتراضي (مو بالضرورة المختار بإعدادات الاجتماع).
 *
 * قواعد:
 * - ما تسمع وأنا كاتم المايك (muted) — خصوصية: الكتم يوقف التعرف فورًا.
 * - Chrome يوقف التعرف بعد صمت/دقيقة تقريبًا ⇒ نعيد تشغيله تلقائيًا ما دامت مفعّلة.
 *
 * المدخلات: enabled (الرئيس شغّلها + أنا داخل الاجتماع)، muted، language،
 * onLine (بث سطر للكل)، onFinal (جملة مكتملة للحفظ).
 */
export function useSpeechCaptions(options: {
  enabled: boolean
  muted: boolean
  language: string
  onLine: (key: string, text: string, final: boolean) => void
  onFinal: (caption: OwnFinalCaption) => void
}) {
  const [ownLine, setOwnLine] = useState<OwnCaptionLine | null>(null)
  const [error, setError] = useState<string | null>(null)
  const optionsRef = useRef(options)
  optionsRef.current = options
  const supported = typeof window !== 'undefined' && getRecognitionCtor() !== null

  const active = options.enabled && !options.muted && supported

  useEffect(() => {
    if (!active) return
    const Ctor = getRecognitionCtor()
    if (!Ctor) return
    let stopped = false
    let recognition: SpeechRecognitionLike | null = null
    let lastInterimAt = 0
    // مفتاح الجملة الحالية: يثبت لين تكتمل، عشان سطرها يتحدث عند الكل بدل ما يتكرر.
    let sentenceKey = `${Date.now()}`
    let sentenceStartedAt = new Date().toISOString()

    const lang = optionsRef.current.language.toLowerCase().startsWith('ar') ? 'ar-SA' : optionsRef.current.language

    const begin = () => {
      if (stopped) return
      recognition = new Ctor()
      recognition.lang = lang
      recognition.continuous = true
      recognition.interimResults = true
      recognition.onresult = (event) => {
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const result = event.results[i]
          const text = result[0]?.transcript?.trim() ?? ''
          if (!text) continue
          if (result.isFinal) {
            optionsRef.current.onLine(sentenceKey, text, true)
            optionsRef.current.onFinal({ clientKey: sentenceKey, text, spokenAt: sentenceStartedAt, language: lang })
            setOwnLine({ key: sentenceKey, text, final: true })
            sentenceKey = `${Date.now()}-${i}`
            sentenceStartedAt = new Date().toISOString()
          } else {
            setOwnLine({ key: sentenceKey, text, final: false })
            const now = Date.now()
            if (now - lastInterimAt > INTERIM_THROTTLE_MS) {
              lastInterimAt = now
              optionsRef.current.onLine(sentenceKey, text, false)
            }
          }
        }
      }
      recognition.onerror = (event) => {
        if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
          stopped = true
          setError('المتصفح منع الترجمة النصية من استخدام المايك — اسمح بالإذن وأعد المحاولة.')
        } else if (event.error === 'language-not-supported') {
          stopped = true
          setError('المتصفح ما يدعم التعرف على الكلام العربي.')
        }
        // no-speech / network / aborted ⇒ onend يعيد التشغيل.
      }
      recognition.onend = () => {
        if (!stopped) setTimeout(begin, RESTART_DELAY_MS)
      }
      try {
        recognition.start()
        setError(null)
      } catch {
        setTimeout(begin, RESTART_DELAY_MS * 3)
      }
    }

    begin()
    return () => {
      stopped = true
      try {
        recognition?.abort()
      } catch {
        /* تجاهل */
      }
    }
  }, [active])

  // تُشتق وقت العرض (بدل setState داخل effect): مطفية ⇒ لا سطر ولا خطأ.
  const unsupportedError = supported ? null : 'الترجمة النصية تحتاج متصفح Chrome أو Edge — متصفحك الحالي ما يدعمها.'
  return {
    ownLine: active ? ownLine : null,
    error: options.enabled ? (unsupportedError ?? error) : null,
    supported,
  }
}
