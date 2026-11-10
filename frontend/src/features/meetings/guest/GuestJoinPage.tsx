import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { CalendarClock, CheckCircle2, Clock, DoorOpen, Loader2, UserRound, XCircle } from 'lucide-react'
import * as guestsApi from '@/api/meetingGuests'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Spinner } from '@/components/ui/Spinner'
import { useAuthStore } from '@/store/authStore'
import { extractErrorMessage } from '@/lib/utils'
import type { GuestRequestStatus, PublicMeetingInvite } from '@/types'
import { DeviceCheck } from '../room/DeviceCheck'
import wadiMakkahMark from '@/assets/wadi-makkah-mark.png'

/**
 * صفحة الضيف (رابط الضيوف /join/:token — migration 0047، قرار لاما 2026-11-10):
 * الاسم ← فحص المايك والكاميرا ← انتظار القبول ← غرفة الاجتماع (/guest-meeting).
 *
 * الطلب المنتظر يُحفظ بـsessionStorage (رقمه + رمزه السري) حتى لا يضيع لو
 * حدّث الضيف الصفحة وهو ينتظر. عند القبول: جلسة الضيف تُحفظ بـauthStore مثل
 * أي مستخدم، والغرفة نفسها هي MeetingRoom العادية (الباك-إند يحصر توكنه
 * باجتماعه فقط).
 */

type Step = 'loading' | 'invalid' | 'closed' | 'member' | 'name' | 'devices' | 'waiting' | GuestRequestStatus

interface StoredRequest {
  request_id: string
  secret: string
  name: string
}

const POLL_MS = 3000

function storageKey(token: string) {
  return `guest-request:${token}`
}

function readStored(token: string): StoredRequest | null {
  try {
    const raw = sessionStorage.getItem(storageKey(token))
    return raw ? (JSON.parse(raw) as StoredRequest) : null
  } catch {
    return null
  }
}

function writeStored(token: string, value: StoredRequest | null) {
  try {
    if (value) sessionStorage.setItem(storageKey(token), JSON.stringify(value))
    else sessionStorage.removeItem(storageKey(token))
  } catch {
    // تخزين المتصفح غير متاح (وضع خاص) — الانتظار يستمر بالذاكرة فقط.
  }
}

const DATE_FMT = new Intl.DateTimeFormat('ar-SA-u-ca-gregory-nu-latn', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  hour: 'numeric',
  minute: '2-digit',
  timeZone: 'Asia/Riyadh',
})

export function GuestJoinPage() {
  const { token = '' } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const accessToken = useAuthStore((s) => s.accessToken)
  const { setTokens, setUser, setAuthMethod } = useAuthStore.getState()

  const [invite, setInvite] = useState<PublicMeetingInvite | null>(null)
  const [step, setStep] = useState<Step>('loading')
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const requestRef = useRef<StoredRequest | null>(readStored(token))

  // ضيف دخل أصلًا (نفس المتصفح) ⇒ غرفته مباشرة.
  useEffect(() => {
    if (accessToken && user?.is_guest) navigate('/guest-meeting', { replace: true })
  }, [accessToken, user, navigate])

  useEffect(() => {
    let cancelled = false
    guestsApi
      .fetchPublicInvite(token)
      .then((data) => {
        if (cancelled) return
        setInvite(data)
        if (accessToken && user && !user.is_guest) setStep('member')
        else if (!data.is_open) setStep('closed')
        else if (requestRef.current) setStep('waiting')
        else setStep('name')
      })
      .catch(() => !cancelled && setStep('invalid'))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  // متابعة الطلب أثناء الانتظار.
  useEffect(() => {
    if (step !== 'waiting' || !requestRef.current) return
    const req = requestRef.current
    let stopped = false
    async function poll() {
      try {
        const res = await guestsApi.fetchGuestRequestStatus(req.request_id, req.secret)
        if (stopped) return
        if (res.status === 'admitted' && res.access_token && res.refresh_token && res.user) {
          writeStored(token, null)
          setTokens(res.access_token, res.refresh_token)
          setAuthMethod('password')
          setUser(res.user)
          navigate('/guest-meeting', { replace: true })
          return
        }
        if (res.status !== 'pending') {
          writeStored(token, null)
          setStep(res.status)
        }
      } catch (err) {
        // 404 فقط = الطلب لم يعد موجودًا ⇒ يبدأ من جديد. أي خطأ آخر (شبكة/5xx)
        // مؤقت ⇒ نكمل الاستطلاع بنفس الطلب حتى لا ينشأ طلب مكرر (مراجعة PR #116).
        const status = (err as { response?: { status?: number } }).response?.status
        if (!stopped && status === 404) {
          writeStored(token, null)
          requestRef.current = null
          setStep('name')
        }
      }
    }
    void poll()
    const id = setInterval(() => void poll(), POLL_MS)
    return () => {
      stopped = true
      clearInterval(id)
    }
  }, [step, token, navigate, setTokens, setUser, setAuthMethod])

  async function submitRequest() {
    setSubmitting(true)
    setError(null)
    try {
      const created = await guestsApi.createGuestRequest(token, name.trim())
      const stored = { request_id: created.request_id, secret: created.secret, name: name.trim() }
      writeStored(token, stored)
      requestRef.current = stored
      setStep('waiting')
    } catch (err) {
      setError(extractErrorMessage(err))
      setStep('name')
    } finally {
      setSubmitting(false)
    }
  }

  async function cancelRequest() {
    const req = requestRef.current
    writeStored(token, null)
    requestRef.current = null
    setStep('cancelled')
    if (req) await guestsApi.cancelGuestRequest(req.request_id, req.secret).catch(() => undefined)
  }

  if (step === 'devices') {
    return <DeviceCheck mode="prejoin" onDone={() => void submitRequest()} />
  }

  const when = invite
    ? invite.scheduled_end_at
      ? `${DATE_FMT.format(new Date(invite.scheduled_at))} – ${new Intl.DateTimeFormat('ar-SA-u-ca-gregory-nu-latn', { hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Riyadh' }).format(new Date(invite.scheduled_end_at))}`
      : DATE_FMT.format(new Date(invite.scheduled_at))
    : ''

  return (
    <div className="flex min-h-svh flex-col items-center justify-center bg-bg-app px-4 py-10">
      <div className="relative w-full max-w-md overflow-hidden rounded-lg border border-border-default bg-bg-surface p-6 shadow-xl sm:p-8">
        <div aria-hidden className="brand-stripe absolute inset-x-0 top-0 h-[3px]" />
        <div className="mb-6 flex flex-col items-center gap-3 text-center">
          <img src={wadiMakkahMark} alt="شعار وادي مكة" className="h-12 w-auto" />
          <p className="text-xs text-text-muted">نظام إدارة اللجان والاجتماعات</p>
        </div>

        {invite && step !== 'invalid' && (
          <div className="mb-6 rounded-md border border-border-default bg-bg-elevated p-4">
            <p className="text-xs text-text-muted">دعوة لحضور اجتماع</p>
            <h1 className="mt-1 text-lg font-bold text-text-primary">{invite.title}</h1>
            {invite.committee_name && <p className="mt-0.5 text-sm text-text-secondary">{invite.committee_name}</p>}
            <p className="mt-2 flex items-center gap-1.5 text-[13px] text-text-secondary">
              <CalendarClock size={14} className="shrink-0 text-brand-primary" />
              {when}
            </p>
          </div>
        )}

        {step === 'loading' && (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        )}

        {step === 'invalid' && (
          <StatusMessage
            icon={<XCircle size={26} />}
            tone="danger"
            title="رابط الدعوة غير صالح"
            text="ربما تم إيقاف هذا الرابط. اطلب رابطًا جديدًا ممن أرسل لك الدعوة."
          />
        )}

        {step === 'closed' && (
          <StatusMessage
            icon={<Clock size={26} />}
            tone="info"
            title="لا يمكن الانضمام الآن"
            text="انتهى هذا الاجتماع أو أنه اجتماع حضوري."
          />
        )}

        {step === 'member' && (
          <div className="flex flex-col gap-3">
            <StatusMessage
              icon={<UserRound size={26} />}
              tone="info"
              title="أنت مسجّل الدخول في المنصة"
              text="هذا الرابط مخصص للضيوف من خارج المنصة. ادخل الاجتماع من حسابك، أو افتح الرابط من نافذة خاصة لتجربته كضيف."
            />
            <Button onClick={() => navigate('/meetings')}>الذهاب إلى الاجتماعات</Button>
          </div>
        )}

        {step === 'name' && (
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (name.trim().length < 2) {
                setError('اكتب اسمك (حرفين على الأقل)')
                return
              }
              setError(null)
              setStep('devices')
            }}
          >
            <Input
              label="اسمك"
              placeholder="الاسم الذي سيظهر للحاضرين"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={60}
              autoFocus
              error={error ?? undefined}
            />
            <p className="text-xs text-text-muted">
              بعد كتابة اسمك ستجرّب المايك والكاميرا، ثم تنتظر حتى يقبلك أحد الحاضرين.
            </p>
            <Button type="submit" icon={<DoorOpen size={16} />} loading={submitting}>
              متابعة
            </Button>
          </form>
        )}

        {step === 'waiting' && (
          <div className="flex flex-col items-center gap-4 py-2 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-info-bg text-info">
              <Loader2 size={26} className="animate-spin" />
            </div>
            <div>
              <p className="font-semibold text-text-primary">بانتظار قبولك في الاجتماع</p>
              <p className="mt-1 text-sm text-text-secondary">
                أبلغنا الحاضرين بطلبك
                {requestRef.current?.name ? ` باسم «${requestRef.current.name}»` : ''}. ستدخل تلقائيًا بمجرد قبولك.
              </p>
            </div>
            <Button variant="ghost" onClick={() => void cancelRequest()}>
              إلغاء الطلب
            </Button>
          </div>
        )}

        {step === 'rejected' && (
          <StatusMessage
            icon={<XCircle size={26} />}
            tone="danger"
            title="لم يتم قبول طلبك"
            text="اعتذر الحاضرون عن قبول طلب الدخول. تواصل مع من أرسل لك الدعوة."
          />
        )}

        {step === 'cancelled' && (
          <div className="flex flex-col gap-3">
            <StatusMessage
              icon={<CheckCircle2 size={26} />}
              tone="info"
              title="تم إلغاء الطلب"
              text="يمكنك طلب الدخول مرة أخرى ما دام الاجتماع قائمًا."
            />
            {invite?.is_open && <Button onClick={() => setStep('name')}>طلب الدخول مرة أخرى</Button>}
          </div>
        )}
      </div>
    </div>
  )
}

function StatusMessage({
  icon,
  tone,
  title,
  text,
}: {
  icon: React.ReactNode
  tone: 'info' | 'danger'
  title: string
  text: string
}) {
  return (
    <div className="flex flex-col items-center gap-3 py-2 text-center">
      <div
        className={
          tone === 'danger'
            ? 'flex h-14 w-14 items-center justify-center rounded-full bg-danger-bg text-danger'
            : 'flex h-14 w-14 items-center justify-center rounded-full bg-info-bg text-info'
        }
      >
        {icon}
      </div>
      <p className="font-semibold text-text-primary">{title}</p>
      <p className="max-w-sm text-sm text-text-secondary">{text}</p>
    </div>
  )
}
