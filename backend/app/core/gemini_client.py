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
بالأسماء الحقيقية قدر استطاعتك؛ إذا لم تستطيعي تحديد المتحدث بثقة معقولة،
استخدمي القيمة "متحدث غير معروف" بالضبط — لا تخمّني اسمًا لست متأكدة منه):
{participant_list}

مهمتك بالضبط:
1) فرّغي التسجيل كاملًا إلى نص عربي دقيق، مقسّمًا إلى مقاطع حسب المتحدث،
   مع وقت تقريبي بصيغة mm:ss لبداية كل مقطع.
2) لكل مقطع، حددي "من قاله" (اسم من القائمة أعلاه، أو "متحدث غير معروف").
3) اكتبي ملخصًا عامًا للاجتماع (3 إلى 6 جمل بالفصحى).
4) استخرجي كل قرار تم اتخاذه أو اقتراحه صراحة أثناء النقاش — نص القرار،
   من اقترحه إن اتضح من السياق (وإلا null)، وهل تمت الموافقة عليه لفظيًا
   بالاجتماع (true/false، أو null إن لم يتضح).
5) استخرجي كل مهمة أو إجراء تم تكليف شخص فيه صراحة — نص المهمة، اسم
   المسؤول عنها إن ذُكر (وإلا null)، وأي موعد نهائي إن ذُكر (وإلا null).
6) استخرجي أهم النقاط والملاحظات الجديرة بالإبراز بمحضر الاجتماع (نقاط
   قصيرة، كل نقطة جملة واحدة).

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
    },
    "required": ["full_transcript", "summary", "decisions", "action_items", "key_points"],
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

        generate_response = await client.post(
            f"{_API_BASE}/v1beta/models/{settings.GEMINI_MODEL}:generateContent",
            params={"key": api_key},
            json={
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
            },
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
