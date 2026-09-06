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
"""

import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_email(*, to: list[str], subject: str, html_body: str) -> None:
    """
    يرسل نفس الرسالة (subject/html_body) لكل عنوان بـ`to` كرسالة منفصلة —
    عزل الخصوصية بين المستلمين (لا يرى عضو باقي عناوين أعضاء اللجنة بحقل
    To/Cc)، عبر اتصال SMTP واحد فقط لكل الدفعة.
    """
    recipients = [addr for addr in to if addr]
    if not recipients:
        return

    if not settings.SMTP_HOST:
        # بيئة تطوير لم تُعبَّأ بيانات SMTP فيها بعد — نتجاوز الإرسال بصمت
        # (تحذير بالسجلات فقط) بدل رمي خطأ يُفشل إنشاء/تعديل/حذف الاجتماع.
        logger.warning("SMTP غير مُهيَّأ بـ.env — تم تجاوز إرسال البريد: %s", subject)
        return

    sender_email = settings.SMTP_FROM_EMAIL or settings.SMTP_USER
    from_header = f"{settings.SMTP_FROM_NAME} <{sender_email}>" if settings.SMTP_FROM_NAME else sender_email

    try:
        async with aiosmtplib.SMTP(
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            start_tls=settings.SMTP_USE_TLS,
        ) as smtp:
            if settings.SMTP_USER:
                await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)

            for recipient in recipients:
                message = EmailMessage()
                message["From"] = from_header
                message["To"] = recipient
                message["Subject"] = subject
                message.set_content("هذه الرسالة بصيغة HTML — افتحيها بعارض بريد يدعم HTML.")
                message.add_alternative(html_body, subtype="html")
                try:
                    await smtp.send_message(message)
                except Exception:
                    logger.exception("فشل إرسال بريد إشعار لـ %s (الموضوع: %s)", recipient, subject)
    except Exception:
        logger.exception("فشل الاتصال بسيرفر SMTP — تم تجاوز إرسال البريد: %s", subject)
