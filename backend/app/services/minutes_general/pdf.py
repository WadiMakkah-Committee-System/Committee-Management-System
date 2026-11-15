"""
الهدف:
ملف PDF لمحضر "القالب العام" بنفس شكل محضر وادي مكة المعتمد (طلب صاحب المشروع
2026-11-15: "أهم شيء شكله نفس اللي أرسلته"):
- ترويسة في كل صفحة: الشعار يسارًا، والتاريخ والمكان والزمان والموضوع يمينًا.
- تذييل في كل صفحة: شريط ألوان الهوية + عنوان الشركة والتواصل (صورة الورق
  الرسمي نفسها، مستخرجة من المحضر الأصلي) + رقم الصفحة بالوسط.
- العنوان وخط مزدوج، جداول الأعضاء والحاضرين والبنود برأس رمادي، المواضيع
  بعناوين عريضة تحتها خط، والتوقيعات بصفحة مستقلة (الرئيس آخر خانة بعرض كامل).

الخطوط: الأصل بخطوط Microsoft (Times New Roman/Sakkal Majalla) وهي غير قابلة
للتضمين، فالبديل الأقرب برخصة مفتوحة: Noto Naskh Arabic (OFL — app/assets/fonts)
للعربي، وTimes المدمج في PDF للحروف اللاتينية والأقواس والرموز.

التنفيذ: reportlab لا يشكّل العربي ولا يرتّبه، فنستخدم arabic-reshaper
وpython-bidi (نفس minutes_pdf_service). النص الغني (عريض/تسطير داخل السطر)
يُرسم مقطعًا مقطعًا من اليمين لليسار. المائل لا يظهر (لا يوجد خط عربي مائل).

بلا تأثيرات جانبية (تسجيل الخطوط بالذاكرة أول مرة فقط).
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    PageBreak,
    PageTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services import minutes_pdf_service
from app.services.minutes_general import sections as S
from app.services.minutes_general.editor_content import is_empty_doc

_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"
_FONT = "WMNaskhArabic"
_FONT_BOLD = "WMNaskhArabic-Bold"
_LATIN = "Times-Roman"
_LATIN_BOLD = "Times-Bold"
_FALLBACK = minutes_pdf_service._FONT_REGULAR
_FALLBACK_BOLD = minutes_pdf_service._FONT_BOLD

_BLACK = colors.black
_HEADER_GREY = colors.HexColor("#D9D9D9")
_CELL_GREY = colors.HexColor("#F2F2F2")

PAGE_W, PAGE_H = A4
_MARGIN_X = 25 * mm
_MARGIN_TOP = 42 * mm
_MARGIN_BOTTOM = 30 * mm

BODY_SIZE = 13
BODY_LEADING = 21
TABLE_SIZE = 11
TABLE_LEADING = 16

_state: dict = {"registered": False, "naskh": frozenset()}

# التشكيل (التنوين والحركات) يبقى — Noto Naskh يرسمه بمكانه الصحيح فوق الحرف
# ("مساءً"، "أولاً")، بخلاف الإعداد الافتراضي اللي يحذفه.
_RESHAPER = arabic_reshaper.ArabicReshaper(configuration={"delete_harakat": False})


def _register_fonts() -> None:
    """تسجيل خطوط الملف مرة واحدة (Naskh + Plex كاحتياط) وحفظ الحروف المتوفرة في Naskh."""
    if _state["registered"]:
        return
    minutes_pdf_service._register_fonts()
    regular = TTFont(_FONT, str(_ASSETS / "fonts" / "NotoNaskhArabic-Regular.ttf"))
    pdfmetrics.registerFont(regular)
    pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(_ASSETS / "fonts" / "NotoNaskhArabic-Bold.ttf")))
    _state["naskh"] = frozenset(regular.face.charToGlyph.keys())
    _state["registered"] = True


# ============================== رسم النص العربي ==============================


def _font_for(char: str, bold: bool) -> str:
    """الخط المناسب لحرف: Naskh للعربي، Times لما يقبله ترميز WinAnsi، وإلا Plex."""
    if char == " " or ord(char) in _state["naskh"]:
        return _FONT_BOLD if bold else _FONT
    try:
        char.encode("cp1252")
        return _LATIN_BOLD if bold else _LATIN
    except UnicodeEncodeError:
        return _FALLBACK_BOLD if bold else _FALLBACK


def _font_runs(text: str, bold: bool) -> list[tuple[str, str]]:
    """تقسيم نص (بصري) لمقاطع متتالية بنفس الخط: [(نص، خط)]."""
    runs: list[tuple[str, str]] = []
    for char in text:
        font = _font_for(char, bold)
        if runs and runs[-1][1] == font:
            runs[-1] = (runs[-1][0] + char, font)
        else:
            runs.append((char, font))
    return runs


def _shape(text: str, rtl: bool) -> str:
    """نص منطقي ← شكله البصري (حروف متصلة + ترتيب حسب اتجاه الفقرة)."""
    return get_display(_RESHAPER.reshape(text), base_dir="R" if rtl else "L")


def _width(text: str, bold: bool, size: float) -> float:
    """عرض نص (بعد التشكيل) بمجموع عرض مقاطعه بخطوطها."""
    shaped = _RESHAPER.reshape(text)
    return sum(pdfmetrics.stringWidth(t, f, size) for t, f in _font_runs(shaped, bold))


def _draw_visual(canvas, x_left: float, y: float, visual: str, bold: bool, size: float) -> float:
    """رسم نص بصري من اليسار، مقطعًا بخطه. المخرجات: العرض المرسوم."""
    x = x_left
    for text, font in _font_runs(visual, bold):
        canvas.setFont(font, size)
        canvas.drawString(x, y, text)
        x += pdfmetrics.stringWidth(text, font, size)
    return x - x_left


_STRONG_RTL = ("R", "AL")


def _is_rtl(text: str) -> bool:
    """
    اتجاه الفقرة من أول حرف قوي (عربي ⇒ يمين لليسار، لاتيني ⇒ يسار لليمين).
    بلا حروف قوية (أرقام فقط مثل "-2,796,978.43" أو "37%-") ⇒ يسار لليمين حتى
    تظهر الإشارة والنسبة بمكانها الصحيح — المحاذاة تبقى يمين كما هي.
    """
    for char in text:
        direction = unicodedata.bidirectional(char)
        if direction in _STRONG_RTL:
            return True
        if direction == "L":
            return False
    return False


@dataclass
class Seg:
    """مقطع نص بتنسيق واحد داخل سطر."""

    text: str
    bold: bool = False
    underline: bool = False


@dataclass
class _Line:
    segs: list[Seg] = field(default_factory=list)


_TOKEN = re.compile(r"\n|[^\S\n]+|[^\s]+")


def _wrap_segments(segs: list[Seg], size: float, max_width: float) -> list[_Line]:
    """
    الهدف: تقسيم مقاطع فقرة لأسطر بالعرض المتاح (على مستوى الكلمات، بالترتيب
    المنطقي قبل الترتيب البصري). "\\n" سطر جديد إجباري. الكلمة الأطول من السطر
    تُقسم بالأحرف.
    """
    lines: list[_Line] = [_Line()]
    current_width = 0.0
    for seg in segs:
        for token in _TOKEN.findall(seg.text):
            if token == "\n":
                lines.append(_Line())
                current_width = 0.0
                continue
            token_width = _width(token, seg.bold, size)
            if token.isspace():
                if lines[-1].segs:
                    lines[-1].segs.append(Seg(token, seg.bold, seg.underline))
                    current_width += token_width
                continue
            if current_width + token_width > max_width and lines[-1].segs:
                while lines[-1].segs and lines[-1].segs[-1].text.isspace():
                    lines[-1].segs.pop()
                lines.append(_Line())
                current_width = 0.0
            while token_width > max_width and len(token) > 1:
                cut = len(token)
                while cut > 1 and _width(token[:cut], seg.bold, size) > max_width:
                    cut -= 1
                lines[-1].segs.append(Seg(token[:cut], seg.bold, seg.underline))
                lines.append(_Line())
                token = token[cut:]
                token_width = _width(token, seg.bold, size)
            lines[-1].segs.append(Seg(token, seg.bold, seg.underline))
            current_width += token_width
    # دمج المقاطع المتتالية بنفس التنسيق (التشكيل الصحيح للكلمات المتجاورة).
    for line in lines:
        merged: list[Seg] = []
        for seg in line.segs:
            if merged and merged[-1].bold == seg.bold and merged[-1].underline == seg.underline:
                merged[-1] = Seg(merged[-1].text + seg.text, seg.bold, seg.underline)
            else:
                merged.append(Seg(seg.text, seg.bold, seg.underline))
        while merged and merged[-1].text.isspace():
            merged.pop()
        line.segs = merged
    return lines


def _draw_line(canvas, line: _Line, *, x0: float, width: float, y: float, size: float, align: str, rtl: bool) -> None:
    """
    رسم سطر واحد: المقاطع بالترتيب المنطقي من اليمين (الفقرة العربية) أو من
    اليسار (الإنجليزية)، كل مقطع بتشكيله وخطه، والتسطير تحت المقطع المسطّر.
    """
    pieces = [(seg, _shape(seg.text, rtl)) for seg in line.segs]
    widths = [_width(seg.text, seg.bold, size) for seg, _ in pieces]
    total = sum(widths)
    if align == "center":
        start_right = x0 + (width + total) / 2
        start_left = x0 + (width - total) / 2
    elif align == "left":
        start_right, start_left = x0 + total, x0
    else:
        start_right, start_left = x0 + width, x0 + width - total
    if rtl:
        x_right = start_right
        for (seg, visual), w in zip(pieces, widths, strict=True):
            _draw_visual(canvas, x_right - w, y, visual, seg.bold, size)
            if seg.underline:
                canvas.setLineWidth(0.7)
                canvas.line(x_right - w, y - 2.2, x_right, y - 2.2)
            x_right -= w
    else:
        x_left = start_left
        for (seg, visual), w in zip(pieces, widths, strict=True):
            _draw_visual(canvas, x_left, y, visual, seg.bold, size)
            if seg.underline:
                canvas.setLineWidth(0.7)
                canvas.line(x_left, y - 2.2, x_left + w, y - 2.2)
            x_left += w


class RichParagraph(Flowable):
    """
    الهدف: فقرة عربية (أو إنجليزية) بتنسيق داخل السطر (عريض/تسطير)، تلتف
    بالعرض المتاح وتنقسم بين الصفحات.

    المدخلات: segs (مقاطع)، size، leading، align (right/center/left)،
    indent (إزاحة من جهة بداية السطر — للقوائم).
    """

    def __init__(
        self,
        segs: list[Seg],
        *,
        size: float = BODY_SIZE,
        leading: float = BODY_LEADING,
        align: str = "right",
        indent: float = 0.0,
        space_after: float = 0.0,
    ):
        super().__init__()
        self.segs = segs
        self.size = size
        self.leading = leading
        self.align = align
        self.indent = indent
        self.space_after = space_after
        self.rtl = _is_rtl("".join(s.text for s in segs))
        self._lines: list[_Line] = []

    def _available(self, avail_width: float) -> float:
        return max(avail_width - self.indent, 20)

    def wrap(self, avail_width, avail_height):
        self.width = avail_width
        self._lines = _wrap_segments(self.segs, self.size, self._available(avail_width))
        self.height = len(self._lines) * self.leading + self.space_after
        return self.width, self.height

    def split(self, avail_width, avail_height):
        lines = _wrap_segments(self.segs, self.size, self._available(avail_width))
        fit = int(avail_height // self.leading)
        if fit <= 0 or fit >= len(lines):
            return []
        head = RichParagraph([], size=self.size, leading=self.leading, align=self.align, indent=self.indent)
        tail = RichParagraph(
            [], size=self.size, leading=self.leading, align=self.align, indent=self.indent,
            space_after=self.space_after,
        )
        head.segs = [s for ln in lines[:fit] for s in ln.segs + [Seg("\n")]][:-1]
        tail.segs = [s for ln in lines[fit:] for s in ln.segs + [Seg("\n")]][:-1]
        head.rtl = tail.rtl = self.rtl
        return [head, tail]

    def draw(self):
        canvas = self.canv
        canvas.setFillColor(_BLACK)
        canvas.setStrokeColor(_BLACK)
        avail = self._available(self.width)
        x0 = 0.0 if self.rtl else self.indent
        y = self.height - self.space_after - self.size
        for line in self._lines:
            _draw_line(canvas, line, x0=x0, width=avail, y=y, size=self.size, align=self.align, rtl=self.rtl)
            y -= self.leading


def _para(text: str, *, bold: bool = False, underline: bool = False, **kwargs) -> RichParagraph:
    """فقرة نص واحد بتنسيق واحد."""
    return RichParagraph([Seg(text, bold, underline)], **kwargs)


class DoubleRule(Flowable):
    """الخط المزدوج تحت العنوان (سميك ثم رفيع) — أعرض من الهوامش مثل الأصل."""

    def __init__(self, overhang: float = 10 * mm):
        super().__init__()
        self.overhang = overhang

    def wrap(self, avail_width, avail_height):
        self.width = avail_width
        self.height = 6
        return self.width, self.height

    def draw(self):
        canvas = self.canv
        canvas.setStrokeColor(_BLACK)
        canvas.setLineWidth(1.6)
        canvas.line(-self.overhang, 4.5, self.width + self.overhang, 4.5)
        canvas.setLineWidth(0.6)
        canvas.line(-self.overhang, 1.2, self.width + self.overhang, 1.2)


# ============================== محتوى المحرر الغني ==============================


def _inline_segs(node: dict) -> list[Seg]:
    """مقاطع النص داخل فقرة/عنوان (عريض/تسطير من التنسيقات، وسطر جديد)."""
    segs: list[Seg] = []
    for child in node.get("content") or []:
        if child.get("type") == "hardBreak":
            segs.append(Seg("\n"))
            continue
        if child.get("type") != "text":
            continue
        marks = {m.get("type") for m in child.get("marks") or []}
        segs.append(Seg(child.get("text", ""), "bold" in marks, "underline" in marks))
    return segs


def _align(node: dict) -> str:
    """محاذاة الفقرة من خصائصها (الافتراضي يمين — المضبوط يُعامل يمين)."""
    value = (node.get("attrs") or {}).get("textAlign")
    return {"center": "center", "left": "left"}.get(value, "right")


def _doc_flowables(doc: dict | None, *, size: float = BODY_SIZE, leading: float = BODY_LEADING) -> list:
    """
    الهدف: تحويل مستند المحرر الغني لعناصر PDF: فقرات، عناوين، قوائم مرقمة
    ونقطية (متداخلة)، وجداول (مع دمج الخلايا).
    المخرجات: قائمة flowables (فارغة لو المستند فارغ).
    """
    if is_empty_doc(doc):
        return []
    out: list = []

    def block(node: dict, *, indent: float, prefix: str | None) -> None:
        node_type = node.get("type")
        if node_type == "paragraph":
            segs = _inline_segs(node)
            if prefix:
                segs = [Seg(prefix)] + segs
            if not segs:
                out.append(Spacer(1, leading * 0.6))
                return
            out.append(RichParagraph(segs, size=size, leading=leading, align=_align(node), indent=indent))
        elif node_type == "heading":
            level = (node.get("attrs") or {}).get("level", 2)
            heading_size = {1: size + 3, 2: size + 1.5}.get(level, size + 0.5)
            segs = [Seg(s.text, True, s.underline) for s in _inline_segs(node)]
            if segs:
                out.append(
                    RichParagraph(segs, size=heading_size, leading=heading_size * 1.6, align=_align(node), indent=indent)
                )
        elif node_type in ("bulletList", "orderedList"):
            start = (node.get("attrs") or {}).get("start", 1) or 1
            for index, item in enumerate(node.get("content") or []):
                label = "• " if node_type == "bulletList" else f"{start + index}. "
                first = True
                for child in item.get("content") or []:
                    block(child, indent=indent + 7 * mm, prefix=label if first else None)
                    first = False
        elif node_type == "table":
            out.append(_editor_table(node, size=size - 1.5, leading=(size - 1.5) * 1.55))
            out.append(Spacer(1, 4))

    for child in (doc or {}).get("content") or []:
        block(child, indent=0.0, prefix=None)
    return out


def _editor_table(node: dict, *, size: float, leading: float) -> Table:
    """
    الهدف: جدول من المحرر الغني بعرض الصفحة — العمود الأول على اليمين (عربي)،
    رؤوس الأعمدة (tableHeader) عريضة برمادي، ودمج الخلايا (colspan/rowspan).
    """
    rows = [r for r in node.get("content") or [] if r.get("type") == "tableRow"]
    grid: dict[tuple[int, int], tuple[dict, int, int]] = {}
    occupied: set[tuple[int, int]] = set()
    n_cols = 0
    for r, row in enumerate(rows):
        c = 0
        for cell in row.get("content") or []:
            while (r, c) in occupied:
                c += 1
            attrs = cell.get("attrs") or {}
            colspan, rowspan = attrs.get("colspan", 1) or 1, attrs.get("rowspan", 1) or 1
            grid[(r, c)] = (cell, colspan, rowspan)
            for dr in range(rowspan):
                for dc in range(colspan):
                    occupied.add((r + dr, c + dc))
            c += colspan
            n_cols = max(n_cols, c)
    n_cols = max(n_cols, 1)
    data = [["" for _ in range(n_cols)] for _ in rows]
    style: list = [
        ("GRID", (0, 0), (-1, -1), 0.6, _BLACK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for (r, c), (cell, colspan, rowspan) in grid.items():
        mirrored = n_cols - c - colspan  # أول عمود منطقي = أقصى اليمين
        content = _doc_flowables({"type": "doc", "content": cell.get("content") or []}, size=size, leading=leading)
        if cell.get("type") == "tableHeader":
            for flowable in content:
                if isinstance(flowable, RichParagraph):
                    flowable.segs = [Seg(s.text, True, s.underline) for s in flowable.segs]
            style.append(("BACKGROUND", (mirrored, r), (mirrored + colspan - 1, r + rowspan - 1), _HEADER_GREY))
        data[r][mirrored] = content or ""
        if colspan > 1 or rowspan > 1:
            style.append(("SPAN", (mirrored, r), (mirrored + colspan - 1, r + rowspan - 1)))
    return Table(data, style=TableStyle(style), hAlign="CENTER")


# ============================== أقسام القالب ==============================


@dataclass
class GeneralMinutesPdfData:
    """
    بيانات PDF القالب العام (تُجمع بطبقة الخدمة — لا ORM هنا).
    - sections: أقسام المحضر (بعد آخر مزامنة).
    - signatures: user_id ← صورة التوقيع (data URL) أو None لو ما وقّع.
    """

    document_title: str
    sections: list[dict]
    signatures: dict[str, str | None] = field(default_factory=dict)


def _cell(text: str, *, bold: bool = False, align: str = "center") -> RichParagraph:
    """خلية جدول نصية."""
    return _para(text or "", bold=bold, size=TABLE_SIZE, leading=TABLE_LEADING, align=align)


def _people_table(rows: list[list], col_widths: list[float]) -> Table:
    """جدول أعضاء/حاضرين بشكل الأصل: رأس رمادي وحدود سوداء رفيعة."""
    table = Table(rows, colWidths=col_widths, repeatRows=1, hAlign="CENTER")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, _BLACK),
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_GREY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ]
        )
    )
    return table


def _members_flowables(section: dict, width: float) -> list:
    """جدول أعضاء اللجنة: م | اسم العضو | آلية الحضور | الصفة | الحالة (من اليمين)."""
    data = section.get("data") or {}
    rows = data.get("rows") or []
    out: list = []
    if data.get("caption"):
        out.append(_para(data["caption"], space_after=2))
    header = [_cell("الحالة"), _cell("الصفة"), _cell("آلية الحضور"), _cell("اسم العضو"), _cell("م")]
    body = [
        [
            _cell(row.get("status_label", "")),
            _cell(row.get("role_label", "")),
            _cell(row.get("mode_label", "")),
            _cell(row.get("name", ""), align="right"),
            _cell(f"{index}."),
        ]
        for index, row in enumerate(rows, start=1)
    ]
    widths = [0.15, 0.24, 0.16, 0.39, 0.06]
    out.append(_people_table([header] + body, [width * w for w in widths]))
    out.append(Spacer(1, 6))
    return out


def _guests_flowables(section: dict, width: float) -> list:
    """جدول "وقد حضر الاجتماع": م | الاسم | آلية الحضور | الصفة — يختفي إذا كان فارغًا."""
    data = section.get("data") or {}
    rows = data.get("rows") or []
    if not rows:
        return []
    out: list = []
    if data.get("caption"):
        out.append(_para(data["caption"], space_after=2))
    header = [_cell("الصفة"), _cell("آلية الحضور"), _cell("الاسم"), _cell("م")]
    body = [
        [
            _cell(row.get("role_label", "")),
            _cell(row.get("mode_label", "")),
            _cell(row.get("name", ""), align="right"),
            _cell(f"{index}."),
        ]
        for index, row in enumerate(rows, start=1)
    ]
    widths = [0.25, 0.17, 0.52, 0.06]
    out.append(_people_table([header] + body, [width * w for w in widths]))
    out.append(Spacer(1, 6))
    return out


def _agenda_flowables(section: dict, width: float) -> list:
    """جدول الأعمال: رقم الموضوع (يمين، عريض بخلفية رمادية) | البند."""
    data = section.get("data") or {}
    rows = data.get("rows") or []
    if not rows:
        return []
    out: list = []
    if data.get("caption"):
        out.append(_para(data["caption"], space_after=3))
    table_rows = [[_cell("البند"), _cell("رقم الموضوع")]] + [
        [_cell(row.get("title", ""), align="right"), _cell(row.get("ordinal_label", ""), bold=True)] for row in rows
    ]
    table = Table(table_rows, colWidths=[width * 0.78, width * 0.22], repeatRows=1, hAlign="CENTER")
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1.4, _BLACK),
                ("INNERGRID", (0, 0), (-1, -1), 0.6, _BLACK),
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_GREY),
                ("BACKGROUND", (1, 1), (1, -1), _CELL_GREY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    out += [table, Spacer(1, 10)]
    return out


def _discussion_flowables(section: dict, width: float) -> list:
    """مربع "مناقشة أعضاء اللجنة" الرمادي وتحته المحتوى (أو مساحة فاضية مثل الأصل)."""
    data = section.get("data") or {}
    box = Table(
        [[_para(data.get("heading") or S.DISCUSSION_HEADING, size=BODY_SIZE, leading=BODY_LEADING, align="center")]],
        colWidths=[width],
        hAlign="CENTER",
    )
    box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1.2, _BLACK),
                ("BACKGROUND", (0, 0), (-1, -1), _HEADER_GREY),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    content = _doc_flowables(data.get("content"))
    return [box, Spacer(1, 8)] + (content or [Spacer(1, 55 * mm)]) + [Spacer(1, 6)]


def _topic_flowables(section: dict) -> list:
    """موضوع: العنوان، "حيثيات الموضوع:" ومحتواها، "القرار (رقم):" ومحتواه — عناوين عريضة تحتها خط."""
    data = section.get("data") or {}
    # "مناقشة ... (مشاركة بالدخل)." ⇒ بدون النقطة قبل النقطتين، مثل الأصل.
    title = (data.get("heading") or "").rstrip(" .:،")
    heading = ": ".join(p for p in (data.get("ordinal_label", ""), title) if p) + ":"
    decision_title = f"{data.get('decision_label') or S.DECISION_LABEL} {data.get('decision_number', '')}:".strip()
    out: list = [
        Spacer(1, 6),
        _para(heading, bold=True, underline=True, size=14, leading=22),
        _para(data.get("background_label") or S.BACKGROUND_LABEL, bold=True, underline=True, size=14, leading=22),
    ]
    out += _doc_flowables(data.get("background")) or [Spacer(1, 10)]
    out.append(Spacer(1, 6))
    out.append(_para(decision_title, bold=True, underline=True, size=14, leading=22))
    out += _doc_flowables(data.get("decision")) or [Spacer(1, 10)]
    return out


def _closing_flowables(section: dict) -> list:
    """الختام: سطر انتهاء الاجتماع (عريض) ثم "وعلى ذلك جرى التوقيع،" بالوسط."""
    data = section.get("data") or {}
    out: list = [Spacer(1, 18)]
    if data.get("text"):
        out.append(_para(data["text"], bold=True, size=10.5, leading=17))
    if data.get("sign_off"):
        out.append(_para(data["sign_off"], bold=True, size=14, leading=22, align="center"))
    return out


def _signature_cell_label(row: dict) -> RichParagraph:
    """رأس خانة التوقيع: الاسم ثم (الصفة)، عريض بالوسط."""
    role = row.get("role_label", "")
    text = row.get("name", "") + (f"\n({role})" if role else "")
    return _para(text, bold=True, size=12, leading=19, align="center")


def _signature_image(image: str | None, width: float, height: float):
    """صورة التوقيع داخل الخانة، أو فراغ لو ما وقّع."""
    return minutes_pdf_service._signature_image(image, width, height) or ""


def _signatures_flowables(section: dict, signatures: dict[str, str | None], width: float) -> list:
    """
    صفحة التوقيعات: العنوان، ثم شبكة عمودين (الأول على اليمين)، والرئيس آخر
    خانة بعرض كامل — حدود خارجية سميكة مثل الأصل.
    """
    data = section.get("data") or {}
    rows = data.get("rows") or []
    if not rows:
        return []
    # الترتيب من المزامنة: الأعضاء ثم الرئيس آخرًا — الأخير بعرض كامل مثل الأصل.
    chair_row = rows[-1]
    others = rows[:-1]
    half = width / 2
    sig_h = 26 * mm
    table_rows: list[list] = []
    heights: list[float | None] = []
    style: list = [
        ("BOX", (0, 0), (-1, -1), 1.6, _BLACK),
        ("INNERGRID", (0, 0), (-1, -1), 0.8, _BLACK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for start in range(0, len(others), 2):
        pair = others[start : start + 2]
        right, left = pair[0], pair[1] if len(pair) > 1 else None
        table_rows.append([_signature_cell_label(left) if left else "", _signature_cell_label(right)])
        heights.append(None)
        table_rows.append(
            [
                _signature_image(signatures.get(left["key"]), half - 12, sig_h - 6) if left else "",
                _signature_image(signatures.get(right["key"]), half - 12, sig_h - 6),
            ]
        )
        heights.append(sig_h)
    label_index = len(table_rows)
    table_rows.append([_signature_cell_label(chair_row), ""])
    heights.append(None)
    table_rows.append([_signature_image(signatures.get(chair_row["key"]), width - 20, sig_h - 6), ""])
    heights.append(sig_h + 8 * mm)
    style.append(("SPAN", (0, label_index), (1, label_index)))
    style.append(("SPAN", (0, label_index + 1), (1, label_index + 1)))
    table = Table(table_rows, colWidths=[half, half], rowHeights=heights, hAlign="CENTER")
    table.setStyle(TableStyle(style))
    out: list = [PageBreak()]
    if data.get("heading"):
        out.append(_para(data["heading"], bold=True, underline=True, size=13, leading=21, align="center"))
    out += [Spacer(1, 22 * mm), table]
    return out


# ============================== الترويسة والتذييل ==============================


def _draw_header(canvas, header: dict) -> None:
    """الترويسة في كل صفحة: الشعار يسارًا، وأربعة أسطر يمينًا (عنوان عريض + قيمة)."""
    logo = _ASSETS / "letterhead" / "wadi-makkah-logo.png"
    logo_w = 22 * mm
    logo_h = logo_w * 129 / 169
    if logo.exists():
        canvas.drawImage(str(logo), 17 * mm, PAGE_H - 14 * mm - logo_h, logo_w, logo_h, mask="auto")
    right = PAGE_W - 15 * mm
    max_width = right - 48 * mm
    lines = [
        ("التاريخ: ", header.get("date_text", "")),
        ("المكان: ", header.get("place_text", "")),
        ("الزمان: ", header.get("time_text", "")),
        ("الموضوع: ", header.get("subject_text", "")),
    ]
    y = PAGE_H - 18 * mm
    for label, value in lines:
        size = 9.5
        while size > 7 and _width(label + value, False, size) > max_width:
            size -= 0.5
        wrapped = _wrap_segments([Seg(label, True), Seg(value)], size, max_width)[:2]
        for line in wrapped:
            _draw_line(canvas, line, x0=right - max_width, width=max_width, y=y, size=size, align="right", rtl=True)
            y -= 4.8 * mm


def _draw_footer(canvas, page_number: int) -> None:
    """التذييل في كل صفحة: صورة الورق الرسمي (شريط الألوان والعنوان) ورقم الصفحة بالوسط."""
    footer = _ASSETS / "letterhead" / "wadi-makkah-footer.png"
    footer_h = PAGE_W * 182 / 1692
    if footer.exists():
        canvas.drawImage(str(footer), 0, 2 * mm, PAGE_W, footer_h, mask="auto")
    canvas.setFont(_LATIN, 10)
    canvas.setFillColor(_BLACK)
    canvas.drawCentredString(PAGE_W / 2, 2 * mm + footer_h * 0.47, str(page_number))


# ============================== البناء ==============================


def build_general_minutes_pdf(data: GeneralMinutesPdfData) -> bytes:
    """
    الهدف: PDF محضر القالب العام بشكل المحضر الأصلي (A4، من اليمين لليسار).

    المدخلات: GeneralMinutesPdfData (الأقسام بعد المزامنة + صور التوقيعات).
    المخرجات: bytes ملف PDF.
    القواعد: الأقسام بترتيبها؛ الأقسام الفارغة (الفقرات اليدوية، جدول
    الحاضرين) لا تظهر؛ التوقيعات بصفحة مستقلة؛ قسم meta لا يظهر.
    """
    _register_fonts()
    sections = sorted(data.sections or [], key=lambda s: s.get("order", 0))
    header = next((s.get("data") or {} for s in sections if S.section_kind(s) == S.KIND_HEADER), {})

    buffer = io.BytesIO()
    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=_MARGIN_X,
        rightMargin=_MARGIN_X,
        topMargin=_MARGIN_TOP,
        bottomMargin=_MARGIN_BOTTOM,
        title=data.document_title,
        author="نظام إدارة اللجان — شركة وادي مكة للتقنية",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body", showBoundary=0)

    def on_page(canvas, doc_):
        canvas.saveState()
        _draw_header(canvas, header)
        _draw_footer(canvas, doc_.page)
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="letterhead", frames=[frame], onPage=on_page)])

    width = doc.width
    story: list = []
    for section in sections:
        kind = S.section_kind(section)
        section_data = section.get("data") or {}
        if kind == S.KIND_TITLE:
            story += [
                _para(section_data.get("line1", ""), bold=True, underline=True, size=15, leading=24, align="center"),
                _para(section_data.get("line2", ""), bold=True, size=13.5, leading=22, align="center"),
                Spacer(1, 6),
                DoubleRule(),
                Spacer(1, 10),
            ]
        elif kind == S.KIND_RICH:
            if section_data.get("role") == S.RICH_DISCUSSION:
                story += _discussion_flowables(section, width)
            else:
                if section_data.get("heading"):
                    story.append(_para(section_data["heading"], bold=True, underline=True, size=14, leading=22))
                story += _doc_flowables(section_data.get("content"))
                story.append(Spacer(1, 4))
        elif kind == S.KIND_MEMBERS:
            story += _members_flowables(section, width)
        elif kind == S.KIND_GUESTS:
            story += _guests_flowables(section, width)
        elif kind == S.KIND_AGENDA:
            story += _agenda_flowables(section, width)
        elif kind == S.KIND_TOPIC:
            story += _topic_flowables(section)
        elif kind == S.KIND_CLOSING:
            story += _closing_flowables(section)
        elif kind == S.KIND_SIGNATURES:
            story += _signatures_flowables(section, data.signatures, width)
        elif kind == S.KIND_TEXT:
            # قسم نصي يضيفه المستخدم يدويًا: عنوان عريض + نص.
            story.append(_para(section.get("title", ""), bold=True, underline=True, size=14, leading=22))
            if (section.get("body") or "").strip():
                story.append(_para(section["body"]))
    if not story:
        story.append(Spacer(1, 1))
    doc.build(story)
    return buffer.getvalue()
