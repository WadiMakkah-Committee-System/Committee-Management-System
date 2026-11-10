import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { notify } from '@/components/ui/Toast'
import { ACTIVE_ROLE_CHANGED_EVENT, ACTIVE_ROLE_HEADER, isActiveRoleChangedError } from '@/lib/activeRole'
import { useAuthStore } from '@/store/authStore'
import type { TokenResponse } from '@/types'

/**
 * الهدف: طبقة اتصال مركزية بالـ API — تُرفق JWT تلقائيًا، وتُجدّد التوكن
 * عند انتهاء صلاحيته (401) عبر Refresh Token دون إزعاج المستخدم، وإذا فشل
 * التجديد نفسه (الجلسة انتهت فعلًا) تسجّل خروجه وتُعيده لصفحة الدخول.
 */

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

// ملاحظة (مراجعة لاما 2026-08-31): لا نضبط Content-Type ثابتًا هنا عمدًا —
// axios يضبطه تلقائيًا بحسب نوع البيانات المرسَلة (application/json لكائن
// JS عادي). لو ثبّتناه على application/json هنا كإعداد افتراضي للـ instance
// كله، فسيبقى ملتصقًا حتى مع طلبات FormData (رفع الملفات في
// api/documents.ts::uploadDocument) لأن axios لا يستبدل Content-Type
// موجود مسبقًا تلقائيًا — فيضيع الـ boundary الصحيح لـ multipart/form-data
// ويفشل الباك-إند بخطأ "Field required" على كل حقول الفورم (title/file)
// رغم إنها مُرسَلة فعليًا. راجعي uploadDocument للتفاصيل.
export const apiClient = axios.create({
  baseURL: API_BASE_URL,
})

apiClient.interceptors.request.use((config) => {
  const { accessToken: token, user } = useAuthStore.getState()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  // تعدد الأدوار (migration 0046): الدور الحالي اللي تعرضه هذي النافذة — لو
  // بدّله المستخدم من تبويب آخر، يرجع الباك-إند 409 بدل تنفيذ الطلب بصفة
  // غير المعروضة. يُرسَل فقط بعد تحميل بيانات المستخدم (قيمة فارغة = بلا دور).
  if (token && user) {
    config.headers[ACTIVE_ROLE_HEADER] = user.role?.role_id ?? ''
  }
  // FormData (رفع ملفات — راجعي uploadMeetingAttachment بـapi/meetings.ts):
  // axios.create({ headers: { 'Content-Type': 'application/json' } }) أعلاه
  // يضبط Content-Type ثابتًا على مستوى الـinstance نفسه (defaults.headers)،
  // وهذا لا يُزال تلقائيًا عند إرسال FormData بخلاف axios.defaults العادي —
  // فيصل multipart/form-data للباك-إند بـContent-Type: application/json
  // خطأ، فيفشل FastAPI بقراءة File()/Form() ويرجع 422 "Field required" لكل
  // حقل (لأنه لا يقرأ الـbody كـmultipart إطلاقًا). الحذف الصريح هنا يترك
  // المتصفح يضبط Content-Type الصحيح (multipart/form-data; boundary=...).
  if (typeof FormData !== 'undefined' && config.data instanceof FormData) {
    delete config.headers['Content-Type']
  }
  return config
})

let isRefreshing = false
let pendingQueue: { resolve: (token: string) => void; reject: (err: unknown) => void }[] = []

function flushQueue(error: unknown, token: string | null): void {
  pendingQueue.forEach(({ resolve, reject }) => {
    if (error || !token) reject(error)
    else resolve(token)
  })
  pendingQueue = []
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as
      | (InternalAxiosRequestConfig & { _retry?: boolean })
      | undefined

    const isAuthEndpoint = originalRequest?.url?.includes('/auth/login')

    // تعدد الأدوار: الدور الحالي تغيّر من نافذة أخرى — useActiveRoleSync
    // (AppShell) يعيد تحميل بيانات المستخدم ويحدّث الصفحة بالدور الصحيح.
    if (isActiveRoleChangedError(error)) {
      window.dispatchEvent(new CustomEvent(ACTIVE_ROLE_CHANGED_EVENT))
      return Promise.reject(error)
    }

    if (error.response?.status !== 401 || !originalRequest || originalRequest._retry || isAuthEndpoint) {
      return Promise.reject(error)
    }

    const { refreshToken, setTokens, logout } = useAuthStore.getState()
    if (!refreshToken) {
      notify('انتهت الجلسة — يُرجى تسجيل الدخول مرة أخرى', 'error')
      logout()
      return Promise.reject(error)
    }

    if (isRefreshing) {
      return new Promise((resolve, reject) => {
        pendingQueue.push({
          resolve: (token) => {
            originalRequest._retry = true
            originalRequest.headers.Authorization = `Bearer ${token}`
            resolve(apiClient(originalRequest))
          },
          reject,
        })
      })
    }

    originalRequest._retry = true
    isRefreshing = true

    try {
      const { data } = await axios.post<TokenResponse>(`${API_BASE_URL}/auth/refresh`, {
        refresh_token: refreshToken,
      })
      setTokens(data.access_token, data.refresh_token)
      flushQueue(null, data.access_token)
      originalRequest.headers.Authorization = `Bearer ${data.access_token}`
      return apiClient(originalRequest)
    } catch (refreshError) {
      flushQueue(refreshError, null)
      // تحديث 2026-09-10 (بلاغ لاما — "زر الحفظ ما يشتغل"): تبيّن إن
      // السبب كان انتهاء الجلسة فعليًا (فشل تجديد التوكن) — logout() كان
      // يصير صامتًا بدون أي رسالة، فيبدو للمستخدمة إن الزر ببساطة "ما
      // يستجيب" رغم إن التحويل لصفحة الدخول صار فعليًا. هذا التنبيه يوضّح
      // السبب الحقيقي قبل التحويل.
      // الضيف (migration 0047): جلسته تنتهي بانتهاء الاجتماع — لا "سجّل دخولك".
      if (useAuthStore.getState().user?.is_guest) notify('انتهى الاجتماع — شكرًا لحضورك', 'info')
      else notify('انتهت الجلسة — يُرجى تسجيل الدخول مرة أخرى', 'error')
      logout()
      return Promise.reject(refreshError)
    } finally {
      isRefreshing = false
    }
  },
)
