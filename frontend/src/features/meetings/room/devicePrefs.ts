/**
 * تفضيلات أجهزة الاجتماع على هذا الجهاز (قرار لاما 2026-11-03 — فحص الأجهزة):
 * الكاميرا/المايك/السماعة المختارة، وهل يدخل والكاميرا/المايك شغالين.
 * تُحفظ بالمتصفح (localStorage) — تفضيل شخصي للجهاز، مو بيانات منصة.
 * شاشة الفحص (DeviceCheck) تطلع أول مرة فقط على الجهاز (isDeviceCheckDone).
 */
export interface DevicePrefs {
  cameraId: string | null
  microphoneId: string | null
  speakerId: string | null
  cameraOn: boolean
  micOn: boolean
}

const PREFS_KEY = 'wm-meeting-device-prefs'
const DONE_KEY = 'wm-meeting-device-check-done'

const DEFAULT_PREFS: DevicePrefs = { cameraId: null, microphoneId: null, speakerId: null, cameraOn: true, micOn: true }

export function getDevicePrefs(): DevicePrefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    return raw ? { ...DEFAULT_PREFS, ...(JSON.parse(raw) as Partial<DevicePrefs>) } : DEFAULT_PREFS
  } catch {
    return DEFAULT_PREFS
  }
}

export function saveDevicePrefs(prefs: DevicePrefs): void {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs))
    localStorage.setItem(DONE_KEY, '1')
  } catch {
    /* التخزين غير متاح — نكمل بالإعدادات الحالية بدون حفظ */
  }
}

export function isDeviceCheckDone(): boolean {
  try {
    return localStorage.getItem(DONE_KEY) === '1'
  } catch {
    return true // ما نقدر نتذكر ⇒ ما نزعجه بالشاشة كل مرة
  }
}
