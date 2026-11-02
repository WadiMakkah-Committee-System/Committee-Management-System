import type { AccountInfo, IPublicClientApplication } from '@azure/msal-browser'
import { getLoginOptions } from '@/api/auth'
import type { LoginOptions } from '@/types'

/**
 * الهدف: الدخول للمنصة بحساب Microsoft 365 حق الشركة (migration 0042)، ونفس
 * الدخول يفتح اجتماعات Teams المدمجة بهوية الموظف الحقيقية بدون أي نافذة ثانية.
 *
 * المسؤولية:
 * - loadLoginOptions: إعدادات الدخول من الباك-إند (GET /auth/login-options) —
 *   معرّفا تطبيق Entra ونطاقات بريد الشركة. ما فيه متغيرات بيئة بالواجهة.
 * - isCompanyEmail: هل المكتوب بخانة الدخول بريد شركة (يحوَّل لـMicrosoft).
 * - signInWithMicrosoft: نافذة Microsoft ⇒ ID Token (للدخول للمنصة) + موافقة
 *   على صلاحية Teams بنفس النافذة (عشان الاجتماعات ما تطلب شي بعدين).
 * - getMicrosoftTeamsToken: توكن Teams صامت للاجتماع (بدون نافذة).
 * - signOutMicrosoft: نسيان حساب Microsoft من هذا المتصفح (مع كل خروج).
 *
 * أمان: الواجهة ما تقرر شي — ID Token يتحقق منه الباك-إند (التوقيع/المستأجر/
 * التطبيق) ويربطه بمستخدم أنشأه السوبر أدمن. التوكنات لا تُخزَّن بقاعدة البيانات.
 * ملاحظة أداء: مكتبة MSAL تُحمَّل ديناميكيًا (import()) فقط لما الميزة مفعّلة.
 */

/** نطاقا Azure Communication Services لمستخدمي Teams (مكالمات + محادثات الاجتماع). */
const TEAMS_SCOPES = [
  'https://auth.msft.communication.azure.com/Teams.ManageCalls',
  'https://auth.msft.communication.azure.com/Teams.ManageChats',
]
const SIGN_IN_SCOPES = ['openid', 'profile', 'email']

let optionsPromise: Promise<LoginOptions> | null = null
let pcaPromise: Promise<IPublicClientApplication | null> | null = null

/** إعدادات الدخول من الباك-إند (تُجلب مرة واحدة لكل تحميل صفحة). */
export function loadLoginOptions(): Promise<LoginOptions> {
  if (!optionsPromise) {
    optionsPromise = getLoginOptions()
    optionsPromise.catch(() => {
      optionsPromise = null
    })
  }
  return optionsPromise
}

/** هل النص بريد من نطاقات الشركة (مثل name@wadimakkah.sa) — بدون حساسية للأحرف. */
export function isCompanyEmail(value: string, options: LoginOptions | null | undefined): boolean {
  if (!options?.microsoft_enabled) return false
  const at = value.trim().lastIndexOf('@')
  if (at <= 0) return false
  const domain = value.trim().slice(at + 1).toLowerCase()
  return options.microsoft_domains.includes(domain)
}

/**
 * نسخة MSAL المهيّأة (مرة واحدة لكل تحميل صفحة)، أو null لو الميزة غير مفعّلة.
 * redirectUri يشير لصفحة الجسر /redirect.html (مطلوبة بـMSAL v5 لإرجاع نتيجة
 * النافذة المنبثقة). الكاش بـlocalStorage حتى تبقى جلسة Microsoft بعد تحديث
 * الصفحة — وتُمسح مع كل خروج من المنصة (authStore.logout).
 */
export function loadMicrosoftClient(): Promise<IPublicClientApplication | null> {
  if (!pcaPromise) {
    pcaPromise = loadLoginOptions().then(async (options) => {
      if (!options.microsoft_enabled || !options.microsoft_client_id || !options.microsoft_tenant_id) return null
      const msal = await import('@azure/msal-browser')
      const pca = await msal.createStandardPublicClientApplication({
        auth: {
          clientId: options.microsoft_client_id,
          authority: `https://login.microsoftonline.com/${options.microsoft_tenant_id}`,
          redirectUri: `${window.location.origin}/redirect.html`,
        },
        cache: { cacheLocation: msal.BrowserCacheLocation.LocalStorage },
      })
      const account = pca.getActiveAccount() ?? pca.getAllAccounts()[0] ?? null
      if (account) pca.setActiveAccount(account)
      return pca
    })
    pcaPromise.catch(() => {
      pcaPromise = null
    })
  }
  return pcaPromise
}

/** هل الخطأ مجرد إغلاق المستخدم لنافذة Microsoft (ما نعرض له رسالة خطأ). */
export function isMicrosoftCancel(err: unknown): boolean {
  return typeof err === 'object' && err !== null && (err as { errorCode?: string }).errorCode === 'user_cancelled'
}

/**
 * تسجيل الدخول بنافذة Microsoft.
 * لازم يُستدعى مباشرة من ضغطة زر (وإلا يحجب المتصفح النافذة) — لذلك صفحة
 * الدخول تهيّئ MSAL مسبقًا (loadMicrosoftClient) أول ما تفتح.
 * loginHint: البريد المكتوب بخانة الدخول — Microsoft تعبّيه تلقائيًا.
 * المخرجات: ID Token (يُرسل للباك-إند) + الحساب. الأخطاء: إغلاق النافذة/رفض.
 */
export async function signInWithMicrosoft(loginHint?: string): Promise<{ idToken: string; account: AccountInfo }> {
  const pca = await loadMicrosoftClient()
  if (!pca) throw new Error('الدخول بحساب Microsoft غير مفعّل حاليًا')
  const result = await pca.loginPopup({
    scopes: SIGN_IN_SCOPES,
    // موافقة صلاحية Teams بنفس النافذة — عشان الاجتماع يفتح بدون نافذة ثانية.
    extraScopesToConsent: TEAMS_SCOPES,
    loginHint: loginHint?.trim() || undefined,
    prompt: loginHint ? undefined : 'select_account',
  })
  if (!result.account || !result.idToken) throw new Error('لم يكتمل تسجيل الدخول بحساب Microsoft')
  pca.setActiveAccount(result.account)
  return { idToken: result.idToken, account: result.account }
}

/**
 * توكن Teams للاجتماع لحساب Microsoft المحفوظ.
 * interactive=false (الافتراضي): صامت فقط — null لو يحتاج تفاعل.
 * interactive=true: لو الصامت فشل (انتهت جلسة Microsoft) يفتح نافذة — فقط من ضغطة زر.
 */
export async function getMicrosoftTeamsToken(interactive = false): Promise<string | null> {
  const pca = await loadMicrosoftClient()
  const account = pca?.getActiveAccount()
  if (!pca || !account) return null
  try {
    return (await pca.acquireTokenSilent({ scopes: TEAMS_SCOPES, account })).accessToken
  } catch {
    if (!interactive) return null
    try {
      return (await pca.acquireTokenPopup({ scopes: TEAMS_SCOPES, account, loginHint: account.username }))
        .accessToken
    } catch {
      return null
    }
  }
}

/** نسيان حساب Microsoft من هذا المتصفح فقط (ما يسجّل الخروج من Microsoft نفسها). */
export async function signOutMicrosoft(): Promise<void> {
  const pca = await loadMicrosoftClient()
  if (!pca) return
  pca.setActiveAccount(null)
  await pca.clearCache()
}
