import { useCallback, useEffect, useRef, useState } from 'react'
import { useUploadMeetingRecording } from '@/hooks/useMeetings'

/**
 * تسجيل صوتي حقيقي بالمتصفح (MediaRecorder API) — مُستخرَج من
 * RecordingPanel.tsx (تعديل لاما 2026-09-06 لمطابقة واجهة الاجتماع
 * المرجعية: التسجيل الآن يُبدأ/يُوقَف من شريط التحكم السفلي (زر
 * "تسجيل" بـMeetingControls.tsx) بنفس قدر لوحة "الذكاء الاصطناعي"
 * (RecordingPanel.tsx)، وأيضًا يظهر كشارة حية أعلى الفيديو الرئيسي
 * (MeetingStage.tsx) — فلا بد أن يكون مصدر حالة واحدًا مرفوعًا لمستوى
 * MeetingRoom.tsx، بدل حالة محلية داخل RecordingPanel وحدها كما كان
 * سابقًا؛ نسخة واحدة فقط من MediaRecorder/getUserMedia يمكن أن تعمل على
 * أي حال، فالرفع لمستوى أعلى ضروري وظيفيًا لا شكليًا فقط.
 */
export function useAudioRecorder(meetingId: string) {
  const uploadMutation = useUploadMeetingRecording()

  const [isRecording, setIsRecording] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [micError, setMicError] = useState<string | null>(null)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // مرجع (لا State) لقراءة أحدث "عدد الثواني" داخل recorder.onstop (closure
  // من لحظة start) بلا حاجة لإعادة بناء onstop نفسه كل ثانية.
  const elapsedSecondsRef = useRef(0)

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      streamRef.current?.getTracks().forEach((t) => t.stop())
    }
  }, [])

  function pickSupportedMimeType(): string {
    const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
    for (const type of candidates) {
      if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(type)) return type
    }
    return ''
  }

  const start = useCallback(async () => {
    setMicError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      chunksRef.current = []
      const mimeType = pickSupportedMimeType()
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data)
      }
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: mimeType || 'audio/webm' })
        const file = new File([blob], `meeting-${meetingId}.webm`, { type: blob.type })
        await uploadMutation.mutateAsync({ meetingId, file, durationSeconds: elapsedSecondsRef.current })
      }
      mediaRecorderRef.current = recorder
      recorder.start()
      elapsedSecondsRef.current = 0
      setIsRecording(true)
      setElapsedSeconds(0)
      timerRef.current = setInterval(() => {
        elapsedSecondsRef.current += 1
        setElapsedSeconds(elapsedSecondsRef.current)
      }, 1000)
      return true
    } catch {
      setMicError('تعذّر الوصول للميكروفون — تحققي من صلاحيات المتصفح')
      return false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetingId])

  const stop = useCallback(() => {
    mediaRecorderRef.current?.stop()
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    setIsRecording(false)
    if (timerRef.current) clearInterval(timerRef.current)
  }, [])

  return {
    isRecording,
    elapsedSeconds,
    micError,
    isUploading: uploadMutation.isPending,
    uploadError: uploadMutation.error,
    start,
    stop,
  }
}
