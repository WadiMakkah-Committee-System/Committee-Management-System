"""
الهدف:
التخاطب مع Microsoft Graph API لإدارة اجتماعات Microsoft Teams الخاصة
بالاجتماعات عن بعد (mode='remote') — إنشاء/تعديل/حذف اجتماع Teams، وسحب
تفريغه النصي (Transcript) وتسجيله (Recording) بعد انتهائه.
راجعي db/migrations/0041_meetings_teams_integration.sql لقواعد العمل.

المسؤولية:
- الحصول على Access Token للتطبيق نفسه (Client Credentials — بلا تسجيل دخول
  مستخدم)، مع تخزينه مؤقتًا بالذاكرة حتى قرب انتهاء صلاحيته.
- عمليات Graph المطلوبة فقط، كل دالة تقابل استدعاءً واحدًا واضحًا.
- ترجمة أخطاء Graph/الشبكة إلى استثناءات هذه الوحدة (TeamsError وفروعها)
  بدل تسريب تفاصيل httpx للطبقات الأعلى.

الاعتماديات:
- httpx (موجودة أصلًا بالمشروع — نفس نمط storage_client.py، بلا حزمة
  msal جديدة: تدفق Client Credentials طلب POST واحد فقط).
- متغيرات البيئة TEAMS_TENANT_ID / TEAMS_CLIENT_ID / TEAMS_CLIENT_SECRET /
  TEAMS_ORGANIZER_EMAIL (app.core.config).

متطلبات خارج الكود (موثّقة، أُعدّت يدويًا 2026-10-31 → 2026-11-02):
- تسجيل تطبيق "Committee Management System" بـEntra ID بصلاحيات Application:
  OnlineMeetings.ReadWrite.All, OnlineMeetingTranscript.Read.All,
  OnlineMeetingRecording.Read.All, User.Read.All + Admin consent.
- Application Access Policy بـTeams PowerShell تسمح للتطبيق بالعمل باسم
  حساب المنظِّم — بدونها يرجع Graph 403 حتى مع الصلاحيات أعلاه.

ملاحظات أمنية:
- TEAMS_CLIENT_SECRET لا يصل للـFrontend أبدًا ولا يُسجَّل بأي رسالة خطأ.
- العميل (المتصفح) لا يكلّم Graph مطلقًا — كل شيء يمر عبر الباك-إند بعد
  فحص الصلاحيات بطبقة الخدمة.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from app.core.config import settings

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_LOGIN_BASE = "https://login.microsoftonline.com"
# هامش أمان قبل انتهاء صلاحية التوكن فعليًا — نطلب توكنًا جديدًا قبلها
# بدقيقة بدل المخاطرة باستخدام توكن ينتهي أثناء الطلب نفسه.
_TOKEN_REFRESH_MARGIN_SECONDS = 60
_REQUEST_TIMEOUT_SECONDS = 30.0
# Graph يرجع 429 (Throttling) أو 503/504 أحيانًا تحت الضغط — نعيد المحاولة
# مرتين بحد أقصى، باحترام Retry-After إن وُجد.
_RETRY_STATUSES = {429, 503, 504}
_MAX_RETRIES = 2


class TeamsError(Exception):
    """خطأ عام أثناء التخاطب مع Microsoft Graph — تُترجَم إلى 502 بطبقة الـAPI."""


class TeamsNotConfiguredError(TeamsError):
    """متغيرات TEAMS_* غير مكتملة بالبيئة — التكامل معطّل (راجعي is_configured)."""


class TeamsNotFoundError(TeamsError):
    """المورد غير موجود بـGraph (404) — مثلًا اجتماع حُذف من Teams مباشرة."""


@dataclass(frozen=True)
class TeamsParticipant:
    """مشارك يُضاف لاجتماع Teams: user_id = Object ID بـEntra، upn = البريد،
    role = 'coorganizer' (رئيس اللجنة) أو 'attendee' (بقية الأعضاء)."""

    user_id: str
    upn: str
    role: str


@dataclass(frozen=True)
class TeamsMeeting:
    """نتيجة إنشاء اجتماع Teams — تُخزَّن بأعمدة teams_* بجدول meetings."""

    meeting_id: str
    join_url: str


@dataclass(frozen=True)
class TeamsArtifact:
    """تفريغ أو تسجيل واحد لاجتماع Teams (قد يتعدد لو أُوقف واستؤنف)."""

    artifact_id: str
    created_at: datetime | None


# ============================== الإعدادات والتوكن ==============================

_token_cache: dict[str, object] = {"token": None, "expires_at": 0.0}


def is_configured() -> bool:
    """
    الهدف: معرفة هل تكامل Teams مفعّل بهذه البيئة.
    المخرجات: True لو كل متغيرات TEAMS_* الأربعة معبّأة.
    ملاحظة: بيئات التطوير بلا مفاتيح Teams تبقى تعمل (اجتماع remote يُنشأ
    بلا رابط Teams، فلا يمكن الانضمام له حتى تُعبَّأ المفاتيح) — نفس نمط
    التكاملات الاختيارية الأخرى بـconfig.py. متى ما عُبّئت المفاتيح يصبح التكامل
    إلزاميًا (فشل Graph = رفض إنشاء الاجتماع).
    """
    return all(
        (
            settings.TEAMS_TENANT_ID,
            settings.TEAMS_CLIENT_ID,
            settings.TEAMS_CLIENT_SECRET,
            settings.TEAMS_ORGANIZER_EMAIL,
        )
    )


def _require_config() -> None:
    """يرمي TeamsNotConfiguredError لو التكامل غير مهيّأ — تُستدعى أول كل
    عملية Graph عامة حتى لا يُرسَل أي طلب بإعدادات ناقصة."""
    if not is_configured():
        raise TeamsNotConfiguredError(
            "إعدادات Microsoft Teams غير مكتملة (TEAMS_TENANT_ID / TEAMS_CLIENT_ID / "
            "TEAMS_CLIENT_SECRET / TEAMS_ORGANIZER_EMAIL)"
        )


async def _get_access_token(client: httpx.AsyncClient, *, force_refresh: bool = False) -> str:
    """
    الهدف: الحصول على Access Token للتطبيق (OAuth2 Client Credentials).
    المدخلات: client مفتوح، force_refresh لتجاهل التوكن المخزّن (بعد 401).
    المخرجات: نص التوكن.
    التأثيرات الجانبية: يحدّث _token_cache بالذاكرة (مشترك بين الطلبات).
    الأخطاء: TeamsError لو رفضت مايكروسوفت المفاتيح (Secret خاطئ/منتهٍ).
    ملاحظة: لا قفل (Lock) عمدًا — طلبان متزامنان أول مرة قد يجلبان توكنين،
    وهذا غير ضار، بينما asyncio.Lock على مستوى الوحدة يرتبط بحلقة حدث واحدة
    ويكسر الاختبارات (حلقة جديدة لكل اختبار).
    """
    now = time.monotonic()
    cached = _token_cache.get("token")
    if not force_refresh and cached and float(_token_cache["expires_at"]) > now:
        return str(cached)

    try:
        response = await client.post(
            f"{_LOGIN_BASE}/{settings.TEAMS_TENANT_ID}/oauth2/v2.0/token",
            data={
                "client_id": settings.TEAMS_CLIENT_ID,
                "client_secret": settings.TEAMS_CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )
    except httpx.HTTPError as exc:
        raise TeamsError(f"تعذّر الاتصال بخدمة تسجيل الدخول لمايكروسوفت: {exc}") from exc
    if response.status_code >= 400:
        # لا نُدرج نص الاستجابة كاملًا — قد يحوي تفاصيل حساسة عن التطبيق.
        raise TeamsError(f"رفضت مايكروسوفت بيانات تطبيق Teams ({response.status_code}) — راجعي TEAMS_CLIENT_SECRET وصلاحيته")

    body = response.json()
    token = body["access_token"]
    expires_in = int(body.get("expires_in", 3600))
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + max(expires_in - _TOKEN_REFRESH_MARGIN_SECONDS, 0)
    return token


def _graph_error_message(response: httpx.Response) -> str:
    """يستخرج رسالة خطأ Graph المختصرة (code: message) للتشخيص بالسجلات."""
    try:
        error = response.json().get("error", {})
        return f"{error.get('code', '')}: {error.get('message', '')}"[:300]
    except ValueError:
        return response.text[:300]


async def _send(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    stream: bool = False,
) -> httpx.Response:
    """
    الهدف: تنفيذ طلب Graph واحد بالتوكن، مع إعادة المحاولة عند 429/503/504،
    وتجديد التوكن مرة واحدة عند 401.
    المدخلات: method/path (مسار نسبي لـ/v1.0)، json/params اختياريان، stream
    لقراءة الاستجابة تدريجيًا (ملفات التسجيل الكبيرة).
    المخرجات: الاستجابة الناجحة (< 400).
    الأخطاء: TeamsNotFoundError (404)، TeamsError (403 وأي خطأ آخر/شبكة).
    """
    token = await _get_access_token(client)
    refreshed = False
    attempt = 0
    while True:
        request = client.build_request(
            method,
            f"{_GRAPH_BASE}{path}",
            json=json,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            response = await client.send(request, stream=stream)
        except httpx.HTTPError as exc:
            raise TeamsError(f"تعذّر الاتصال بـMicrosoft Graph: {exc}") from exc

        if response.status_code == 401 and not refreshed:
            await response.aclose()
            token = await _get_access_token(client, force_refresh=True)
            refreshed = True
            continue
        if response.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
            await response.aclose()
            retry_after = response.headers.get("Retry-After", "")
            delay = float(retry_after) if retry_after.isdigit() else 2.0 * (attempt + 1)
            attempt += 1
            await asyncio.sleep(min(delay, 10.0))
            continue
        break

    if response.status_code < 400:
        return response

    if stream:
        await response.aread()
    message = _graph_error_message(response)
    await response.aclose()
    if response.status_code == 404:
        raise TeamsNotFoundError(f"المورد غير موجود في Microsoft Teams ({message})")
    if response.status_code == 403:
        raise TeamsError(
            "رفض Microsoft Graph الطلب (403) — تأكدي من موافقة المدير على صلاحيات التطبيق "
            f"ومن Application Access Policy لحساب المنظِّم ({message})"
        )
    raise TeamsError(f"فشل طلب Microsoft Graph ({response.status_code}): {message}")


def _client() -> httpx.AsyncClient:
    """عميل httpx جديد لكل عملية (نفس نمط storage_client.py) — مهلة 30 ثانية.
    يُستبدل بالاختبارات بعميل MockTransport (لا اتصال شبكة فعلي)."""
    # follow_redirects: محتوى التفريغ/التسجيل قد يُعاد كتحويل (302) لرابط
    # تحميل مؤقت. httpx يحذف ترويسة Authorization تلقائيًا عند التحويل
    # لنطاق مختلف، فلا يتسرب التوكن لخادم آخر.
    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS, follow_redirects=True)


def _meeting_path(organizer_id: str, meeting_id: str) -> str:
    """مسار اجتماع Teams بـGraph عبر منظِّمه — المعرّفات تُرمَّز (quote) لأن
    معرّف onlineMeeting يحوي رموزًا خاصة (base64)."""
    return f"/users/{quote(organizer_id)}/onlineMeetings/{quote(meeting_id, safe='')}"


def _parse_datetime(value: str | None) -> datetime | None:
    """يحوّل تاريخ Graph (ISO 8601 بلاحقة Z) لـdatetime، أو None لو فارغ/غير صالح."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso_utc(value: datetime) -> str:
    """يحوّل datetime (timezone-aware) لصيغة ISO بتوقيت UTC بلاحقة Z كما يطلب Graph."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


# ============================== المستخدمون ==============================


async def get_user_id(email: str) -> str | None:
    """
    الهدف: إيجاد Object ID لمستخدم بـEntra من بريده (UPN).
    المدخلات: email — بريد المستخدم بنظامنا (يُفترض مطابقته لبريد Microsoft 365).
    المخرجات: Object ID نصًا، أو None لو لا يوجد مستخدم بهذا البريد بالشركة
    (عضو خارجي مثلًا — يدخل الاجتماع كضيف عبر الرابط).
    الأخطاء: TeamsNotConfiguredError، TeamsError.
    الصلاحية المطلوبة بـGraph: User.Read.All.
    """
    _require_config()
    async with _client() as client:
        try:
            response = await _send(
                client, "GET", f"/users/{quote(email.strip(), safe='@')}", params={"$select": "id"}
            )
        except TeamsNotFoundError:
            return None
        return response.json()["id"]


async def get_organizer_id() -> str:
    """
    الهدف: Object ID لحساب المنظِّم المعرّف بـTEAMS_ORGANIZER_EMAIL.
    المخرجات: Object ID نصًا.
    الأخطاء: TeamsError لو البريد غير موجود بالشركة (إعداد خاطئ بالبيئة).
    """
    organizer_id = await get_user_id(settings.TEAMS_ORGANIZER_EMAIL)
    if organizer_id is None:
        raise TeamsError("حساب منظِّم اجتماعات Teams (TEAMS_ORGANIZER_EMAIL) غير موجود في Microsoft 365")
    return organizer_id


# ============================== الاجتماعات ==============================


def _meeting_body(
    *, subject: str, start: datetime, end: datetime, participants: list[TeamsParticipant] | None
) -> dict:
    """جسم onlineMeeting المشترك بين الإنشاء والتعديل.
    lobbyBypassSettings.scope='organization': موظفو الشركة يدخلون مباشرة،
    والضيوف من خارجها ينتظرون بالـLobby حتى يُدخلهم المنظِّم/الرئيس.
    recordAutomatically=True: التسجيل يبدأ تلقائيًا عند بداية الاجتماع —
    لأن من يدخل من المنصة (عبر ACS) لا يقدر يبدأ التسجيل/التفريغ يدويًا،
    والمسودة تعتمد على تفريغ Teams.
    participants=None ⇒ لا يُرسَل الحقل إطلاقًا (التعديل يُبقي المشاركين
    الحاليين كما هم) — بخلاف قائمة فارغة التي تحذفهم جميعًا."""
    body: dict = {
        "subject": subject,
        "startDateTime": _iso_utc(start),
        "endDateTime": _iso_utc(end),
        "lobbyBypassSettings": {"scope": "organization", "isDialInBypassEnabled": False},
        "recordAutomatically": True,
        "allowTranscription": True,
    }
    if participants is not None:
        body["participants"] = {
            "attendees": [
                {"upn": p.upn, "role": p.role, "identity": {"user": {"id": p.user_id}}}
                for p in participants
            ]
        }
    return body


async def create_online_meeting(
    *,
    organizer_id: str,
    subject: str,
    start: datetime,
    end: datetime,
    participants: list[TeamsParticipant],
) -> TeamsMeeting:
    """
    الهدف: إنشاء اجتماع Teams باسم حساب المنظِّم.
    المدخلات: organizer_id (Object ID)، subject (عنوان الاجتماع)، start/end
    (timezone-aware)، participants (رئيس اللجنة coorganizer + الأعضاء attendee).
    المخرجات: TeamsMeeting (المعرّف + رابط الانضمام).
    التأثيرات الجانبية: ينشئ اجتماعًا فعليًا بـTeams (لا يرسل دعوات تقويم).
    الأخطاء: TeamsNotConfiguredError، TeamsError (403 = Access Policy ناقصة).
    """
    _require_config()
    async with _client() as client:
        response = await _send(
            client,
            "POST",
            f"/users/{quote(organizer_id)}/onlineMeetings",
            json=_meeting_body(subject=subject, start=start, end=end, participants=participants),
        )
        body = response.json()
    join_url = body.get("joinWebUrl") or body.get("joinUrl")
    if not body.get("id") or not join_url:
        raise TeamsError("استجابة Microsoft Graph لإنشاء الاجتماع ناقصة (بلا معرّف أو رابط انضمام)")
    return TeamsMeeting(meeting_id=body["id"], join_url=join_url)


async def update_online_meeting(
    *,
    organizer_id: str,
    meeting_id: str,
    subject: str,
    start: datetime,
    end: datetime,
    participants: list[TeamsParticipant] | None,
) -> None:
    """
    الهدف: مزامنة بيانات اجتماع Teams قائم بعد تعديل الاجتماع بنظامنا
    (العنوان/الموعد/المشاركون).
    المدخلات: organizer_id المحفوظ وقت الإنشاء (وليس الإعداد الحالي)، meeting_id،
    participants (None ⇒ يبقى المشاركون الحاليون كما هم، مثلًا عند التمديد).
    التأثيرات الجانبية: PATCH فعلي على اجتماع Teams.
    الأخطاء: TeamsNotFoundError (حُذف من Teams مباشرة)، TeamsError.
    """
    _require_config()
    async with _client() as client:
        await _send(
            client,
            "PATCH",
            _meeting_path(organizer_id, meeting_id),
            json=_meeting_body(subject=subject, start=start, end=end, participants=participants),
        )


async def delete_online_meeting(*, organizer_id: str, meeting_id: str) -> None:
    """
    الهدف: حذف اجتماع Teams (عند حذف الاجتماع أو تحويله لحضوري).
    التأثيرات الجانبية: DELETE فعلي — رابط الانضمام يتوقف عن العمل.
    ملاحظة: 404 يُعامل كنجاح (الاجتماع محذوف أصلًا) — العملية idempotent.
    الأخطاء: TeamsError لأي فشل آخر.
    """
    _require_config()
    async with _client() as client:
        try:
            await _send(client, "DELETE", _meeting_path(organizer_id, meeting_id))
        except TeamsNotFoundError:
            return


# ============================== التفريغ والتسجيل ==============================


async def _list_artifacts(organizer_id: str, meeting_id: str, kind: str) -> list[TeamsArtifact]:
    """
    منطق مشترك لـlist_transcripts/list_recordings: kind = 'transcripts' أو
    'recordings'. المخرجات مرتبة زمنيًا تصاعديًا (الأقدم أولًا)، والعناصر
    بلا تاريخ تأتي أولًا.
    """
    _require_config()
    async with _client() as client:
        response = await _send(client, "GET", f"{_meeting_path(organizer_id, meeting_id)}/{kind}")
        items = response.json().get("value", [])
    artifacts = [
        TeamsArtifact(artifact_id=item["id"], created_at=_parse_datetime(item.get("createdDateTime")))
        for item in items
        if item.get("id")
    ]
    return sorted(artifacts, key=lambda a: a.created_at or datetime.min.replace(tzinfo=UTC))


async def list_transcripts(*, organizer_id: str, meeting_id: str) -> list[TeamsArtifact]:
    """
    الهدف: كل تفريغات اجتماع Teams مرتبة زمنيًا (قد تتعدد لو أُوقف التفريغ واستؤنف).
    المخرجات: قائمة (قد تكون فارغة لو لم يُشغَّل التفريغ أصلًا، أو لم يجهز بعد —
    يجهز عادة خلال دقائق من انتهاء الاجتماع).
    الصلاحية المطلوبة بـGraph: OnlineMeetingTranscript.Read.All.
    """
    return await _list_artifacts(organizer_id, meeting_id, "transcripts")


async def get_transcript_vtt(*, organizer_id: str, meeting_id: str, transcript_id: str) -> str:
    """
    الهدف: محتوى تفريغ واحد بصيغة WebVTT (نص بأسماء المتحدثين وتوقيتاتهم).
    المخرجات: نص VTT كما هو — يُحلَّل بـapp.core.teams_transcript.
    """
    _require_config()
    async with _client() as client:
        response = await _send(
            client,
            "GET",
            f"{_meeting_path(organizer_id, meeting_id)}/transcripts/{quote(transcript_id, safe='')}/content",
            params={"$format": "text/vtt"},
        )
        return response.text


async def list_recordings(*, organizer_id: str, meeting_id: str) -> list[TeamsArtifact]:
    """
    الهدف: كل تسجيلات اجتماع Teams مرتبة زمنيًا.
    الصلاحية المطلوبة بـGraph: OnlineMeetingRecording.Read.All.
    ملاحظة: Teams يحذف التسجيلات تلقائيًا بعد مدة سياسة الشركة (120 يومًا
    حاليًا) — بعدها ترجع القائمة فارغة.
    """
    return await _list_artifacts(organizer_id, meeting_id, "recordings")


@dataclass
class RecordingStream:
    """ملف تسجيل مفتوح للقراءة التدريجية — يُمرَّر لـStreamingResponse.
    chunks يغلق الاتصال بنفسه عند الانتهاء (أو عند انقطاع العميل)."""

    content_type: str
    content_length: str | None
    chunks: AsyncIterator[bytes]


async def open_recording_stream(*, organizer_id: str, meeting_id: str, recording_id: str) -> RecordingStream:
    """
    الهدف: فتح ملف تسجيل Teams للبث التدريجي عبر الباك-إند (بلا تخزين نسخة
    عندنا، وبلا تحميل الملف كاملًا بالذاكرة — قد يبلغ مئات الميجابايت).
    المخرجات: RecordingStream — الحالة تُفحص قبل الإرجاع، فأي خطأ (404/403)
    يظهر كاستثناء قبل بدء إرسال الاستجابة للمستخدم.
    التأثيرات الجانبية: يفتح اتصالًا يبقى مفتوحًا حتى نهاية البث.
    الأخطاء: TeamsNotFoundError، TeamsError.
    """
    _require_config()
    client = _client()
    try:
        response = await _send(
            client,
            "GET",
            f"{_meeting_path(organizer_id, meeting_id)}/recordings/{quote(recording_id, safe='')}/content",
            stream=True,
        )
    except BaseException:
        await client.aclose()
        raise

    async def _iterate() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return RecordingStream(
        content_type=response.headers.get("Content-Type", "video/mp4"),
        content_length=response.headers.get("Content-Length"),
        chunks=_iterate(),
    )
