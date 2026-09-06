import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/store/authStore'
import type { TokenResponse } from '@/types'

/**
 * الهدف: طبقة اتصال مركزية بالـ API — تُرفق JWT تلقائيًا، وتُجدّد التوكن
 * عند انتهاء صلاحيته (401) عبر Refresh Token دون إزعاج المستخدم، وإذا فشل
 * التجديد نفسه (الجلسة انتهت فعلًا) تسجّل خروجه وتُعيده لصفحة الدخول.
 */

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
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

    if (error.response?.status !== 401 || !originalRequest || originalRequest._retry || isAuthEndpoint) {
      return Promise.reject(error)
    }

    const { refreshToken, setTokens, logout } = useAuthStore.getState()
    if (!refreshToken) {
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
      logout()
      return Promise.reject(refreshError)
    } finally {
      isRefreshing = false
    }
  },
)
