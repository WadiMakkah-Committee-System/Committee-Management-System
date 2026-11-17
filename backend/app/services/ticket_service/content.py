"""
الهدف:
التحقق من محتوى رسائل التذاكر ومرفقاتها قبل الحفظ (القسم 5 بالمواصفات).

المسؤولية:
- نص الرسالة: مستند TipTap يُتحقق منه بنفس القائمة البيضاء المعتمدة لمحرر
  المحاضر (minutes_general.editor_content.validate_editor_doc) — بدون أي
  HTML خام، فلا مجال لحقن سكربت. ثم يُستخرج منه نص مجرّد لفحص الطول.
- الحدود المعتمدة (2026-11-17): الوصف 10 إلى 5000 حرف، والرد حتى 5000
  ويصير فاضي لو معه مرفق.
- المرفقات: PNG/JPG/PDF/DOCX/XLSX، 5 كحد أقصى لكل رسالة، وحد الحجم
  MAX_DOCUMENT_UPLOAD_MB. النوع يُحدَّد من الامتداد ويُطابَق مع بصمة
  بداية الملف (magic bytes) — لا نثق بـContent-Type القادم من المتصفح.

الأخطاء: TicketValidationError برسالة عربية (400).
"""

import json
import os
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services.minutes_general.editor_content import EditorContentError, validate_editor_doc
from app.services.ticket_service.errors import TicketValidationError

TITLE_MIN = 5
TITLE_MAX = 150
DESCRIPTION_MIN = 10
BODY_MAX = 5000
MAX_ATTACHMENTS_PER_MESSAGE = 5

#: مستند فارغ — يُحفظ لرد فيه مرفقات فقط (القاعدة تشترط body_json من نوع doc).
EMPTY_DOC: dict[str, Any] = {"type": "doc", "content": []}

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_ZIP_MAGIC = b"PK\x03\x04"

#: الامتداد → (نوع الملف المحفوظ، بصمة بداية الملف). DOCX وXLSX حاويات ZIP.
_ALLOWED_FILES: dict[str, tuple[str, bytes]] = {
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".pdf": ("application/pdf", b"%PDF-"),
    ".docx": (_DOCX, _ZIP_MAGIC),
    ".xlsx": (_XLSX, _ZIP_MAGIC),
}


@dataclass(frozen=True)
class IncomingFile:
    """
    الهدف: ملف مرفوع بعد قراءته من الطلب (قبل التحقق).
    الحقول: file_name كما أرسله المتصفح، content بايتات الملف.
    """

    file_name: str
    content: bytes


@dataclass(frozen=True)
class ValidatedFile:
    """
    الهدف: مرفق اجتاز التحقق وجاهز للحفظ.
    الحقول: اسم الملف النظيف، نوعه المحدد من الامتداد، والمحتوى.
    """

    file_name: str
    mime_type: str
    content: bytes


def validate_title(raw: str) -> str:
    """
    الهدف: التحقق من عنوان التذكرة.
    المدخلات: raw — العنوان كما وصل. المخرجات: العنوان بعد حذف المسافات الطرفية.
    الأخطاء: TicketValidationError لو أقصر من 5 أو أطول من 150 حرف.
    """
    title = (raw or "").strip()
    if not TITLE_MIN <= len(title) <= TITLE_MAX:
        raise TicketValidationError(f"العنوان لازم يكون من {TITLE_MIN} إلى {TITLE_MAX} حرف")
    return title


def parse_body(raw: str | None) -> dict[str, Any] | None:
    """
    الهدف: قراءة نص الرسالة (JSON بصيغة TipTap كنص داخل حقل Form) والتحقق منه.

    المدخلات: raw — نص JSON أو فاضي.
    المخرجات: المستند النظيف، أو None لو فاضي فعليًا (بدون أي نص).
    الأخطاء: TicketValidationError لو الصيغة أو العناصر غير مقبولة.
    """
    if raw is None or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TicketValidationError("صيغة نص الرسالة غير صالحة") from exc
    try:
        return validate_editor_doc(value)
    except EditorContentError as exc:
        raise TicketValidationError(str(exc)) from exc


def plain_text(doc: dict[str, Any] | None) -> str:
    """
    الهدف: النص المجرّد من مستند TipTap — كل فقرة/عنصر قائمة بسطر.

    المدخلات: مستند نظيف أو None. المخرجات: نص بدون مسافات طرفية.
    يُحفظ بـbody_text (للطول والبحث) — لا يُعرض بدل المستند.
    """
    if not doc:
        return ""

    def walk(node: dict[str, Any]) -> str:
        node_type = node.get("type")
        if node_type == "text":
            return node.get("text", "")
        if node_type == "hardBreak":
            return "\n"
        parts = [walk(child) for child in node.get("content") or []]
        if node_type == "tableRow":
            return " | ".join(parts)
        if node_type in ("doc", "bulletList", "orderedList", "listItem", "table", "tableCell", "tableHeader"):
            return "\n".join(part for part in parts if part)
        return "".join(parts)

    return walk(doc).strip()


def validate_body(
    doc: dict[str, Any] | None, *, is_description: bool, has_attachments: bool
) -> tuple[dict[str, Any], str]:
    """
    الهدف: تطبيق حدود الطول على نص الرسالة.

    المدخلات:
    - doc: المستند النظيف من parse_body (أو None).
    - is_description: الوصف (أول رسالة) حدّه الأدنى 10 أحرف.
    - has_attachments: الرد بمرفق يصير بدون نص (قرار 2026-11-17).

    المخرجات: (المستند للحفظ، النص المجرّد).
    الأخطاء: TicketValidationError لو الطول خارج الحدود أو الرسالة فاضية بدون مرفق.
    """
    text = plain_text(doc)
    if len(text) > BODY_MAX:
        raise TicketValidationError(f"النص أطول من الحد المسموح ({BODY_MAX} حرف)")
    if is_description and len(text) < DESCRIPTION_MIN:
        raise TicketValidationError(f"الوصف لازم يكون {DESCRIPTION_MIN} أحرف على الأقل")
    if not text and not has_attachments:
        raise TicketValidationError("اكتب رسالة أو أرفق ملفًا")
    return (doc or EMPTY_DOC), text


def _clean_file_name(raw: str) -> str:
    """
    الهدف: اسم ملف آمن للعرض والتنزيل — بدون مسار، وحد أقصى 255 حرف مع
    الحفاظ على الامتداد. لا يدخل في مسار التخزين أصلًا (المسار UUID فقط).
    """
    name = os.path.basename((raw or "").replace("\\", "/")).strip().replace("\x00", "")
    if not name:
        name = "file"
    if len(name) > 255:
        stem, ext = os.path.splitext(name)
        name = stem[: 255 - len(ext)] + ext
    return name


def validate_files(files: list[IncomingFile]) -> list[ValidatedFile]:
    """
    الهدف: التحقق من مرفقات رسالة واحدة.

    قواعد العمل:
    - 5 ملفات كحد أقصى.
    - الامتداد من القائمة المسموحة، وبداية الملف تطابق نوعه فعلًا.
    - الملف مو فاضي، وحجمه ضمن MAX_DOCUMENT_UPLOAD_MB.

    المدخلات: الملفات بعد قراءتها من الطلب.
    المخرجات: الملفات المقبولة بنوعها المحدد من الخادم.
    الأخطاء: TicketValidationError برسالة تحدد الملف المرفوض.
    """
    if len(files) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise TicketValidationError(f"الحد الأقصى {MAX_ATTACHMENTS_PER_MESSAGE} مرفقات لكل رسالة")
    max_bytes = settings.MAX_DOCUMENT_UPLOAD_MB * 1024 * 1024
    validated: list[ValidatedFile] = []
    for incoming in files:
        name = _clean_file_name(incoming.file_name)
        ext = os.path.splitext(name)[1].lower()
        allowed = _ALLOWED_FILES.get(ext)
        if allowed is None:
            raise TicketValidationError(
                f"نوع الملف ({name}) غير مسموح — المسموح: PNG وJPG وPDF وDOCX وXLSX"
            )
        mime_type, magic = allowed
        if not incoming.content:
            raise TicketValidationError(f"الملف ({name}) فاضي")
        if len(incoming.content) > max_bytes:
            raise TicketValidationError(
                f"حجم الملف ({name}) يتجاوز الحد المسموح ({settings.MAX_DOCUMENT_UPLOAD_MB} ميجابايت)"
            )
        if not incoming.content.startswith(magic):
            raise TicketValidationError(f"محتوى الملف ({name}) لا يطابق امتداده")
        validated.append(ValidatedFile(file_name=name, mime_type=mime_type, content=incoming.content))
    return validated
