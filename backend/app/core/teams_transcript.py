"""
الهدف:
تحويل تفريغ Microsoft Teams (صيغة WebVTT) إلى البنية المعتمدة بالنظام
لحقل meeting_drafts.full_transcript: [{speaker, start_time, text}] — نفس
بنية التفريغ الناتج من Gemini للتسجيل الصوتي، فتعرضه الواجهة بنفس المكوّن.

المسؤولية:
- parse_vtt: تحليل نص VTT واحد إلى مقاطع، مع دمج المقاطع المتتالية لنفس
  المتحدث (Teams يقسّم الكلام لمقاطع قصيرة جدًا كل بضع ثوانٍ).
- to_plain_text: تحويل المقاطع لنص مقروء يُرسَل لـGemini للتلخيص.

ملاحظات:
- دوال نقية بلا أي اتصال خارجي أو قاعدة بيانات — سهلة الاختبار.
- أسماء المتحدثين من Teams هي أسماء حساباتهم الرسمية (أدق من تخمين
  Gemini للأصوات)، فتُعتمد كما هي.

مثال على المدخل (من Graph):
    WEBVTT

    0f3a…/12-0
    00:00:03.120 --> 00:00:06.480
    <v لمى الجعيد>السلام عليكم، نبدأ الاجتماع.</v>
"""

import html
import re

_TIMESTAMP_RE = re.compile(r"^\s*(?P<start>[\d:.]+)\s*-->\s*[\d:.]+")
_VOICE_RE = re.compile(r"<v\s+([^>]+)>(.*?)(?:</v>|$)", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

UNKNOWN_SPEAKER = "متحدث غير معروف"


def _format_start(raw: str) -> str:
    """
    يحوّل توقيت VTT (hh:mm:ss.mmm أو mm:ss.mmm) إلى mm:ss — أو hh:mm:ss لو
    تجاوز الاجتماع ساعة — بنفس صيغة full_transcript الحالية.
    """
    parts = raw.split(".")[0].split(":")
    try:
        numbers = [int(p) for p in parts]
    except ValueError:
        return raw
    while len(numbers) < 3:
        numbers.insert(0, 0)
    hours, minutes, seconds = numbers[-3:]
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def parse_vtt(vtt: str) -> list[dict[str, str]]:
    """
    الهدف: تحليل تفريغ Teams إلى مقاطع منظّمة.

    المدخلات:
    - vtt: نص WebVTT كما أعاده Graph.

    المخرجات:
    - قائمة {speaker, start_time, text} بترتيب الكلام، مع دمج المقاطع
      المتتالية لنفس المتحدث في مقطع واحد (يبدأ بتوقيت أولها).

    قواعد:
    - مقطع بلا وسم <v اسم> يُنسب لـ"متحدث غير معروف" بدل تجاهله.
    - المقاطع الفارغة بعد إزالة الوسوم تُتجاهل.
    - رموز HTML (مثل &amp;) تُفك لنصها الأصلي.

    الأخطاء: لا ترمي — مدخل غير صالح ينتج قائمة فارغة (الطبقة المستدعية
    تتعامل مع القائمة الفارغة كـ"لا يوجد تفريغ").
    """
    entries: list[dict[str, str]] = []
    blocks = re.split(r"\r?\n\s*\r?\n", vtt.strip())
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        timestamp_index = next((i for i, line in enumerate(lines) if _TIMESTAMP_RE.match(line)), None)
        if timestamp_index is None:
            continue  # ترويسة WEBVTT أو NOTE أو كتلة غير مفهومة
        start = _format_start(_TIMESTAMP_RE.match(lines[timestamp_index]).group("start"))
        payload = "\n".join(lines[timestamp_index + 1 :])
        if not payload.strip():
            continue

        voice = _VOICE_RE.search(payload)
        if voice:
            speaker = voice.group(1).strip() or UNKNOWN_SPEAKER
            text = voice.group(2)
        else:
            speaker = UNKNOWN_SPEAKER
            text = payload
        text = html.unescape(_TAG_RE.sub("", text))
        text = " ".join(text.split())
        if not text:
            continue

        if entries and entries[-1]["speaker"] == speaker:
            entries[-1]["text"] = f"{entries[-1]['text']} {text}"
        else:
            entries.append({"speaker": speaker, "start_time": start, "text": text})
    return entries


def to_plain_text(entries: list[dict[str, str]]) -> str:
    """
    الهدف: تحويل المقاطع لنص سطري "[mm:ss] المتحدث: النص" يُرسل لـGemini.
    المدخلات: مخرجات parse_vtt (أو أكثر من تفريغ مدموج).
    المخرجات: نص واحد، سطر لكل مقطع.
    """
    return "\n".join(f"[{e['start_time']}] {e['speaker']}: {e['text']}" for e in entries)
