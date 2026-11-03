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
 * - دخول بضغطة وحدة (قرار لاما 2026-11-03): تذكّر إيميل الشركة على الجهاز
 *   (remember/forget...)، ودخول صامت مسبق (prepareSilentSignIn) بدون أي نافذة
 *   لو جلسة Microsoft موجودة بالمتصفح — فالضغطة تدخل مباشرة.
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

const REMEMBERED_EMAIL_KEY = 'wm-last-microsoft-email'

let optionsPromise: Promise<LoginOptions> | null = null
// نتيجة الدخول الصامت المسبق لآخر إيميل جُرِّب — تُستهلك عند الضغط بدون انتظار
// (الانتظار يضيّع "ضغطة المستخدم" فيحجب المتصفح النافذة لو احتجناها).
let prepared: { hint: string; at: number; result: { idToken: string; account: AccountInfo } } | null = null
// ID Token صالح ساعة — نتيجة أقدم من 30 دقيقة ما نستخدمها (نفتح النافذة بدالها).
const PREPARED_MAX_AGE_MS = 30 * 60 * 1000
let preparing: { hint: string; promise: Promise<unknown> } | null = null

/** آخر إيميل شركة دخل به أحد من هذا الجهاز (أو null). الإيميل فقط — بدون أي توكن. */
export function getRememberedMicrosoftEmail(): string | null {
  try {
    return localStorage.getItem(REMEMBERED_EMAIL_KEY)
  } catch {
    return null
  }
}

/** يحفظ إيميل الشركة بعد دخول ناجح (تعبئة تلقائية بالمرة الجاية). */
export function rememberMicrosoftEmail(email: string): void {
  try {
    localStorage.setItem(REMEMBERED_EMAIL_KEY, email.trim())
  } catch {
    /* التخزين غير متاح (وضع خاص مثلًا) — الميزة اختيارية */
  }
}

/** "مو أنت؟" — ينسى الإيميل المحفوظ ونتيجة الدخول الصامت. */
export function forgetMicrosoftEmail(): void {
  prepared = null
  preparing = null
  try {
    localStorage.removeItem(REMEMBERED_EMAIL_KEY)
  } catch {
    /* تجاهل */
  }
}

/**
 * دخول صامت مسبق (بدون نافذة): لو المتصفح فيه جلسة Microsoft لهذا الإيميل،
 * نجيب ID Token في الخلفية وهو يكتب/أول ما تفتح الصفحة — فلما يضغط "دخول"
 * يدخل فورًا. يفشل بصمت (مثلًا المتصفح يحجب كوكيز الطرف الثالث) ووقتها
 * الضغطة تفتح نافذة Microsoft بالإيميل جاهز (تختار الحساب وتقفل لحالها).
 */
export function prepareSilentSignIn(loginHint: string): void {
  const hint = loginHint.trim().toLowerCase()
  if (!hint || prepared?.hint === hint || preparing?.hint === hint) return
  const promise = loadMicrosoftClient()
    .then(async (pca) => {
      if (!pca) return
      const result = await pca.ssoSilent({ scopes: SIGN_IN_SCOPES, loginHint: hint })
      if (result.account && result.idToken && preparing?.hint === hint) {
        prepared = { hint, at: Date.now(), result: { idToken: result.idToken, account: result.account } }
      }
    })
    .catch(() => {})
    .finally(() => {
      if (preparing?.hint === hint) preparing = null
    })
  preparing = { hint, promise }
}
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
  const hint = loginHint?.trim().toLowerCase()
  if (hint && prepared?.hint === hint && Date.now() - prepared.at < PREPARED_MAX_AGE_MS) {
    const ready = prepared.result
    prepared = null
    const pcaReady = await loadMicrosoftClient()
    pcaReady?.setActiveAccount(ready.account)
    return ready
  }
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
/** توكن Teams للاجتماع + معرّف حساب Microsoft (oid) اللي صدر له. */
export interface MicrosoftTeamsToken {
  token: string
  objectId: string
}

export async function getMicrosoftTeamsToken(interactive = false): Promise<MicrosoftTeamsToken | null> {
  const pca = await loadMicrosoftClient()
  const account = pca?.getActiveAccount()
  if (!pca || !account) return null
  // localAccountId = معرّف حساب Microsoft (oid) — الباك-إند يتأكد إنه نفس الحساب
  // المربوط بمستخدم المنصة. التوكن نفسه مشفّر لخدمة Microsoft وما ينقرأ.
  const withId = (token: string): MicrosoftTeamsToken => ({ token, objectId: account.localAccountId })
  try {
    return withId((await pca.acquireTokenSilent({ scopes: TEAMS_SCOPES, account })).accessToken)
  } catch {
    if (!interactive) return null
    try {
      return withId(
        (await pca.acquireTokenPopup({ scopes: TEAMS_SCOPES, account, loginHint: account.username })).accessToken,
      )
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
