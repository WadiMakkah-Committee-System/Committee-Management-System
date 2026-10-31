"""
الهدف:
إرسال بريد إلكتروني فعليًا عبر SMTP (Gmail/Outlook أو أي مزوّد قياسي آخر)
بشكل غير متزامن (async) — حتى لا يوقف Event Loop أثناء انتظار اتصال شبكي
ببطء SMTP، بنفس روح تحسين أداء get_current_user (راجعي user_service.py،
تحديث 2026-09-06): ما نبي نرجّع بطئًا جديدًا للموقع عبر عملية بريد بطيئة.

المسؤولية:
- send_email(): يرسل رسالة HTML واحدة لعدة مستلمين، باتصال SMTP واحد
  يُعاد استخدامه لكل المستلمين (بدل فتح اتصال جديد لكل بريد).
- لا يُفشل أبدًا العملية الأصلية (إنشاء/تعديل/حذف اجتماع) بسبب خطأ إرسال —
  الإشعار البريدي إضافة، وليس جزءًا من نجاح العملية نفسها. أي خطأ (شبكة/
  بيانات SMTP خاطئة/مزوّد يرفض الاتصال) يُسجَّل بالسجلات (logger.exception)
  فقط، ولا يُرفَع للمستدعي — لهذا السبب تحديدًا تُستدعى دائمًا كـ
  BackgroundTasks من طبقة الـAPI (بعد db.commit())، وليس بشكل مباشر
  ومتزامن ضمن معاملة الطلب.

ملاحظة أمنية: SMTP_PASSWORD (App Password غالبًا لا كلمة مرور الحساب
الفعلية) تُقرأ من .env فقط عبر core.config، ولا تظهر بالسجلات إطلاقًا.

تحديث 2026-10-31 (بلاغ لاما — البريد لا يصل إطلاقًا من بيئة الإنتاج):
الباك إند على Render بخطة free، وRender يحجب منذ سبتمبر 2025 كل اتصال
صادر من الخدمات المجانية على منافذ SMTP (25/465/587) — فاتصال aiosmtplib
يسقط بـtimeout مهما كان الحساب/الـApp Password صحيحًا. الحل: مسار إرسال
بديل عبر HTTP API لمزوّد بريد (HTTPS على 443 غير محجوب)، يُختار بمتغير
البيئة EMAIL_PROVIDER:
- "smtp" (الافتراضي): السلوك القديم كما هو بالضبط — يبقى للسيرفر الخاص
  بالشركة لاحقًا أو أي بيئة لا تحجب SMTP.
- "resend": عبر https://api.resend.com/emails (يتطلب دومين مُوثَّق بحساب
  Resend للإرسال لأي مستلم).
- "brevo": عبر https://api.brevo.com/v3/smtp/email (يكفي مُرسِل مُوثَّق).
المفتاح في EMAIL_API_KEY، والمُرسِل الظاهر من SMTP_FROM_EMAIL/SMTP_FROM_NAME
(نفس المتغيرات القائمة، حتى لا يتكرر تعريف المُرسِل بمكانين). لا مكتبة
جديدة — httpx موجودة أصلًا بـrequirements.txt.
"""

import logging
from email.message import EmailMessage

import aiosmtplib
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# نص بديل لعارضات البريد التي لا تدعم HTML — نفس النص بكل المسارات.
_PLAIN_TEXT_FALLBACK = "هذه الرسالة بصيغة HTML — افتحيها بعارض بريد يدعم HTML."

# نفس حد الـtimeout المستخدم بمسار SMTP (راجعي تعليق 2026-09-10 أدناه):
# فشل سريع بدل تعليق طويل يحجز جلسة DB الطلب الأصلي.
_HTTP_TIMEOUT_SECONDS = 10

_RESEND_URL = "https://api.resend.com/emails"
_BREVO_URL = "https://api.brevo.com/v3/smtp/email"
_HTTP_PROVIDERS = ("resend", "brevo")


async def send_email(*, to: list[str], subject: str, html_body: str) -> None:
    """
    الهدف:
    نقطة الدخول الوحيدة لإرسال البريد بالنظام (كل notify_* تستدعيها).

    المسؤولية:
    يرسل نفس الرسالة (subject/html_body) لكل عنوان بـ`to` كرسالة منفصلة —
    عزل الخصوصية بين المستلمين (لا يرى عضو باقي عناوين أعضاء اللجنة بحقل
    To/Cc) — عبر المزوّد المحدد بـEMAIL_PROVIDER (smtp/resend/brevo).

    المدخلات:
    - to: list[str] — عناوين المستلمين (القيم الفارغة تُتجاهل).
    - subject: str — عنوان الرسالة.
    - html_body: str — محتوى الرسالة بصيغة HTML.

    المخرجات: None.

    التأثيرات الجانبية:
    اتصال شبكي خارجي (SMTP أو HTTPS لمزوّد البريد). لا يلمس قاعدة البيانات.

    الأخطاء المحتملة:
    لا يرفع أي استثناء للمستدعي إطلاقًا — كل فشل (إعدادات ناقصة/شبكة/رفض
    المزوّد) يُسجَّل بالسجلات فقط، لأن البريد إضافة لا شرط لنجاح العملية.
    """
    recipients = [addr for addr in to if addr]
    if not recipients:
        return

    provider = (settings.EMAIL_PROVIDER or "smtp").strip().lower()
    if provider in _HTTP_PROVIDERS:
        await _send_via_http_api(provider=provider, recipients=recipients, subject=subject, html_body=html_body)
        return
    if provider != "smtp":
        logger.error("EMAIL_PROVIDER غير معروف (%s) — تم تجاوز إرسال البريد: %s", provider, subject)
        return

    await _send_via_smtp(recipients=recipients, subject=subject, html_body=html_body)


def _build_http_request(
    *, provider: str, recipient: str, subject: str, html_body: str, from_email: str, from_name: str
) -> tuple[str, dict[str, str], dict]:
    """
    الهدف:
    بناء طلب HTTP (الرابط + الترويسات + الجسم) لرسالة واحدة حسب صيغة كل مزوّد.

    المدخلات:
    - provider: "resend" أو "brevo".
    - recipient: str — مستلم واحد فقط (عزل الخصوصية، نفس مسار SMTP).
    - subject/html_body: محتوى الرسالة.
    - from_email/from_name: هوية المُرسِل الظاهرة.

    المخرجات:
    tuple(url, headers, json_payload).

    التأثيرات الجانبية: لا شيء (دالة نقية — قابلة للاختبار بدون شبكة).

    ملاحظة أمنية: المفتاح يوضع بالترويسة فقط ولا يُسجَّل بالسجلات أبدًا.
    """
    if provider == "resend":
        sender = f"{from_name} <{from_email}>" if from_name else from_email
        return (
            _RESEND_URL,
            {"Authorization": f"Bearer {settings.EMAIL_API_KEY}"},
            {
                "from": sender,
                "to": [recipient],
                "subject": subject,
                "html": html_body,
                "text": _PLAIN_TEXT_FALLBACK,
            },
        )
    # brevo
    sender_obj = {"email": from_email}
    if from_name:
        sender_obj["name"] = from_name
    return (
        _BREVO_URL,
        {"api-key": settings.EMAIL_API_KEY, "accept": "application/json"},
        {
            "sender": sender_obj,
            "to": [{"email": recipient}],
            "subject": subject,
            "htmlContent": html_body,
            "textContent": _PLAIN_TEXT_FALLBACK,
        },
    )


async def _send_via_http_api(*, provider: str, recipients: list[str], subject: str, html_body: str) -> None:
    """
    الهدف:
    إرسال البريد عبر HTTP API لمزوّد (Resend/Brevo) بدل SMTP — لأن منافذ SMTP
    محجوبة على Render free (راجعي تحديث 2026-10-31 برأس الملف).

    المسؤولية:
    - رسالة منفصلة لكل مستلم (نفس عزل الخصوصية بمسار SMTP).
    - عميل HTTP واحد يُعاد استخدامه لكل الدفعة، بـtimeout=10 ثوانٍ.
    - إعادة محاولة واحدة لكل مستلم عند خطأ شبكة أو رد 429/5xx (أخطاء
      مؤقتة). ردود 4xx الأخرى (مفتاح خاطئ/مُرسِل غير مُوثَّق) لا تُعاد —
      إعادتها لن تنجح، وتُسجَّل مع نص رد المزوّد لتسهيل التشخيص.

    المدخلات: provider، recipients (غير فارغة)، subject، html_body.
    المخرجات: None.

    التأثيرات الجانبية: طلبات HTTPS خارجية. لا يرفع أي استثناء للمستدعي.
    """
    if not settings.EMAIL_API_KEY:
        logger.warning("EMAIL_API_KEY غير مُهيَّأ بـ.env (EMAIL_PROVIDER=%s) — تم تجاوز إرسال البريد: %s", provider, subject)
        return
    from_email = settings.SMTP_FROM_EMAIL
    if not from_email:
        logger.warning("SMTP_FROM_EMAIL مطلوب مع EMAIL_PROVIDER=%s — تم تجاوز إرسال البريد: %s", provider, subject)
        return

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        for recipient in recipients:
            url, headers, payload = _build_http_request(
                provider=provider,
                recipient=recipient,
                subject=subject,
                html_body=html_body,
                from_email=from_email,
                from_name=settings.SMTP_FROM_NAME,
            )
            for attempt in (1, 2):
                try:
                    response = await client.post(url, headers=headers, json=payload)
                except httpx.HTTPError:
                    logger.exception(
                        "خطأ شبكة أثناء إرسال بريد لـ %s عبر %s (محاولة %d، الموضوع: %s)",
                        recipient,
                        provider,
                        attempt,
                        subject,
                    )
                    continue
                if response.is_success:
                    break
                logger.error(
                    "رفض %s إرسال بريد لـ %s — HTTP %d: %s (محاولة %d، الموضوع: %s)",
                    provider,
                    recipient,
                    response.status_code,
                    response.text[:500],
                    attempt,
                    subject,
                )
                if response.status_code != 429 and response.status_code < 500:
                    break


async def _send_via_smtp(*, recipients: list[str], subject: str, html_body: str) -> None:
    """
    الهدف:
    مسار الإرسال الأصلي عبر SMTP (منقول كما هو من send_email قبل تحديث
    2026-10-31 بدون أي تغيير بالمنطق) — يُستخدم عند EMAIL_PROVIDER=smtp.

    المسؤولية:
    اتصال SMTP واحد لكل الدفعة، رسالة منفصلة لكل مستلم، وإعادة محاولة
    واحدة باتصال جديد عند الفشل (راجعي إصلاح 2026-09-13 أدناه).

    المدخلات: recipients (غير فارغة)، subject، html_body.
    المخرجات: None. لا يرفع أي استثناء للمستدعي.
    """
    if not settings.SMTP_HOST:
        # بيئة تطوير لم تُعبَّأ بيانات SMTP فيها بعد — نتجاوز الإرسال بصمت
        # (تحذير بالسجلات فقط) بدل رمي خطأ يُفشل إنشاء/تعديل/حذف الاجتماع.
        logger.warning("SMTP غير مُهيَّأ بـ.env — تم تجاوز إرسال البريد: %s", subject)
        return

    sender_email = settings.SMTP_FROM_EMAIL or settings.SMTP_USER
    from_header = f"{settings.SMTP_FROM_NAME} <{sender_email}>" if settings.SMTP_FROM_NAME else sender_email

    # تحديث 2026-09-10 (تشخيص بلاغ لاما — صفحة المحضر/الاجتماعات تعلّق
    # بالكامل بضع دقائق ثم ترجع، رغم تجربة NullPool وQueuePool معًا بدون
    # فرق حقيقي): تبيّن عبر فحص مباشر لـpg_stat_activity إن الجلسات
    # العالقة "idle in transaction"/"active" كانت بانتظار العميل (Python)
    # لا القاعدة (wait_event=ClientRead دائمًا) — يعني التعليق ليس بسبب
    # الـ Pool أو WebSocket إطلاقًا، بل كود الطلب نفسه ما يرجع يُغلق
    # جلسته. السبب: send_email تُستدعى دائمًا عبر BackgroundTasks (صح)،
    # لكن FastAPI توثّق رسميًا إن تنظيف Dependency ذات yield (get_db هنا)
    # ينتظر انتهاء BackgroundTasks أولًا قبل ما يُغلق الجلسة ويُعيدها
    # للـ Pool — فأي طلب ينشئ/يعدّل اجتماع أو طلب لجنة (كلها تُرسِل بريدًا)
    # يُبقي جلسته محجوزة طوال مدة محاولة الاتصال بسيرفر SMTP. وaiosmtplib
    # بلا timeout صريح هنا (الافتراضي 60 ثانية نظريًا، لكن معروف بتوثيقه
    # إنه لا يُطبَّق بشكل موثوق دائمًا على مرحلة connect() تحديدًا ببعض
    # الحالات الشبكية — راجعي github.com/cole/aiosmtplib/issues/50) —
    # فلو SMTP_HOST محجوب/غير قابل للوصول من شبكة الجهاز (شائع جدًا)،
    # الاتصال يعلّق لدقائق بدل ما يفشل بسرعة، ويسحب معه جلسة DB الطلب
    # الأصلي كامل هذي المدة. الحل هنا: timeout=10 صريح يجبر فشلًا سريعًا
    # بدل تعليق غير محدود — لا يحل مشكلة الشبكة نفسها إن كانت SMTP فعلًا
    # محجوبة، لكن يحدّ الضرر لـ١٠ ثوانٍ كحد أقصى بدل دقائق.
    def _build_message(recipient: str) -> EmailMessage:
        message = EmailMessage()
        message["From"] = from_header
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(_PLAIN_TEXT_FALLBACK)
        message.add_alternative(html_body, subtype="html")
        return message

    async def _connect() -> aiosmtplib.SMTP:
        smtp = aiosmtplib.SMTP(
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            start_tls=settings.SMTP_USE_TLS,
            timeout=10,
        )
        await smtp.connect()
        if settings.SMTP_USER:
            await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        return smtp

    try:
        smtp = await _connect()
    except Exception:
        logger.exception("فشل الاتصال بسيرفر SMTP — تم تجاوز إرسال البريد: %s", subject)
        return

    # إصلاح 2026-09-13 (بلاغ لاما — لايف: اجتماع بـ3 مستلمين، وصل البريد
    # فقط لأول واحد بالقائمة/منشئ الاجتماع، الباقي لم يصلهم شيء إطلاقًا):
    # الكود السابق كان يفتح اتصال SMTP واحد ويُعيد استخدامه لكل المستلمين
    # بحلقة try/except منفصلة لكل واحد — لكن لو مزوّد SMTP أسقط/رفض
    # الاتصال نفسه بعد أول رسالة (شائع مع Gmail/عدة مزوّدات: حد أقصى
    # لعدد الرسائل بلا إعادة تفاوض على نفس القناة، أو timeout قصير بين
    # الرسائل) — كل محاولات الإرسال التالية تفشل بصمت (استثناء مُسجَّل
    # بالسجلات فقط، لا يظهر لأحد بالواجهة، والعملية الأصلية لا تُفشَل
    # عمدًا). الحل: عند فشل إرسال لمستلم، نحاول مرة واحدة إضافية باتصال
    # SMTP جديد مستقل تمامًا قبل التسليم بالفشل لهذا المستلم تحديدًا —
    # يعالج انقطاع الاتصال منتصف الدفعة بلا تحويل التصميم بالكامل لاتصال
    # منفصل لكل رسالة (يبقى اتصال واحد يُعاد استخدامه بالمسار السعيد).
    try:
        for recipient in recipients:
            message = _build_message(recipient)
            try:
                await smtp.send_message(message)
                continue
            except Exception:
                logger.exception(
                    "فشل إرسال بريد لـ %s بالاتصال الحالي — إعادة محاولة باتصال جديد (الموضوع: %s)",
                    recipient,
                    subject,
                )
            try:
                await smtp.quit()
            except Exception:
                pass
            try:
                smtp = await _connect()
                await smtp.send_message(message)
            except Exception:
                logger.exception(
                    "فشل إرسال بريد إشعار لـ %s حتى بعد إعادة المحاولة (الموضوع: %s)", recipient, subject
                )
    finally:
        try:
            await smtp.quit()
        except Exception:
            pass
