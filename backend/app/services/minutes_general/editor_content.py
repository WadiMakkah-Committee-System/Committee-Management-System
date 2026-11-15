"""
الهدف:
التحقق من محتوى "المحرر الغني" (الحيثيات، القرار، المناقشة، الفقرتان
اليدويتان) قبل حفظه في meeting_minutes.sections — المحتوى مستند JSON بصيغة
ProseMirror/TipTap: {"type": "doc", "content": [...]}.

المسؤولية:
- قائمة بيضاء صارمة لأنواع العناصر والتنسيقات والخصائص المسموحة: فقرات،
  عناوين، قوائم مرقمة ونقطية، جداول، سطر جديد، نص بتنسيق عريض/مائل/تسطير.
- إسقاط أي خاصية غير معروفة، ورفض أي عنصر/تنسيق غير مدعوم.
- حدود حجم (عمق، عدد عناصر، طول نص) تمنع إغراق القاعدة.

الأمان: المحتوى لا يُعرض أبدًا كـHTML خام — الواجهة ترسمه بالمحرر نفسه والـPDF
يرسمه عنصرًا عنصرًا — فلا مجال لحقن سكربت. القائمة البيضاء طبقة حماية إضافية.

الأخطاء: EditorContentError برسالة عربية واضحة (تُترجم لـ400 بطبقة الخدمة).
"""

from typing import Any

MAX_DEPTH = 30
MAX_NODES = 20_000
MAX_TEXT_CHARS = 200_000

_ALIGNMENTS = {None, "left", "right", "center", "justify"}
_MARKS = {"bold", "italic", "underline"}
_NODE_TYPES = {
    "doc",
    "paragraph",
    "heading",
    "bulletList",
    "orderedList",
    "listItem",
    "table",
    "tableRow",
    "tableHeader",
    "tableCell",
    "hardBreak",
    "text",
}


class EditorContentError(ValueError):
    """محتوى المحرر غير صالح — رسالة عربية جاهزة للعرض."""


def _clean_int(value: Any, *, low: int, high: int, field: str) -> int:
    """
    الهدف: التحقق من عدد صحيح ضمن نطاق.
    المخرجات: العدد. الأخطاء: EditorContentError لو ليس عددًا أو خارج النطاق.
    """
    if isinstance(value, bool) or not isinstance(value, int) or not (low <= value <= high):
        raise EditorContentError(f"قيمة غير صالحة في محتوى المحرر ({field})")
    return value


def _clean_attrs(node_type: str, attrs: Any) -> dict | None:
    """
    الهدف: إبقاء الخصائص المسموحة فقط لكل نوع عنصر وإسقاط الباقي.
    المدخلات: نوع العنصر، وقاموس الخصائص القادم من الواجهة.
    المخرجات: قاموس الخصائص النظيف، أو None لو لا خصائص.
    الأخطاء: EditorContentError لو قيمة خاصية مسموحة غير صالحة.
    """
    if not isinstance(attrs, dict):
        return None
    clean: dict[str, Any] = {}
    if node_type in ("paragraph", "heading") and "textAlign" in attrs:
        if attrs["textAlign"] not in _ALIGNMENTS:
            raise EditorContentError("محاذاة غير مدعومة في محتوى المحرر")
        if attrs["textAlign"] is not None:
            clean["textAlign"] = attrs["textAlign"]
    if node_type == "heading":
        clean["level"] = _clean_int(attrs.get("level", 2), low=1, high=3, field="level")
    if node_type == "orderedList" and attrs.get("start") is not None:
        clean["start"] = _clean_int(attrs["start"], low=0, high=100_000, field="start")
    if node_type in ("tableCell", "tableHeader"):
        if attrs.get("colspan") is not None:
            clean["colspan"] = _clean_int(attrs["colspan"], low=1, high=50, field="colspan")
        if attrs.get("rowspan") is not None:
            clean["rowspan"] = _clean_int(attrs["rowspan"], low=1, high=500, field="rowspan")
        widths = attrs.get("colwidth")
        if widths is not None:
            if not isinstance(widths, list) or len(widths) > 50:
                raise EditorContentError("عرض أعمدة غير صالح في جدول المحرر")
            clean["colwidth"] = [_clean_int(w, low=1, high=5000, field="colwidth") for w in widths]
    return clean or None


def validate_editor_doc(value: Any) -> dict | None:
    """
    الهدف: التحقق من مستند محرر كامل وتنظيفه قبل الحفظ.

    المدخلات: value — None (محتوى فارغ) أو {"type": "doc", "content": [...]}.
    المخرجات: نسخة نظيفة من المستند، أو None لو فارغ.
    الأخطاء: EditorContentError لو البنية/الأنواع/الحجم غير مقبولة.
    بلا تأثيرات جانبية (لا يعدّل المدخل).
    """
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("type") != "doc":
        raise EditorContentError("صيغة محتوى المحرر غير صالحة")

    counters = {"nodes": 0, "chars": 0}

    def clean_node(node: Any, depth: int) -> dict:
        if depth > MAX_DEPTH:
            raise EditorContentError("محتوى المحرر متداخل أكثر من اللازم")
        if not isinstance(node, dict):
            raise EditorContentError("صيغة محتوى المحرر غير صالحة")
        node_type = node.get("type")
        if node_type not in _NODE_TYPES:
            raise EditorContentError("محتوى المحرر يحتوي عناصر غير مدعومة")
        counters["nodes"] += 1
        if counters["nodes"] > MAX_NODES:
            raise EditorContentError("محتوى المحرر أكبر من الحد المسموح")

        out: dict[str, Any] = {"type": node_type}
        if node_type == "text":
            text = node.get("text")
            if not isinstance(text, str) or not text:
                raise EditorContentError("نص فارغ أو غير صالح في محتوى المحرر")
            counters["chars"] += len(text)
            if counters["chars"] > MAX_TEXT_CHARS:
                raise EditorContentError("نص المحرر أطول من الحد المسموح")
            out["text"] = text
            marks = node.get("marks")
            if marks:
                if not isinstance(marks, list):
                    raise EditorContentError("تنسيق غير صالح في محتوى المحرر")
                clean_marks = []
                for mark in marks:
                    mark_type = mark.get("type") if isinstance(mark, dict) else None
                    if mark_type not in _MARKS:
                        raise EditorContentError("تنسيق نص غير مدعوم في محتوى المحرر")
                    if {"type": mark_type} not in clean_marks:
                        clean_marks.append({"type": mark_type})
                out["marks"] = clean_marks
            return out

        attrs = _clean_attrs(node_type, node.get("attrs"))
        if attrs:
            out["attrs"] = attrs
        children = node.get("content")
        if children is not None:
            if not isinstance(children, list):
                raise EditorContentError("صيغة محتوى المحرر غير صالحة")
            out["content"] = [clean_node(child, depth + 1) for child in children]
        return out

    cleaned = clean_node(value, 0)
    return None if is_empty_doc(cleaned) else cleaned


def iter_text(node: dict | None):
    """
    الهدف: كل النصوص داخل مستند/عنصر محرر (بالترتيب).
    المدخلات: عنصر محرر أو None. المخرجات: مولّد نصوص.
    """
    if not node:
        return
    if node.get("type") == "text":
        yield node.get("text", "")
        return
    for child in node.get("content") or []:
        yield from iter_text(child)


def is_empty_doc(doc: dict | None) -> bool:
    """
    الهدف: هل المستند فارغ فعليًا (بلا أي نص ولا جدول)؟ — يُستخدم لقرار حذف
    موضوع لم يُكتب فيه شيء، ولعرض النص الإرشادي.
    """
    if not doc:
        return True
    if any(text.strip() for text in iter_text(doc)):
        return False

    def has_table(node: dict) -> bool:
        return node.get("type") == "table" or any(has_table(c) for c in node.get("content") or [])

    return not has_table(doc)
