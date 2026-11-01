import { apiClient } from '@/lib/apiClient'
import type { LoginPayload, TokenResponse } from '@/types'

export async function login(payload: LoginPayload): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>('/auth/login', payload)
  return data
}

export async function logout(): Promise<void> {
  await apiClient.post('/auth/logout')
}

/**
 * FR-UM-018 — POST /auth/forgot-password (عام، بدون توكن).
 * يطلب إرسال رمز استعادة (6 أرقام) لبريد المستخدم. يرجع 204 دائمًا —
 * حتى لو البريد غير مسجّل — فلا تُبنى أي رسالة بالواجهة على وجود البريد.
 * يرمي خطأ 422 فقط لصيغة بريد غير صالحة.
 */
export async function requestPasswordReset(email: string): Promise<void> {
  await apiClient.post('/auth/forgot-password', { email })
}

/**
 * FR-UM-018 — POST /auth/verify-reset-code (عام).
 * يتحقق من الرمز كخطوة مستقلة قبل إدخال كلمة المرور الجديدة، دون استهلاكه.
 * يرمي 400 برسالة عامة عند رمز خاطئ/منتهٍ/تجاوز عدد المحاولات (5).
 */
export async function verifyResetCode(payload: { email: string; otp_code: string }): Promise<void> {
  await apiClient.post('/auth/verify-reset-code', payload)
}

/**
 * FR-UM-018 — POST /auth/reset-password (عام).
 * يعيّن كلمة المرور الجديدة (يعيد الخادم التحقق من الرمز)، ويسجّل خروج
 * المستخدم من كل الأجهزة. يرمي 400 لرمز غير صالح، و422 لكلمة مرور تخالف السياسة.
 */
export async function resetPassword(payload: {
  email: string
  otp_code: string
  new_password: string
}): Promise<void> {
  await apiClient.post('/auth/reset-password', payload)
}

export async function changePassword(payload: {
  current_password: string
  new_password: string
}): Promise<void> {
  await apiClient.post('/auth/change-password', payload)
}
