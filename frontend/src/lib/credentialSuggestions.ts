/**
 * الهدف:
 * اقتراح بيانات دخول أولية (اسم مستخدم + كلمة مرور مؤقتة) داخل نموذج
 * "إضافة مستخدم جديد"، لتسريع إدخال الموظفين على السوبر ادمن.
 *
 * ملاحظات:
 * - هذه اقتراحات فقط في الواجهة؛ الـBackend يبقى هو المرجع: يتحقق من سياسة
 *   كلمة المرور (FR-UM-015) ومن عدم تكرار اسم المستخدم (FR-UM-001) كالمعتاد.
 * - لا شيء هنا يرسل بيانات للسيرفر أو يخزّنها.
 */

const USERNAME_MIN_LENGTH = 3
const USERNAME_MAX_LENGTH = 50

/** الحد الأدنى المسموح لطول كلمة المرور حسب سياسة FR-UM-015. */
const PASSWORD_MIN_LENGTH = 8

/** الطول الافتراضي لكلمة المرور المؤقتة المقترحة (أطول من الحد الأدنى عمدًا). */
export const SUGGESTED_PASSWORD_LENGTH = 12

// الأحرف المتشابهة بصريًا (O/0، I/l/1) مستبعدة عمدًا، لأن السوبر ادمن قد
// يُملي كلمة المرور المؤقتة للموظف شفهيًا أو يكتبها يدويًا.
const UPPERCASE = 'ABCDEFGHJKLMNPQRSTUVWXYZ'
const LOWERCASE = 'abcdefghijkmnpqrstuvwxyz'
const DIGITS = '23456789'
const ALL_PASSWORD_CHARS = UPPERCASE + LOWERCASE + DIGITS

/**
 * الهدف:
 * اقتراح اسم مستخدم من البريد الإلكتروني للموظف.
 *
 * المسؤولية:
 * تأخذ الجزء الذي قبل "@" (أو النص كاملًا إن لم تُكتب "@" بعد، ليعمل
 * الاقتراح أثناء الكتابة)، وتحوّله لصيغة يقبلها حقل اسم المستخدم:
 * أحرف إنجليزية صغيرة وأرقام و"." و"_" فقط، بطول من 3 إلى 50 حرفًا.
 *
 * لماذا البريد وليس الاسم؟
 * الأسماء تُدخَل بالعربي، وتحويلها لحروف إنجليزية غير موحّد
 * (محمد = mohammed / muhammad / mohamed). البريد الوظيفي فريد أصلًا
 * ومكتوب بالإنجليزي، فالاقتراح منه ثابت ومتوقّع لكل الموظفين.
 *
 * المدخلات:
 * - email: نص البريد الإلكتروني كما كُتب بالحقل (قد يكون ناقصًا أثناء الكتابة).
 *
 * المخرجات:
 * - string: اسم مستخدم مقترح صالح لنمط الحقل /^[a-z0-9_.]+$/.
 * - null: إذا لم ينتج اسم صالح بطول 3 أحرف على الأقل.
 *
 * قواعد التحويل:
 * - إزالة وسم "+" (مثال: ahmed+test@x.com ← ahmed).
 * - تحويل الأحرف الكبيرة لصغيرة.
 * - استبدال أي حرف غير مسموح (مثل "-") بـ"_".
 * - دمج الفواصل المتتالية وحذفها من البداية والنهاية.
 *
 * التأثيرات الجانبية: لا يوجد (دالة نقية).
 */
export function suggestUsernameFromEmail(email: string): string | null {
  const localPart = email.trim().split('@')[0].split('+')[0]

  let username = localPart
    .toLowerCase()
    .replace(/[^a-z0-9_.]/g, '_')
    .replace(/([._])[._]+/g, '$1')
    .replace(/^[._]+|[._]+$/g, '')

  username = username.slice(0, USERNAME_MAX_LENGTH).replace(/[._]+$/g, '')

  return username.length >= USERNAME_MIN_LENGTH ? username : null
}

/**
 * الهدف:
 * توليد عدد صحيح عشوائي آمن تشفيريًا ضمن [0, maxExclusive).
 *
 * المسؤولية:
 * تستخدم crypto.getRandomValues بدل Math.random (غير آمن لكلمات المرور)،
 * مع Rejection Sampling لتجنّب انحياز باقي القسمة (Modulo Bias).
 *
 * المدخلات:
 * - maxExclusive: الحد الأعلى غير الشامل (عدد صحيح موجب).
 *
 * المخرجات:
 * - number: عدد صحيح من 0 حتى maxExclusive - 1.
 */
function secureRandomInt(maxExclusive: number): number {
  const range = 0x100000000
  const limit = range - (range % maxExclusive)
  const buffer = new Uint32Array(1)
  let value: number
  do {
    crypto.getRandomValues(buffer)
    value = buffer[0]
  } while (value >= limit)
  return value % maxExclusive
}

/** اختيار حرف عشوائي آمن من مجموعة أحرف. */
function pickRandomChar(chars: string): string {
  return chars[secureRandomInt(chars.length)]
}

/**
 * الهدف:
 * توليد كلمة مرور مؤقتة قوية للمستخدم الجديد.
 *
 * المسؤولية:
 * تضمن مطابقة سياسة FR-UM-015 دائمًا: حرف كبير واحد على الأقل، وحرف صغير
 * واحد على الأقل، ورقم واحد على الأقل، وطول 8 أحرف فأكثر. ثم تخلط ترتيب
 * الأحرف عشوائيًا (Fisher–Yates) حتى لا تكون الأحرف الإلزامية بمواقع ثابتة.
 *
 * المدخلات:
 * - length: طول كلمة المرور (افتراضيًا SUGGESTED_PASSWORD_LENGTH = 12).
 *
 * المخرجات:
 * - string: كلمة مرور عشوائية بالطول المطلوب.
 *
 * الأخطاء المحتملة:
 * - RangeError: إذا كان الطول أقل من 8 (الحد الأدنى للسياسة).
 *
 * التأثيرات الجانبية: لا يوجد (تقرأ من مولّد الأرقام العشوائية فقط).
 *
 * ملاحظة أمنية:
 * كلمة المرور مؤقتة؛ النظام يُلزم المستخدم بتغييرها عند أول دخول (FR-UM-016).
 */
export function generateTemporaryPassword(length: number = SUGGESTED_PASSWORD_LENGTH): string {
  if (!Number.isInteger(length) || length < PASSWORD_MIN_LENGTH) {
    throw new RangeError(`طول كلمة المرور يجب أن يكون ${PASSWORD_MIN_LENGTH} أحرف على الأقل`)
  }

  const chars = [pickRandomChar(UPPERCASE), pickRandomChar(LOWERCASE), pickRandomChar(DIGITS)]
  while (chars.length < length) {
    chars.push(pickRandomChar(ALL_PASSWORD_CHARS))
  }

  for (let i = chars.length - 1; i > 0; i--) {
    const j = secureRandomInt(i + 1)
    ;[chars[i], chars[j]] = [chars[j], chars[i]]
  }

  return chars.join('')
}
