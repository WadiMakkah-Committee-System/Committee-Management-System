import type { AccountInfo, IPublicClientApplication } from '@azure/msal-browser'

/**
 * الهدف: تسجيل دخول موظف الشركة بحساب Microsoft 365 من داخل المنصة (مرة وحدة)،
 * عشان يدخل اجتماعات Teams المدمجة **بهويته الحقيقية**: باسمه، وبدون انتظار
 * بالـLobby، والمنظّم/الرئيس يدخل كمنظّم ويقدر يقبل الضيوف من المنصة.
 *
 * المسؤولية:
 * - تهيئة MSAL (مكتبة Microsoft الرسمية @azure/msal-browser) مرة واحدة.
 * - signInMicrosoft: نافذة منبثقة لتسجيل الدخول وطلب توكن Teams.
 * - getMicrosoftTeamsToken: توكن صامت (بدون نافذة) للحساب المحفوظ.
 * - signOutMicrosoft: نسيان الحساب من هذا المتصفح.
 *
 * الإعداد (ليست أسرارًا — معرّفات عامة): VITE_MS_CLIENT_ID (Application ID
 * لتطبيق Entra نفسه المستخدم بالباك-إند) وVITE_MS_TENANT_ID. غيابهما يعني أن
 * الميزة معطّلة ويبقى الدخول كضيف فقط.
 *
 * أمان: التوكن لا يُخزَّن بقاعدة البيانات ولا يُرسَل لأي جهة غير الباك-إند،
 * والباك-إند يمرّره لـAzure Communication Services الذي يتحقق من توقيعه.
 * ملاحظة أداء: المكتبة تُحمَّل ديناميكيًا (import()) فقط داخل غرفة الاجتماع.
 */

const CLIENT_ID = (import.meta.env.VITE_MS_CLIENT_ID as string | undefined)?.trim() ?? ''
const TENANT_ID = (import.meta.env.VITE_MS_TENANT_ID as string | undefined)?.trim() ?? ''

/** نطاقا Azure Communication Services لمستخدمي Teams (مكالمات + محادثات الاجتماع). */
const TEAMS_SCOPES = [
  'https://auth.msft.communication.azure.com/Teams.ManageCalls',
  'https://auth.msft.communication.azure.com/Teams.ManageChats',
]

/** هل الدخول بحساب Microsoft مفعّل بهذه البيئة. */
export function isMicrosoftSignInConfigured(): boolean {
  return Boolean(CLIENT_ID && TENANT_ID)
}

let pcaPromise: Promise<IPublicClientApplication> | null = null

/**
 * يرجع نسخة MSAL المهيّأة (مرة واحدة لكل تحميل صفحة).
 * redirectUri يشير لصفحة الجسر /redirect.html (مطلوبة بـMSAL v5 لإرجاع نتيجة
 * النافذة المنبثقة للصفحة الأصلية). الكاش بـlocalStorage حتى يبقى المستخدم
 * مسجّلًا بين الزيارات — "مرة وحدة".
 */
export function loadMicrosoftClient(): Promise<IPublicClientApplication> {
  if (!pcaPromise) {
    pcaPromise = import('@azure/msal-browser').then(async (msal) => {
      const pca = await msal.createStandardPublicClientApplication({
        auth: {
          clientId: CLIENT_ID,
          authority: `https://login.microsoftonline.com/${TENANT_ID}`,
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

/** الحساب المسجّل حاليًا بهذا المتصفح (أو null). */
export async function getMicrosoftAccount(): Promise<AccountInfo | null> {
  const pca = await loadMicrosoftClient()
  return pca.getActiveAccount()
}

/**
 * تسجيل الدخول بنافذة منبثقة + توكن Teams.
 * يجب أن يُستدعى مباشرة من ضغطة زر (وإلا قد يحجب المتصفح النافذة)، لذلك
 * تُهيَّأ MSAL مسبقًا بفتح الغرفة (loadMicrosoftClient).
 * المخرجات: { token, account }. الأخطاء: إغلاق النافذة/رفض الموافقة ⇒ يُرمى الخطأ.
 */
export async function signInMicrosoft(): Promise<{ token: string; account: AccountInfo }> {
  const pca = await loadMicrosoftClient()
  const result = await pca.acquireTokenPopup({ scopes: TEAMS_SCOPES, prompt: 'select_account' })
  if (!result.account) throw new Error('لم يكتمل تسجيل الدخول بحساب Microsoft')
  pca.setActiveAccount(result.account)
  return { token: result.accessToken, account: result.account }
}

/**
 * توكن Teams صامت للحساب المحفوظ (يُجدَّد تلقائيًا من MSAL).
 * المخرجات: التوكن، أو null لو لا يوجد حساب أو انتهت الجلسة وتحتاج تسجيل دخول جديد.
 */
export async function getMicrosoftTeamsToken(): Promise<string | null> {
  const pca = await loadMicrosoftClient()
  const account = pca.getActiveAccount()
  if (!account) return null
  try {
    const result = await pca.acquireTokenSilent({ scopes: TEAMS_SCOPES, account })
    return result.accessToken
  } catch {
    return null
  }
}

/** نسيان حساب Microsoft من هذا المتصفح فقط (لا يسجّل الخروج من Microsoft نفسها). */
export async function signOutMicrosoft(): Promise<void> {
  const pca = await loadMicrosoftClient()
  const account = pca.getActiveAccount()
  pca.setActiveAccount(null)
  if (account) await pca.clearCache({ account })
}
