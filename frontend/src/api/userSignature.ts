import { apiClient } from '@/lib/apiClient'

/**
 * "توقيعي" — التوقيع المحفوظ للمستخدم الحالي (backend: app/api/v1/user_signature.py،
 * migration 0049). يُستخدم للتوقيع على المحاضر بدل رسمه كل مرة. كل مستخدم يقرأ
 * ويعدّل توقيعه هو فقط (المعرّف من التوكن بالخادم).
 */

export interface SavedSignature {
  signature_image: string
  updated_at: string
}

/** توقيعي المحفوظ، أو null لو ما عندي توقيع (404). */
export async function fetchMySignature(): Promise<SavedSignature | null> {
  try {
    const { data } = await apiClient.get<SavedSignature>('/users/me/signature')
    return data
  } catch (error) {
    if ((error as { response?: { status?: number } })?.response?.status === 404) return null
    throw error
  }
}

/** حفظ/استبدال توقيعي (صورة PNG بصيغة data URL). */
export async function saveMySignature(signatureImage: string): Promise<SavedSignature> {
  const { data } = await apiClient.put<SavedSignature>('/users/me/signature', { signature_image: signatureImage })
  return data
}

/** حذف توقيعي المحفوظ (المحاضر الموقّعة سابقًا لا تتأثر). */
export async function deleteMySignature(): Promise<void> {
  await apiClient.delete('/users/me/signature')
}
