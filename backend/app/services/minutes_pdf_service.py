"""
الهدف:
توليد ملف PDF لمحضر الاجتماع بالعربي (طلب لاما 2026-11-01 — تصنيف "مرفقات
اللجنة" بالوثائق: المحضر يظهر ضمن مرفقات الاجتماع كملف PDF للتحميل).

المسؤولية:
build_minutes_pdf() — يبني PDF من بيانات المحضر المخزّنة (أقسام نصية JSON +
التوقيعات) لحظة الطلب؛ لا يُخزَّن الملف (المحضر يتغير حتى اكتماله).

لماذا reportlab + arabic-reshaper + python-bidi (بموافقة لاما):
reportlab لا يشكّل الحروف العربية ولا يطبق اتجاه النص (Bidi) بنفسه —
arabic_reshaper يحوّل الحروف لأشكالها المتصلة (Presentation Forms)، وget_display
يرتبها بصريًا من اليمين لليسار. التفاف الأسطر يتم هنا على النص المنطقي
(قبل الترتيب البصري) ثم يُرتّب كل سطر على حدة — وإلا تنعكس ترتيبات الأسطر.

الخط: IBM Plex Sans Arabic (خط الهوية — ملف Wadi للألوان والخطوط) مضمّن
بـapp/assets/fonts (رخصة SIL OFL 1.1 — OFL.txt بنفس المجلد). الألوان من
ملف الهوية (الأزرق الرئيسي #105EA7).
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, Image, SimpleDocTemplate, Spacer, Table, TableStyle

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_FONT_REGULAR = "IBMPlexSansArabic"
_FONT_BOLD = "IBMPlexSansArabic-Bold"
_BRAND_BLUE = colors.HexColor("#105EA7")
_TEXT = colors.HexColor("#1F2937")
_MUTED = colors.HexColor("#6B7280")
_BORDER = colors.HexColor("#E5E7EB")
# السعودية بلا توقيت صيفي — إزاحة ثابتة +3 (لا تعتمد على قاعدة tz بالحاوية).
_RIYADH = timezone(timedelta(hours=3))

_STAGE_LABELS = {
    "none": "لم يبدأ",
    "preparing": "قيد الإعداد",
    "review": "قيد المراجعة",
    "approval": "قيد الاعتماد",
    "signature": "بانتظار التوقيع",
    "completed": "مكتمل",
}

_fonts_registered = False


def _register_fonts() -> None:
    """تسجيل الخط مرة واحدة لكل عملية (pdfmetrics سجل عام بالذاكرة)."""
    global _fonts_registered
    if _fonts_registered:
        return
    pdfmetrics.registerFont(TTFont(_FONT_REGULAR, str(_ASSETS / "fonts" / "IBMPlexSansArabic-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(_ASSETS / "fonts" / "IBMPlexSansArabic-Bold.ttf")))
    _fonts_registered = True


def _visual(text: str) -> str:
    """سطر منطقي واحد ← شكله البصري (حروف متصلة + ترتيب من اليمين لليسار)."""
    return get_display(arabic_reshaper.reshape(text))


def _width(text: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(arabic_reshaper.reshape(text), font, size)


def _wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    """
    التفاف النص على مستوى الكلمات بالترتيب المنطقي (قبل Bidi)، مع الحفاظ على
    الأسطر الفارغة المقصودة. كلمة أطول من السطر وحدها تُقسَّم بالأحرف.
    """
    lines: list[str] = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        words = raw.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            candidate = f"{current} {word}" if current else word
            if _width(candidate, font, size) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            while _width(word, font, size) > max_width and len(word) > 1:
                cut = len(word)
                while cut > 1 and _width(word[:cut], font, size) > max_width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        lines.append(current)
    return lines


class RTLText(Flowable):
    """
    فقرة عربية من اليمين لليسار — تلتف بالعرض المتاح وتنقسم بين الصفحات
    (split) بدل تجاوز الصفحة. color/size/font لكل الفقرة.
    """

    def __init__(
        self,
        text: str,
        *,
        font: str = _FONT_REGULAR,
        size: float = 11,
        color=_TEXT,
        leading: float | None = None,
        align: str = "right",
    ):
        super().__init__()
        self.text = text
        self.font = font
        self.size = size
        self.color = color
        self.leading = leading or size * 1.7
        self.align = align
        self._lines: list[str] = []

    def wrap(self, avail_width, avail_height):
        self.width = avail_width
        self._lines = _wrap(self.text, self.font, self.size, avail_width)
        self.height = max(len(self._lines), 1) * self.leading
        return self.width, self.height

    def split(self, avail_width, avail_height):
        lines = _wrap(self.text, self.font, self.size, avail_width)
        fit = int(avail_height // self.leading)
        if fit <= 0 or fit >= len(lines):
            return []
        head = RTLText("\n".join(lines[:fit]), font=self.font, size=self.size, color=self.color, leading=self.leading)
        tail = RTLText("\n".join(lines[fit:]), font=self.font, size=self.size, color=self.color, leading=self.leading)
        return [head, tail]

    def draw(self):
        canvas = self.canv
        canvas.setFont(self.font, self.size)
        canvas.setFillColor(self.color)
        y = self.height - self.size
        for line in self._lines:
            visual = _visual(line)
            if self.align == "center":
                canvas.drawCentredString(self.width / 2, y, visual)
            else:
                canvas.drawRightString(self.width, y, visual)
            y -= self.leading


class SectionHeading(Flowable):
    """عنوان قسم: نص عريض أزرق + خط فاصل خفيف تحته."""

    def __init__(self, text: str):
        super().__init__()
        self.text = text

    def wrap(self, avail_width, avail_height):
        self.width = avail_width
        self.height = 24
        return self.width, self.height

    def draw(self):
        canvas = self.canv
        canvas.setFont(_FONT_BOLD, 13)
        canvas.setFillColor(_BRAND_BLUE)
        canvas.drawRightString(self.width, 8, _visual(self.text))
        canvas.setStrokeColor(_BORDER)
        canvas.setLineWidth(0.6)
        canvas.line(0, 2, self.width, 2)


@dataclass
class MinutesPdfSignature:
    name: str
    signed_at: datetime | None
    image_base64: str | None


@dataclass
class MinutesPdfData:
    """بيانات المحضر اللازمة للـPDF — تُجمع بطبقة الخدمة (لا ORM هنا)."""

    committee_name: str
    meeting_title: str
    scheduled_at: datetime
    scheduled_end_at: datetime | None
    mode: str
    location: str | None
    stage: str
    participants: list[str]
    sections: list[dict]
    signatures: list[MinutesPdfSignature]


def _fmt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(_RIYADH).strftime("%Y-%m-%d — %H:%M")


def _signature_image(data_url: str | None, width: float, height: float):
    """صورة التوقيع (Base64 PNG، بعد data: أو بدونها) أو None لو غير صالحة."""
    if not data_url:
        return None
    try:
        raw = base64.b64decode(data_url.split(",", 1)[-1])
        reader = ImageReader(io.BytesIO(raw))
        iw, ih = reader.getSize()
        scale = min(width / iw, height / ih)
        return Image(io.BytesIO(raw), width=iw * scale, height=ih * scale)
    except Exception:  # noqa: BLE001 — توقيع تالف لا يُسقط المحضر كاملًا
        return None


def build_minutes_pdf(data: MinutesPdfData) -> bytes:
    """
    الهدف: PDF المحضر (A4، من اليمين لليسار).

    المحتوى: شعار وادي مكة + "محضر اجتماع" + بيانات الاجتماع (اللجنة، الموعد
    بتوقيت الرياض، النوع/المكان، حالة المحضر) + الحضور + أقسام المحضر بالترتيب
    + جدول التوقيعات (الاسم، وقت التوقيع، صورة التوقيع).

    المدخلات: MinutesPdfData. المخرجات: bytes ملف PDF.
    التأثيرات الجانبية: لا شيء (تسجيل الخط بالذاكرة أول مرة فقط).
    """
    _register_fonts()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"محضر اجتماع — {data.meeting_title}",
        author="نظام إدارة اللجان — شركة وادي مكة للتقنية",
    )

    story: list = []
    logo = _ASSETS / "wadi-makkah-mark.png"
    if logo.exists():
        story.append(Image(str(logo), width=28 * mm, height=28 * mm * 200 / 437, hAlign="RIGHT"))
        story.append(Spacer(1, 4))
    story.append(RTLText("محضر اجتماع", font=_FONT_BOLD, size=20, color=_BRAND_BLUE))
    story.append(RTLText(data.meeting_title, font=_FONT_BOLD, size=15))
    story.append(Spacer(1, 6))

    mode = "عن بُعد" if data.mode == "remote" else f"حضوري — {data.location or '—'}"
    details = [
        ("اللجنة", data.committee_name),
        ("الموعد", _fmt(data.scheduled_at) + (f"  إلى  {_fmt(data.scheduled_end_at)[-5:]}" if data.scheduled_end_at else "")),
        ("نوع الاجتماع", mode),
        ("حالة المحضر", _STAGE_LABELS.get(data.stage, data.stage)),
    ]
    for label, value in details:
        story.append(RTLText(f"{label}: {value}", size=10.5, color=_TEXT))
    story.append(Spacer(1, 8))

    if data.participants:
        story.append(SectionHeading("الحضور"))
        story.append(Spacer(1, 4))
        story.append(RTLText("، ".join(data.participants), size=10.5))
        story.append(Spacer(1, 10))

    sections = sorted(data.sections or [], key=lambda s: s.get("order", 0))
    if not sections:
        story.append(RTLText("لم تُكتب أقسام المحضر بعد.", size=11, color=_MUTED))
    for section in sections:
        story.append(SectionHeading(section.get("title") or "قسم"))
        story.append(Spacer(1, 4))
        body = (section.get("body") or "").strip()
        story.append(RTLText(body or "—", size=11, color=_TEXT if body else _MUTED))
        story.append(Spacer(1, 10))

    if data.signatures:
        story.append(SectionHeading("التوقيعات"))
        story.append(Spacer(1, 6))
        col_widths = [doc.width * 0.34, doc.width * 0.30, doc.width * 0.36]  # صورة، وقت، اسم (يمين)
        rows = [
            [
                RTLText("التوقيع", font=_FONT_BOLD, size=10, align="center"),
                RTLText("وقت التوقيع", font=_FONT_BOLD, size=10, align="center"),
                RTLText("الاسم", font=_FONT_BOLD, size=10),
            ]
        ]
        for sig in data.signatures:
            image = _signature_image(sig.image_base64, col_widths[0] - 8, 14 * mm)
            rows.append(
                [
                    image or RTLText("—" if sig.signed_at else "لم يوقّع بعد", size=9.5, color=_MUTED, align="center"),
                    RTLText(_fmt(sig.signed_at), size=9.5, align="center"),
                    RTLText(sig.name, size=10),
                ]
            )
        table = Table(rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, _BORDER),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F6FA")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 1), (0, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(table)

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont(_FONT_REGULAR, 8)
        canvas.setFillColor(_MUTED)
        canvas.drawRightString(
            doc_.pagesize[0] - doc_.rightMargin, 10 * mm, _visual("نظام إدارة اللجان — شركة وادي مكة للتقنية")
        )
        canvas.drawString(doc_.leftMargin, 10 * mm, f"{doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
