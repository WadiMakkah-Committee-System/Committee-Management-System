"""
الهدف:
التخاطب مع Google Gemini API (REST مباشرة عبر httpx — بدون حزمة
google-generativeai كـ Dependency جديدة، بنفس فلسفة app/core/storage_client.py
مع Supabase) لتحويل تسجيل صوتي لاجتماع إلى مسودة (تفريغ نص + تمييز
متحدثين + ملخص + قرارات + مهام + نقاط مهمة) — راجعي رأس
db/migrations/0025_meeting_recordings_and_drafts.sql لقرار اختيار Gemini
(Free Tier، يقبل صوت مباشرة ويسوي التفريغ+التمييز+التلخيص بطلب واحد،
بخلاف OpenAI اللي يحتاج 3 خدمات منفصلة لنفس النتيجة).

المسؤولية:
- رفع الملف الصوتي لـGemini Files API (Resumable Upload) — إلزامي حتى
  للملفات الصغيرة هنا (وليس Inline base64) لأن تسجيلات الاجتماعات
  الرسمية غالبًا تتجاوز حد الـInline (~20MB) بسهولة (اجتماع 45+ دقيقة).
- استدعاء generateContent بالبرومت + الملف المرفوع، مع responseSchema
  يفرض JSON صارم (raise عند أي انحراف عن الشكل المتوقع — لا نحاول
  "نصلح" مخرجات ناقصة صامتًا).
- generate_meeting_draft(): الدالة العامة الوحيدة اللي تستخدمها طبقة
  الخدمة (meeting_draft_service.py) — تغلّف كل خطوات Files API أعلاه.

ملاحظات أمنية:
- GEMINI_API_KEY لا يصل للـFrontend أبدًا (نفس مبدأ AGORA_APP_CERTIFICATE/
  SUPABASE_SERVICE_ROLE_KEY) — كل الاستدعاء من الـBackend فقط.
- GeminiError عام تلتقطه طبقة الخدمة وتحوّله لحالة status='failed' بجدول
  meeting_drafts (مع error_message)، بدل تسريب تفاصيل الاستدعاء الخارجي
  للمستخدم مباشرة.
"""

import asyncio
import json
from typing import Literal

import httpx

from app.core.config import settings

_API_BASE = "https://generativelanguage.googleapis.com"
_UPLOAD_URL = f"{_API_BASE}/upload/v1beta/files"
_FILE_POLL_INTERVAL_SECONDS = 2
_FILE_POLL_MAX_ATTEMPTS = 30  # ~دقيقة كحد أقصى لانتظار معالجة جوجل للملف


class GeminiError(Exception):
    """خطأ عام أثناء التخاطب مع Gemini API (رفع/معالجة/توليد فشل)."""


class GeminiNotConfiguredError(GeminiError):
    """GEMINI_API_KEY غير مُعبّأ بالبيئة الحالية."""


def _require_api_key() -> str:
    if not settings.GEMINI_API_KEY:
        raise GeminiNotConfiguredError("إعدادات Gemini غير مكتملة (GEMINI_API_KEY)")
    return settings.GEMINI_API_KEY


# ============================== البرومت ==============================
# يُبنى ديناميكيًا لكل استدعاء (اسم الاجتماع + قائمة الحضور الفعليين —
# راجعي meeting_draft_service.py) عبر build_prompt() أدناه. القالب هنا
# ثابت وموثّق بالكامل — أي تعديل عليه يجب أن يبقى متوافقًا مع
# _RESPONSE_SCHEMA (الحقول/الأنواع يجب أن تتطابق تمامًا).
_PROMPT_TEMPLATE = """أنتِ مساعدة ذكاء اصطناعي متخصصة في تحليل تسجيلات اجتماعات اللجان الرسمية بالعربية.

سيُزوَّدك بملف صوتي كامل لاجتماع لجنة باسم: "{meeting_title}"

قائمة المشاركين المسجَّلين رسميًا بهذا الاجتماع (استخدميها لمطابقة الأصوات
بالأسماء الحقيقية):
{participant_list}

تعليمات مهمة لتحديد هوية المتحدث — اتبعيها بالترتيب قبل اليأس من التحديد:
أ) انتبهي لأي تعريف بالنفس ("أنا فلان...")، أو مخاطبة باسم صريح ("يا فلان
   وش رأيك؟"، "دور فلانة")، أو ذِكر منصب/دور يطابق أحد الأسماء بالقائمة —
   هذه أقوى دليل لمطابقة الصوت بالاسم.
ب) بمجرد ما تحددي هوية صوت معيّن بثقة معقولة (ولو بمقطع واحد فقط)، طبّقي
   نفس الاسم على كل المقاطع الأخرى بنفس الصوت طيلة التسجيل، حتى لو ما
   تكرر ذكر اسمه صراحة بها المقاطع — التمييز الصوتي المتصل عبر التسجيل
   دليل كافٍ، وليس فقط اللحظة اللي فيها ذُكر الاسم.
ج) لا تخمّني اسمًا من القائمة لصوت ما قدرتِ تربطينه بدليل معقول (سياق أو
   استمرارية صوتية) — الدقة أهم من التخمين.
د) إذا تعذّر تحديد الاسم الحقيقي لصوت معيّن، لا تستخدمي تسمية واحدة موحّدة
   لكل الأصوات غير المعروفة — بدّلي كل صوت غير معروف عن الثاني برقم تسلسلي
   يميّزهم عن بعض: "متحدث غير معروف 1"، "متحدث غير معروف 2"، وهكذا (نفس
   الرقم لنفس الصوت طيلة التسجيل، بنفس منطق البند ب).

مهمتك بالضبط:
1) فرّغي التسجيل كاملًا إلى نص عربي دقيق، مقسّمًا إلى مقاطع حسب المتحدث،
   مع وقت تقريبي بصيغة mm:ss لبداية كل مقطع.
2) لكل مقطع، حددي "من قاله" وفق تعليمات تحديد الهوية أعلاه.
3) اكتبي ملخصًا عامًا للاجتماع (3 إلى 6 جمل بالفصحى).
4) استخرجي كل قرار تم اتخاذه أو اقتراحه صراحة أثناء النقاش — نص القرار،
   من اقترحه إن اتضح من السياق (وإلا null)، وهل تمت الموافقة عليه لفظيًا
   بالاجتماع (true/false، أو null إن لم يتضح).
5) استخرجي كل مهمة أو إجراء تم تكليف شخص فيه صراحة — نص المهمة، اسم
   المسؤول عنها إن ذُكر (وإلا null)، وأي موعد نهائي إن ذُكر (وإلا null).
6) استخرجي أهم النقاط والملاحظات الجديرة بالإبراز بمحضر الاجتماع (نقاط
   قصيرة، كل نقطة جملة واحدة).
7) استخرجي كل "توصية" ذُكرت بالاجتماع — أي اقتراح رُفع لجهة أعلى (الإدارة
   العليا/مجلس الإدارة/لجنة أخرى) للنظر فيه، بدون أنه اتخذ كقرار نهائي
   بهذا الاجتماع نفسه (فرّقي بينها وبين "القرارات" بالبند 4 — القرار
   يعني موافقة/بتّ فعلي بنفس الاجتماع، التوصية تعني اقتراح مرفوع
   للاعتماد لاحقًا من جهة أخرى). لكل توصية: نص التوصية، ومن اقترحها إن
   اتضح (وإلا null).
8) استخرجي كل "نقطة معلّقة" أو "سؤال مفتوح" أُثير بالنقاش ولم يُحسم أو
   يُجب عليه صراحة أثناء الاجتماع (يحتاج متابعة أو رد لاحق). لكل نقطة:
   نصها، ومن أثارها إن اتضح (وإلا null).
9) بصفتك مساعدة لجنة حوكمة والتزام تحديدًا: استخرجي أي "ملاحظة أو مخاطرة
   متعلقة بالالتزام/الحوكمة" ذُكرت أثناء النقاش (مخالفة إجرائية، تأخر
   بمهمة رقابية، ثغرة بضبط داخلي، قضية امتثال تنظيمي، تعارض مصالح، أو ما
   شابه — فقط لو ذُكرت فعليًا، لا تستنتجي مخاطر من عندك). لكل ملاحظة:
   نصها، ومستوى خطورتها كما يظهر من سياق النقاش لو أمكن تقييمه بثقة
   معقولة (قيمة واحدة بالضبط من: "مرتفع" أو "متوسط" أو "منخفض"، وإلا
   null إن لم يتضح مستوى الخطورة من السياق).

قواعد صارمة وملزمة:
- لا تختلقي أي معلومة غير موجودة فعليًا بالتسجيل. الدقة أهم من الاكتمال.
- أي جزء من الصوت غير مفهوم أو غير واضح، اكتبي نص المقطع كـ"[غير مسموع]"
  بدل تخمين محتواه.
- لو التسجيل لا يحتوي أي قرارات أو مهام صريحة، أعيدي مصفوفة فارغة []
  لتلك الحقول — لا تخترعي محتوى لتعبئتها.
- حافظي على الفصحى بالملخص/القرارات/المهام/النقاط المهمة حتى لو كان
  الحديث الفعلي بالعامية؛ النص الكامل (full_transcript) ينقل الكلام كما
  قيل فعليًا (فصحى أو عامية، بلا تعديل).
- أعيدي المخرجات بصيغة JSON فقط، مطابقة تمامًا للـSchema المحدد بالطلب،
  بدون أي نص أو شرح خارج كائن الـJSON نفسه."""


def build_prompt(*, meeting_title: str, participant_names: list[str]) -> str:
    participant_list = (
        "\n".join(f"- {name}" for name in participant_names)
        if participant_names
        else "(لا توجد قائمة مشاركين مسجَّلة لهذا الاجتماع)"
    )
    return _PROMPT_TEMPLATE.format(meeting_title=meeting_title, participant_list=participant_list)


# مطابق تمامًا لأعمدة meeting_drafts (راجعي app/models/meeting_draft.py) —
# أي تعديل هنا يجب أن ينعكس هناك وبالعكس.
_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "full_transcript": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "speaker": {"type": "STRING"},
                    "start_time": {"type": "STRING"},
                    "text": {"type": "STRING"},
                },
                "required": ["speaker", "start_time", "text"],
            },
        },
        "summary": {"type": "STRING"},
        "decisions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING"},
                    "proposed_by": {"type": "STRING", "nullable": True},
                    "approved": {"type": "BOOLEAN", "nullable": True},
                },
                "required": ["text"],
            },
        },
        "action_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING"},
                    "assignee": {"type": "STRING", "nullable": True},
                    "due_date": {"type": "STRING", "nullable": True},
                },
                "required": ["text"],
            },
        },
        "key_points": {"type": "ARRAY", "items": {"type": "STRING"}},
        "recommendations": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING"},
                    "proposed_by": {"type": "STRING", "nullable": True},
                },
                "required": ["text"],
            },
        },
        "open_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING"},
                    "raised_by": {"type": "STRING", "nullable": True},
                },
                "required": ["text"],
            },
        },
        "compliance_notes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING"},
                    "severity": {"type": "STRING", "nullable": True},
                },
                "required": ["text"],
            },
        },
    },
    "required": [
        "full_transcript",
        "summary",
        "decisions",
        "action_items",
        "key_points",
        "recommendations",
        "open_items",
        "compliance_notes",
    ],
}


async def _upload_audio_file(client: httpx.AsyncClient, api_key: str, *, content: bytes, mime_type: str, display_name: str) -> str:
    """يرفع الملف عبر Files API (Resumable Upload، خطوتين) ويرجع file_uri."""
    start_response = await client.post(
        _UPLOAD_URL,
        params={"key": api_key},
        headers={
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(content)),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
        },
        json={"file": {"display_name": display_name}},
    )
    if start_response.status_code >= 400:
        raise GeminiError(f"فشل بدء رفع الملف الصوتي لـGemini: {start_response.status_code}")
    upload_url = start_response.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise GeminiError("Gemini لم يرجع رابط رفع صالح (X-Goog-Upload-URL مفقود)")

    upload_response = await client.post(
        upload_url,
        headers={
            "X-Goog-Upload-Command": "upload, finalize",
            "X-Goog-Upload-Offset": "0",
            "Content-Length": str(len(content)),
        },
        content=content,
    )
    if upload_response.status_code >= 400:
        raise GeminiError(f"فشل رفع محتوى الملف الصوتي لـGemini: {upload_response.status_code}")
    file_info = upload_response.json().get("file", {})
    file_uri = file_info.get("uri")
    file_name = file_info.get("name")
    if not file_uri or not file_name:
        raise GeminiError("استجابة رفع الملف من Gemini غير مكتملة")

    await _wait_until_active(client, api_key, file_name=file_name)
    return file_uri


async def _wait_until_active(client: httpx.AsyncClient, api_key: str, *, file_name: str) -> None:
    """الملفات الصوتية الطويلة تحتاج معالجة قصيرة (PROCESSING) قبل أن تصير
    قابلة للاستخدام (ACTIVE) — نستطلع الحالة بدل الاستدعاء الفوري."""
    for _ in range(_FILE_POLL_MAX_ATTEMPTS):
        status_response = await client.get(f"{_API_BASE}/v1beta/{file_name}", params={"key": api_key})
        if status_response.status_code >= 400:
            raise GeminiError(f"فشل التحقق من حالة معالجة الملف بـGemini: {status_response.status_code}")
        state = status_response.json().get("state")
        if state == "ACTIVE":
            return
        if state == "FAILED":
            raise GeminiError("فشلت معالجة الملف الصوتي من طرف Gemini")
        await asyncio.sleep(_FILE_POLL_INTERVAL_SECONDS)
    raise GeminiError("انتهت مهلة انتظار معالجة الملف الصوتي من طرف Gemini")



_GENERATE_RETRY_MAX_ATTEMPTS = 3
_GENERATE_RETRY_BASE_DELAY_SECONDS = 3


async def _generate_content_with_retry(
    client: httpx.AsyncClient, api_key: str, *, prompt: str, audio_mime_type: str, file_uri: str
) -> httpx.Response:
    """Gemini يرجّع أحيانًا 503 (UNAVAILABLE — ضغط مؤقت على الموديل) —
    إعادة محاولة قصيرة بتأخير متصاعد أفضل من فشل التوليد فورًا وإجبار
    المستخدم يضغط الزر يدويًا من جديد. أي status code ثاني (400/401/404...)
    يرجع فورًا بدون إعادة محاولة لأنه خطأ دائم مو مؤقت."""
    request_body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"file_data": {"mime_type": audio_mime_type, "file_uri": file_uri}},
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
        },
    }
    response: httpx.Response | None = None
    for attempt in range(_GENERATE_RETRY_MAX_ATTEMPTS):
        response = await client.post(
            f"{_API_BASE}/v1beta/models/{settings.GEMINI_MODEL}:generateContent",
            params={"key": api_key},
            json=request_body,
        )
        if response.status_code != 503:
            return response
        if attempt < _GENERATE_RETRY_MAX_ATTEMPTS - 1:
            await asyncio.sleep(_GENERATE_RETRY_BASE_DELAY_SECONDS * (2 ** attempt))
    return response



# ======================= استخراج بنود الاجتماع (FR-TASK-005) =======================
# استدعاء نصّي خفيف منفصل تمامًا عن generate_meeting_draft أعلاه — بدون
# رفع ملف صوتي، فقط نص ملخص الاجتماع الجاهز (مسودة مكتملة مسبقًا شرط
# مسبق بطبقة الخدمة، راجعي meeting_service.extract_meeting_items). لا
# تصنّف البنود كمهمة/قرار — هذا قرار بشري لاحق برئيس اللجنة (UC5/UC7).

_EXTRACT_ITEMS_PROMPT_TEMPLATE = """أنتِ مساعدة ذكاء اصطناعي تدعمين رئيس لجنة حوكمة والتزام رسمية.

فيما يلي ملخص اجتماع اللجنة:
---
{summary}
---

مهمتك: استخرجي من هذا الملخص فقط (بدون إضافة أي معلومة غير مذكورة فيه)
قائمة "بنود" — كل بند نقطة واحدة محددة ذُكرت بالملخص وتحتاج متابعة رسمية
من رئيس اللجنة، بحيث يمكن لاحقًا تحويلها إلى "مهمة" تُسند لمسؤول بموعد
محدد، أو "قرار" رسمي يُسجَّل ويُعتمَد.

قواعد صارمة وملزمة:
- كل بند نص قصير وواضح (جملة واحدة بحد أقصى)، بصياغة تصلح كعنوان مهمة
  أو قرار رسمي (مثال: "تحديث سياسة تعارض المصالح" — وليس فقرة سردية
  طويلة أو اقتباسًا حرفيًا من الحديث).
- لا تُصنّفي البند كـ"مهمة" أو "قرار" إطلاقًا، ولا تضيفي أي حقل غير
  النص نفسه — التصنيف قرار بشري لاحق برئيس اللجنة فقط.
- لا تكرري نفس البند بصياغتين مختلفتين.
- لو الملخص لا يحتوي أي نقطة تستحق متابعة رسمية (مهمة أو قرار)، أعيدي
  مصفوفة فارغة [] — لا تخترعي بنودًا لتعبئتها؛ الدقة أهم من الاكتمال.
- أعيدي المخرجات بصيغة JSON فقط، مطابقة تمامًا للـSchema المحدد بالطلب،
  بدون أي نص أو شرح خارج كائن الـJSON نفسه."""

_EXTRACT_ITEMS_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "items": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["items"],
}


async def _generate_text_only_with_retry(client: httpx.AsyncClient, api_key: str, *, prompt: str, response_schema: dict) -> httpx.Response:
    """نفس منطق إعادة المحاولة عند 503 بـ_generate_content_with_retry أعلاه،
    لكن بدون ملف مرفق (استدعاء نصّي بحت) — مفصولة لتفادي تعقيد التوقيع
    المشترك بين الحالتين (صوت+نص مقابل نص فقط)."""
    request_body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
        },
    }
    response: httpx.Response | None = None
    for attempt in range(_GENERATE_RETRY_MAX_ATTEMPTS):
        response = await client.post(
            f"{_API_BASE}/v1beta/models/{settings.GEMINI_MODEL}:generateContent",
            params={"key": api_key},
            json=request_body,
        )
        if response.status_code != 503:
            return response
        if attempt < _GENERATE_RETRY_MAX_ATTEMPTS - 1:
            await asyncio.sleep(_GENERATE_RETRY_BASE_DELAY_SECONDS * (2 ** attempt))
    return response


async def extract_meeting_items(*, summary: str) -> list[str]:
    """FR-TASK-005/UC2: تستخرج قائمة نصوص بنود من ملخص الاجتماع الجاهز.
    ترمي GeminiError عند أي فشل — نفس مبدأ generate_meeting_draft (الطبقة
    المستدعية بـmeeting_service مسؤولة عن التعامل مع الخطأ، بدون تسريب
    تفاصيل الاستدعاء الخارجي للمستخدم مباشرة)."""
    api_key = _require_api_key()
    prompt = _EXTRACT_ITEMS_PROMPT_TEMPLATE.format(summary=summary)

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await _generate_text_only_with_retry(
            client, api_key, prompt=prompt, response_schema=_EXTRACT_ITEMS_RESPONSE_SCHEMA
        )
    if response.status_code >= 400:
        raise GeminiError(f"فشل استدعاء Gemini لاستخراج بنود الاجتماع: {response.status_code} — {response.text[:300]}")

    body = response.json()
    try:
        raw_text = body["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(raw_text)
        items = parsed["items"]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise GeminiError("استجابة Gemini لا تطابق الشكل المتوقع") from exc

    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise GeminiError("استجابة Gemini لا تطابق الشكل المتوقع")

    return [item.strip() for item in items if item.strip()]


async def generate_meeting_draft(
    *, meeting_title: str, participant_names: list[str], audio_content: bytes, audio_mime_type: str, audio_file_name: str
) -> dict:
    """يرفع التسجيل، يستدعي Gemini، ويرجع dict مطابق تمامًا لـ_RESPONSE_SCHEMA
    (نفس مفاتيح أعمدة meeting_drafts). يرمي GeminiError عند أي فشل —
    الطبقة المستدعية (meeting_draft_service.generate_draft) مسؤولة عن
    حفظ status='failed' + error_message بدل السماح للاستثناء يتسرب للـAPI مباشرة."""
    api_key = _require_api_key()
    prompt = build_prompt(meeting_title=meeting_title, participant_names=participant_names)

    async with httpx.AsyncClient(timeout=180.0) as client:
        file_uri = await _upload_audio_file(
            client, api_key, content=audio_content, mime_type=audio_mime_type, display_name=audio_file_name
        )

        generate_response = await _generate_content_with_retry(
            client,
            api_key,
            prompt=prompt,
            audio_mime_type=audio_mime_type,
            file_uri=file_uri,
        )
    if generate_response.status_code >= 400:
        raise GeminiError(f"فشل استدعاء Gemini لتوليد المسودة: {generate_response.status_code} — {generate_response.text[:300]}")

    body = generate_response.json()
    try:
        raw_text = body["candidates"][0]["content"]["parts"][0]["text"]
        draft = json.loads(raw_text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise GeminiError("استجابة Gemini لا تطابق الشكل المتوقع") from exc

    missing = [field for field in _RESPONSE_SCHEMA["required"] if field not in draft]
    if missing:
        raise GeminiError(f"مخرجات Gemini ناقصة — الحقول المفقودة: {', '.join(missing)}")

    return draft

# ======================= البحث الذكي داخل الوثائق (البحث الدلالي + شات) =======================
# دالتان مستقلتان عن مسودة الاجتماع أعلاه، تُستخدَمان من
# app/services/document_embedding_service.py وapp/services/document_search_service.py
# (راجعي رأس db/migrations/0029_documents_semantic_search.sql للقرار الكامل).

_EMBEDDING_MODEL = "models/gemini-embedding-001"
# طول أقصى للنص المُرسَل لطلب الـembedding نفسه (وليس content_text
# المخزَّن — ذاك يُقتطع بحد أوسع بـtext_extraction.MAX_EXTRACTED_CHARS).
# gemini-embedding-001 له حد أقصى ~2048 توكن للمدخل؛ نقتطع بحرص أكبر
# (بالأحرف تقريبًا) بدل الاعتماد على تقدير توكنات دقيق.
_EMBEDDING_INPUT_MAX_CHARS = 8_000


async def embed_text(text: str, *, task_type: Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]) -> list[float]:
    """
    يحوّل نص إلى متجه 768 بُعد عبر Gemini Embedding API — يُستخدم مرتين
    بمنطق مختلف قليلًا (فرّقهما Google تحديدًا بـtaskType حتى تُعطي نتائج
    مقارنة أدق): RETRIEVAL_DOCUMENT وقت تخزين/فهرسة وثيقة،
    RETRIEVAL_QUERY وقت تحويل سؤال المستخدم بالبحث/الشات لنفس فضاء
    المقارنة. يرمي GeminiError عند أي فشل (نفس فلسفة بقية الدوال هنا —
    الطبقة المستدعية مسؤولة عن حالة failed بدل تسريب تفاصيل الاستدعاء
    الخارجي مباشرة)."""
    api_key = _require_api_key()
    trimmed = text.strip()[:_EMBEDDING_INPUT_MAX_CHARS]
    if not trimmed:
        raise GeminiError("لا يوجد نص فعلي لتوليد embedding له")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{_API_BASE}/v1beta/{_EMBEDDING_MODEL}:embedContent",
            params={"key": api_key},
            json={
                "model": _EMBEDDING_MODEL,
                "content": {"parts": [{"text": trimmed}]},
                "taskType": task_type,
                "outputDimensionality": 768,
            },
        )
    if response.status_code >= 400:
        raise GeminiError(f"فشل استدعاء Gemini لتوليد embedding: {response.status_code} — {response.text[:300]}")

    body = response.json()
    try:
        values = body["embedding"]["values"]
    except (KeyError, TypeError) as exc:
        raise GeminiError("استجابة Gemini لـembedding لا تطابق الشكل المتوقع") from exc
    if not isinstance(values, list) or len(values) != 768:
        raise GeminiError(f"طول متجه embedding غير متوقع من Gemini ({len(values) if isinstance(values, list) else 'N/A'})")
    return values


# طول أقصى لمحتوى كل وثيقة يُدرَج ضمن سياق سؤال الشات بوت (وليس
# content_text المخزَّن كاملًا) — يبقي حجم الطلب معقولًا لـgenerateContent
# حتى مع عدة وثائق بالشات العام دفعة واحدة.
_CHAT_CONTEXT_CHARS_PER_DOCUMENT = 6_000

_DOCUMENT_CHAT_PROMPT_TEMPLATE = """أنتِ مساعدة ذكاء اصطناعي تجاوبين على أسئلة موظفي الشركة اعتمادًا حصريًا
على محتوى الوثائق الرسمية المزوَّدة لك أدناه — ولا شيء غيرها.

سؤال المستخدم:
{question}

الوثائق المتاحة (كل وثيقة لها معرّف id وعنوان ومحتوى):
{documents_block}

قواعد صارمة وملزمة:
- جاوبي فقط بالاعتماد على محتوى الوثائق أعلاه — لا تستخدمي أي معلومة
  عامة من عندك ولا تخمّني.
- لو الإجابة غير موجودة صراحة أو ضمنيًا بأي من الوثائق المزوَّدة، قولي
  بوضوح إنك ما لقيتِ إجابة لهذا السؤال ضمن الوثائق المتاحة — لا تختلقي
  إجابة.
- اكتبي الإجابة بالعربية الفصحى الواضحة، مختصرة ومباشرة.
- أرجعي أيضًا قائمة معرّفات (id) الوثائق اللي فعليًا استخدمتِ محتواها
  لبناء الإجابة فقط (مصفوفة فارغة [] لو ما لقيتِ إجابة من أي وثيقة)."""

_DOCUMENT_CHAT_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "answer": {"type": "STRING"},
        "used_document_ids": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["answer", "used_document_ids"],
}


async def answer_from_documents(
    *, question: str, documents: list[dict[str, str]]
) -> dict:
    """
    RAG (استرجاع معزَّز بالتوليد): تجاوب على question بالاعتماد فقط على
    documents (كل عنصر {"document_id", "title", "content"}) — نفس الدالة
    تخدم شات "وثيقة واحدة مفتوحة" (documents بعنصر واحد) وشات "كل
    الوثائق" (عدة عناصر أعادها البحث الدلالي، راجعي
    document_search_service.semantic_search) بدون فرق بالمنطق، الفرق فقط
    بعدد العناصر الممرَّرة. ترمي GeminiError عند أي فشل."""
    api_key = _require_api_key()

    if not documents:
        return {"answer": "لا توجد وثائق متاحة للإجابة على سؤالك حاليًا.", "used_document_ids": []}

    documents_block = "\n\n".join(
        f"--- وثيقة id={doc['document_id']} — العنوان: {doc['title']} ---\n"
        f"{doc['content'][:_CHAT_CONTEXT_CHARS_PER_DOCUMENT]}"
        for doc in documents
    )
    prompt = _DOCUMENT_CHAT_PROMPT_TEMPLATE.format(question=question, documents_block=documents_block)

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await _generate_text_only_with_retry(
            client, api_key, prompt=prompt, response_schema=_DOCUMENT_CHAT_RESPONSE_SCHEMA
        )
    if response.status_code >= 400:
        raise GeminiError(f"فشل استدعاء Gemini لشات الوثائق: {response.status_code} — {response.text[:300]}")

    body = response.json()
    try:
        raw_text = body["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(raw_text)
        answer = parsed["answer"]
        used_document_ids = parsed["used_document_ids"]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise GeminiError("استجابة Gemini لشات الوثائق لا تطابق الشكل المتوقع") from exc

    if not isinstance(used_document_ids, list):
        used_document_ids = []
    return {"answer": answer, "used_document_ids": [str(i) for i in used_document_ids]}
