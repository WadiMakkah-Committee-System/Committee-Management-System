"""
الهدف:
منطق أقسام "القالب العام" للمحاضر داخل meeting_minutes.sections (JSONB):
البناء الأولي، والمزامنة مع بيانات الاجتماع، ودمج تعديلات المستخدم.
المواصفات: مستند المشروع minutes_template_spec.md، والتصميم:
docs/minutes-official-template.md.

المسؤولية (دوال نقية — بلا قاعدة بيانات ولا تأثيرات جانبية):
- build_skeleton: هيكل القالب الفارغ بالترتيب المعتمد.
- sync_sections: تعبئة/تحديث الأجزاء التلقائية من MeetingSnapshot.
- merge_user_section / merge_user_sections: دمج تعديل المستخدم مع المخزَّن.

قواعد العمل الأساسية:
1) كل قسم له kind. الأقسام القديمة بلا kind تُعامل "text" (لا تتأثر).
2) الحقول التلقائية تتزامن مع الاجتماع إلى أن يعدّلها المستخدم يدويًا —
   أي حقل يتغيّر بتعديل يدوي يُضاف لـlocked ولا تلمسه المزامنة بعدها (على
   مستوى الخانة في صفوف الجداول).
3) صف تلقائي يحذفه المستخدم يُسجَّل في removed_keys فلا تعيده المزامنة،
   وموضوع تلقائي يُحذف يُسجَّل في قسم meta (removed_topic_keys).
4) لكل قسم رقم مراجعة rev — يزيد مع كل تغيير (من المستخدم أو المزامنة)،
   والتعديل بنسخة قديمة يُرفض (409) حتى لا يُكتب فوق تغيير أحدث بالغلط.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.services.minutes_general import formatting
from app.services.minutes_general.editor_content import (
    EditorContentError,
    is_empty_doc,
    validate_editor_doc,
)

TEMPLATE_ID = "general"
TEMPLATE_NAME = "القالب العام"
TEMPLATE_DESCRIPTION = (
    "قالب المحضر المعتمد بشكل محضر وادي مكة: ترويسة بالتاريخ والمكان والزمان، جدولا الأعضاء "
    "والحاضرين، جدول الأعمال، قسم لكل موضوع بحيثياته وقراره المرقّم، والتوقيعات — يتعبّأ "
    "تلقائيًا من بيانات الاجتماع ويتزامن معها، وكل شيء فيه قابل للتعديل."
)

# ============================== أنواع الأقسام ==============================
KIND_TEXT = "text"
KIND_HEADER = "header"
KIND_TITLE = "title"
KIND_RICH = "rich"
KIND_MEMBERS = "members_table"
KIND_GUESTS = "guests_table"
KIND_AGENDA = "agenda_table"
KIND_TOPIC = "topic"
KIND_CLOSING = "closing"
KIND_SIGNATURES = "signatures"
KIND_META = "meta"

ALL_KINDS = (
    KIND_TEXT,
    KIND_HEADER,
    KIND_TITLE,
    KIND_RICH,
    KIND_MEMBERS,
    KIND_GUESTS,
    KIND_AGENDA,
    KIND_TOPIC,
    KIND_CLOSING,
    KIND_SIGNATURES,
    KIND_META,
)
# أنواع يقدر المستخدم يضيفها بنفسه (الباقي يبنيه القالب فقط).
USER_CREATABLE_KINDS = (KIND_TEXT, KIND_RICH, KIND_TOPIC)

RICH_OPENING = "opening"
RICH_OPENING_FOLLOWUP = "opening_followup"
RICH_DISCUSSION = "discussion"
RICH_CUSTOM = "custom"

# ============================== النصوص الثابتة ==============================
STATUS_PRESENT = "حاضر"
STATUS_ABSENT = "غائب"
MODE_REMOTE = "عن بعد"
MODE_IN_PERSON = "حضوري"
MODE_ABSENT = "غائب"
PLACE_REMOTE = "عبر الاتصال المرئي"
GUEST_ROLE = "ضيف خارجي"
CHAIR_ROLE_FALLBACK = "رئيس اللجنة"
TIME_PENDING = "......"

TITLE_LINE1 = "محضر اجتماع"
GUESTS_CAPTION = "وقد حضر الاجتماع:"
AGENDA_CAPTION = "وقد تم استعراض ومناقشة جدول الأعمال وفقاً للتالي:"
DISCUSSION_HEADING = "مناقشة أعضاء اللجنة"
BACKGROUND_LABEL = "حيثيات الموضوع:"
DECISION_LABEL = "القرار"
CLOSING_SIGN_OFF = "وعلى ذلك جرى التوقيع،"

OPENING_PLACEHOLDER = (
    "اكتب الفقرة الافتتاحية، مثال: إنه في يوم ... الموافق ... انعقد اجتماع ... برئاسة ... "
    "وبحضور الأعضاء التالية أسماؤهم:"
)
OPENING_FOLLOWUP_PLACEHOLDER = (
    "اكتب فقرة الافتتاح، مثال: وقد افتتح رئيس اللجنة الاجتماع ... ورحّب بالأعضاء، وحيث إن "
    "الاجتماع انعقد مكتمل النصاب ..."
)
DISCUSSION_PLACEHOLDER = "اكتب مناقشة أعضاء اللجنة"
BACKGROUND_PLACEHOLDER = "اكتب حيثيات الموضوع"
DECISION_PLACEHOLDER = "وبعد مناقشة حيثيات الموضوع قررت اللجنة ما يلي: أولاً: ... ثانياً: ..."

MAX_TEXT_FIELD = 2_000
MAX_ROWS = 500


class SectionsValidationError(ValueError):
    """تعديل أقسام غير صالح — رسالة عربية (تُترجم لـ400)."""


class SectionConflictError(Exception):
    """
    تعديل قسم بنسخة قديمة (rev لا يطابق المخزَّن) — تُترجم لـ409.
    current: نسخة القسم الحالية حتى تعرضها الواجهة وتعيد تطبيق التعديل.
    """

    def __init__(self, current: dict):
        super().__init__("تم تعديل هذا القسم من شخص آخر أو من بيانات الاجتماع — حدّث الصفحة وأعد المحاولة")
        self.current = current


# ============================== بيانات الاجتماع (المدخل) ==============================


@dataclass(frozen=True)
class MemberInfo:
    """عضو لجنة كما يظهر بالمحضر: المعرّف، الاسم، الصفة (اسم دوره باللجنة)، وهل هو الرئيس."""

    user_id: str
    name: str
    role_label: str
    is_chair: bool = False


@dataclass(frozen=True)
class GuestInfo:
    """ضيف خارجي مقبول دخل الاجتماع: المعرّف (حساب الضيف المؤقت) والاسم من شاشة الدخول."""

    user_id: str
    name: str


@dataclass(frozen=True)
class AgendaInfo:
    """بند جدول أعمال: المعرّف، العنوان، الترتيب."""

    agenda_item_id: str
    title: str
    sort_order: int


@dataclass(frozen=True)
class MeetingSnapshot:
    """
    كل ما يحتاجه القالب من الاجتماع — يُجمع من القاعدة في snapshot.load_snapshot.

    - mode: "remote" أو "in_person".
    - started: هل بدأ الاجتماع (قبل البداية لا يُحكم بحاضر/غائب).
    - end_time: وقت الانتهاء الفعلي، أو None ما دام الاجتماع لم ينتهِ.
    - members: مرتبون (الرئيس أولًا، أمين السر آخرًا).
    """

    committee_name: str
    meeting_title: str
    mode: str
    location: str | None
    scheduled_at: datetime
    end_time: datetime | None
    started: bool
    meeting_number: int
    meeting_year: int
    members: tuple[MemberInfo, ...] = ()
    attended_user_ids: frozenset[str] = field(default_factory=frozenset)
    guests: tuple[GuestInfo, ...] = ()
    agenda: tuple[AgendaInfo, ...] = ()


# ============================== مواصفات الحقول لكل نوع ==============================
# auto: تتزامن مع الاجتماع حتى تُعدَّل يدويًا. free: يكتبها المستخدم ولا تتزامن.
# docs: محتوى محرر غني. ints: أعداد. row_auto/row_fields: حقول صفوف الجداول.


@dataclass(frozen=True)
class _KindSpec:
    auto: tuple[str, ...] = ()
    free: tuple[str, ...] = ()
    docs: tuple[str, ...] = ()
    ints: dict[str, tuple[int, int]] = field(default_factory=dict)
    row_fields: tuple[str, ...] = ()


_SPECS: dict[str, _KindSpec] = {
    KIND_HEADER: _KindSpec(auto=("date_text", "place_text", "time_text", "subject_text")),
    KIND_TITLE: _KindSpec(
        auto=("meeting_number", "meeting_year", "line2"),
        free=("line1",),
        ints={"meeting_number": (1, 999), "meeting_year": (1900, 2200)},
    ),
    KIND_RICH: _KindSpec(free=("heading",), docs=("content",)),
    KIND_MEMBERS: _KindSpec(free=("caption",), row_fields=("name", "role_label", "mode_label", "status_label")),
    KIND_GUESTS: _KindSpec(free=("caption",), row_fields=("name", "mode_label", "role_label")),
    KIND_AGENDA: _KindSpec(free=("caption",), row_fields=("ordinal_label", "title")),
    KIND_TOPIC: _KindSpec(
        auto=("ordinal_label", "heading", "decision_number"),
        free=("background_label", "decision_label"),
        docs=("background", "decision"),
    ),
    KIND_CLOSING: _KindSpec(auto=("text",), free=("sign_off",)),
    KIND_SIGNATURES: _KindSpec(auto=("heading",), row_fields=("name", "role_label")),
    KIND_META: _KindSpec(),
}

_TABLE_KINDS = (KIND_MEMBERS, KIND_GUESTS, KIND_AGENDA, KIND_SIGNATURES)


# ============================== أدوات مساعدة ==============================


def _locked(obj: dict) -> set[str]:
    """الحقول المقفلة (المعدّلة يدويًا) في قسم أو صف."""
    return set(obj.get("locked") or [])


def _lock(obj: dict, name: str) -> None:
    """يضيف حقلًا لقائمة المقفلة (بدون تكرار) — التأثير: يعدّل obj."""
    locked = list(obj.get("locked") or [])
    if name not in locked:
        locked.append(name)
    obj["locked"] = locked


def _set_auto(obj: dict, name: str, value: Any) -> None:
    """يحدّث حقلًا تلقائيًا إلا إذا كان مقفلًا يدويًا — التأثير: يعدّل obj."""
    if name not in _locked(obj):
        obj[name] = value


def _new_section(kind: str, title: str, data: dict) -> dict:
    """قسم جديد بمعرّف عشوائي ورقم مراجعة 1."""
    return {"id": str(uuid.uuid4()), "kind": kind, "order": 0, "title": title, "body": "", "rev": 1, "data": data}


def section_kind(section: dict) -> str:
    """نوع القسم — القديم بلا kind يُعامل نصًا."""
    return section.get("kind") or KIND_TEXT


def _rich(role: str, heading: str, placeholder: str, title: str) -> dict:
    """قسم محرر غني (فقرة افتتاحية/فقرة افتتاح/مناقشة)."""
    return _new_section(
        KIND_RICH, title, {"role": role, "heading": heading, "placeholder": placeholder, "content": None}
    )


def _table(kind: str, title: str, caption: str) -> dict:
    """قسم جدول فارغ (صفوفه تملؤها المزامنة)."""
    return _new_section(kind, title, {"caption": caption, "rows": [], "removed_keys": [], "locked": []})


def new_topic_section(agenda: AgendaInfo | None) -> dict:
    """
    الهدف: قسم موضوع جديد — مربوط ببند جدول أعمال (تلقائي) أو يدوي (agenda=None).
    المخرجات: القسم (العناوين والأرقام تملؤها المزامنة).
    """
    return _new_section(
        KIND_TOPIC,
        agenda.title if agenda else "موضوع",
        {
            "agenda_item_id": agenda.agenda_item_id if agenda else None,
            "ordinal_label": "",
            "heading": agenda.title if agenda else "",
            "background_label": BACKGROUND_LABEL,
            "background_placeholder": BACKGROUND_PLACEHOLDER,
            "background": None,
            "decision_label": DECISION_LABEL,
            "decision_number": "",
            "decision_placeholder": DECISION_PLACEHOLDER,
            "decision": None,
            "locked": [],
        },
    )


def build_skeleton() -> list[dict]:
    """
    الهدف: هيكل القالب العام الفارغ بالترتيب المعتمد (المواضيع تُضاف بالمزامنة).
    المخرجات: قائمة أقسام بأرقام order متتالية.
    """
    sections = [
        _new_section(
            KIND_HEADER,
            "الترويسة",
            {"date_text": "", "place_text": "", "time_text": "", "subject_text": "", "locked": []},
        ),
        _new_section(
            KIND_TITLE,
            "العنوان",
            {"line1": TITLE_LINE1, "line2": "", "meeting_number": 1, "meeting_year": 2000, "locked": []},
        ),
        _rich(RICH_OPENING, "", OPENING_PLACEHOLDER, "الفقرة الافتتاحية"),
        _table(KIND_MEMBERS, "أعضاء اللجنة", ""),
        _table(KIND_GUESTS, "الحاضرون من خارج اللجنة", GUESTS_CAPTION),
        _rich(RICH_OPENING_FOLLOWUP, "", OPENING_FOLLOWUP_PLACEHOLDER, "فقرة الافتتاح"),
        _table(KIND_AGENDA, "جدول الأعمال", AGENDA_CAPTION),
        _rich(RICH_DISCUSSION, DISCUSSION_HEADING, DISCUSSION_PLACEHOLDER, DISCUSSION_HEADING),
        _new_section(KIND_CLOSING, "الختام", {"text": "", "sign_off": CLOSING_SIGN_OFF, "locked": []}),
        _table(KIND_SIGNATURES, "التوقيعات", ""),
        _new_section(KIND_META, "بيانات القالب", {"template": TEMPLATE_ID, "removed_topic_keys": []}),
    ]
    for index, section in enumerate(sections):
        section["order"] = index
    return sections


# ============================== المزامنة مع الاجتماع ==============================


def _member_status(snap: MeetingSnapshot, user_id: str) -> str:
    """
    حالة العضو التلقائية: عن بعد بعد بداية الاجتماع ← حاضر/غائب من الحضور
    التلقائي. قبل البداية، وفي الحضوري (لا تسجيل حضور) ← فارغة يختارها الرئيس.
    """
    if snap.mode != "remote" or not snap.started:
        return ""
    return STATUS_PRESENT if user_id in snap.attended_user_ids else STATUS_ABSENT


def _mode_for_status(snap: MeetingSnapshot, status: str) -> str:
    """آلية الحضور المشتقة من الحالة: الغائب "غائب"، وغيره حسب نوع الاجتماع."""
    if status == STATUS_ABSENT:
        return MODE_ABSENT
    return MODE_REMOTE if snap.mode == "remote" else MODE_IN_PERSON


def _sync_rows(data: dict, desired: list[tuple[str, dict]], *, remove_missing: bool) -> None:
    """
    الهدف: مزامنة صفوف جدول مع القائمة المطلوبة من الاجتماع.

    المدخلات:
    - data: بيانات قسم الجدول (rows، removed_keys).
    - desired: [(key، الحقول التلقائية)] بالترتيب المطلوب.
    - remove_missing: هل يُحذف الصف التلقائي اللي اختفى من الاجتماع (إذا ما
      انعدّل يدويًا).

    القواعد: الحقول المقفلة لا تتغير، والمحذوف يدويًا (removed_keys) لا يرجع،
    والصفوف اليدوية تبقى كما هي بعد الصفوف التلقائية.
    التأثيرات: يعدّل data["rows"].
    """
    rows = data.get("rows") or []
    removed = set(data.get("removed_keys") or [])
    existing_auto = {row["key"]: row for row in rows if row.get("auto")}
    manual_rows = [row for row in rows if not row.get("auto")]

    synced: list[dict] = []
    desired_keys: set[str] = set()
    for key, values in desired:
        desired_keys.add(key)
        if key in removed:
            continue
        row = existing_auto.get(key) or {"key": key, "auto": True, "locked": []}
        for name, value in values.items():
            _set_auto(row, name, value)
        synced.append(row)
    for key, row in existing_auto.items():
        if key in desired_keys:
            continue
        if remove_missing and not row.get("locked"):
            continue
        synced.append(row)
    data["rows"] = synced + manual_rows


def _topic_untouched(section: dict) -> bool:
    """موضوع ما انكتب فيه شيء ولا انعدّل — يُحذف لو انحذف بنده من جدول الأعمال."""
    data = section.get("data") or {}
    return (
        not data.get("locked")
        and is_empty_doc(data.get("background"))
        and is_empty_doc(data.get("decision"))
        and data.get("background_label", BACKGROUND_LABEL) == BACKGROUND_LABEL
        and data.get("decision_label", DECISION_LABEL) == DECISION_LABEL
    )


def _first(sections: list[dict], kind: str, role: str | None = None) -> dict | None:
    """أول قسم من نوع معيّن (ودور معيّن للمحرر الغني)."""
    for section in sections:
        if section_kind(section) != kind:
            continue
        if role is not None and (section.get("data") or {}).get("role") != role:
            continue
        return section
    return None


def _place_topics(sections: list[dict], topics: list[dict]) -> list[dict]:
    """
    الهدف: وضع أقسام المواضيع متتالية في مكانها وإعادة ترقيم order.
    المكان: مكان أول موضوع موجود، وإلا بعد "مناقشة أعضاء اللجنة"، وإلا بعد
    جدول الأعمال، وإلا قبل الختام، وإلا بالنهاية.
    """
    ordered = sorted(sections, key=lambda s: s.get("order", 0))
    others = [s for s in ordered if section_kind(s) != KIND_TOPIC]
    slot: int | None = None
    position = 0
    for section in ordered:
        if section_kind(section) == KIND_TOPIC:
            slot = position
            break
        position += 1
    if slot is None:
        for anchor in (
            _first(others, KIND_RICH, RICH_DISCUSSION),
            _first(others, KIND_AGENDA),
        ):
            if anchor is not None:
                slot = others.index(anchor) + 1
                break
    if slot is None:
        closing = _first(others, KIND_CLOSING)
        slot = others.index(closing) if closing is not None else len(others)
    final = others[:slot] + topics + others[slot:]
    for index, section in enumerate(final):
        section["order"] = index
    return final


def sync_sections(sections: list[dict] | None, snap: MeetingSnapshot) -> list[dict]:
    """
    الهدف: تعبئة/تحديث الأجزاء التلقائية في القالب العام من بيانات الاجتماع.

    المدخلات:
    - sections: الأقسام المخزّنة (None أو فارغة ⇒ يُبنى الهيكل من جديد).
    - snap: بيانات الاجتماع الحالية.

    المخرجات: قائمة أقسام جديدة (نسخة — المدخل لا يتغير). أي قسم تغيّر
    محتواه يزيد rev بواحد.

    القواعد: الحقول المقفلة يدويًا لا تتغير، والمحذوف يدويًا لا يرجع، والقسم
    المحذوف كاملًا (غير المواضيع) لا يُعاد إنشاؤه.
    """
    before = {s["id"]: copy.deepcopy(s) for s in sections or []}
    result = copy.deepcopy(sections) if sections else build_skeleton()

    meta = _first(result, KIND_META)
    if meta is None:
        meta = _new_section(KIND_META, "بيانات القالب", {"template": TEMPLATE_ID, "removed_topic_keys": []})
        meta["order"] = 10_000
        result.append(meta)

    # --- العنوان: رقم الاجتماع وسنته (قابلان للتعديل) ثم السطر الثاني منهما.
    number, year = snap.meeting_number, snap.meeting_year
    title = _first(result, KIND_TITLE)
    if title is not None:
        data = title["data"]
        _set_auto(data, "meeting_number", snap.meeting_number)
        _set_auto(data, "meeting_year", snap.meeting_year)
        number, year = data["meeting_number"], data["meeting_year"]
        _set_auto(data, "line2", f"{snap.committee_name} - الاجتماع {formatting.ordinal_ar(number)} لعام {year}م")

    # --- الترويسة.
    header = _first(result, KIND_HEADER)
    if header is not None:
        data = header["data"]
        _set_auto(data, "date_text", formatting.date_text(snap.scheduled_at))
        place = PLACE_REMOTE if snap.mode == "remote" else (snap.location or "—")
        _set_auto(data, "place_text", place)
        _set_auto(data, "time_text", formatting.time_text(snap.scheduled_at))
        _set_auto(data, "subject_text", f"محضر {snap.meeting_title}")

    # --- أعضاء اللجنة: الحالة من الحضور، وآلية الحضور مشتقة من الحالة النهائية.
    members = _first(result, KIND_MEMBERS)
    if members is not None:
        desired = [
            (m.user_id, {"name": m.name, "role_label": m.role_label, "status_label": _member_status(snap, m.user_id)})
            for m in snap.members
        ]
        _sync_rows(members["data"], desired, remove_missing=True)
        for row in members["data"]["rows"]:
            if row.get("auto"):
                _set_auto(row, "mode_label", _mode_for_status(snap, row.get("status_label", "")))

    # --- الضيوف: اللي انقبلوا ودخلوا فقط، والصفة "ضيف خارجي" كقيمة أولية.
    guests = _first(result, KIND_GUESTS)
    if guests is not None:
        guest_mode = MODE_REMOTE if snap.mode == "remote" else MODE_IN_PERSON
        desired = [(g.user_id, {"name": g.name, "mode_label": guest_mode, "role_label": GUEST_ROLE}) for g in snap.guests]
        _sync_rows(guests["data"], desired, remove_missing=False)

    # --- جدول البنود.
    agenda_items = sorted(snap.agenda, key=lambda a: a.sort_order)
    agenda = _first(result, KIND_AGENDA)
    if agenda is not None:
        desired = [(a.agenda_item_id, {"title": a.title}) for a in agenda_items]
        _sync_rows(agenda["data"], desired, remove_missing=True)
        for index, row in enumerate(agenda["data"]["rows"], start=1):
            if row.get("auto"):
                _set_auto(row, "ordinal_label", f"الموضوع {formatting.ordinal_ar(index)}")

    # --- المواضيع: قسم لكل بند (إلا المحذوف يدويًا)، ثم الترقيم وأرقام القرارات.
    existing_topics = [s for s in sorted(result, key=lambda s: s.get("order", 0)) if section_kind(s) == KIND_TOPIC]
    removed_topics = set(meta["data"].get("removed_topic_keys") or [])
    present_keys = {a.agenda_item_id for a in agenda_items}
    by_agenda = {
        (s.get("data") or {}).get("agenda_item_id"): s
        for s in existing_topics
        if (s.get("data") or {}).get("agenda_item_id")
    }
    topics: list[dict] = []
    included: set[str] = set()
    for item in agenda_items:
        if item.agenda_item_id in removed_topics:
            continue
        section = by_agenda.get(item.agenda_item_id) or new_topic_section(item)
        _set_auto(section["data"], "heading", item.title)
        topics.append(section)
        included.add(section["id"])
    for section in existing_topics:
        if section["id"] in included:
            continue
        key = (section.get("data") or {}).get("agenda_item_id")
        if key and key not in present_keys and _topic_untouched(section):
            continue  # بند انحذف من جدول الأعمال وموضوعه فاضي.
        topics.append(section)
    for index, section in enumerate(topics, start=1):
        data = section["data"]
        _set_auto(data, "ordinal_label", f"الموضوع {formatting.ordinal_ar(index)}")
        _set_auto(data, "decision_number", f"({index}-{number}-{year})")
        section["title"] = (f"{data.get('ordinal_label', '')}: {data.get('heading', '')}".strip(": ") or "موضوع")[:200]
    result = _place_topics([s for s in result if section_kind(s) != KIND_TOPIC], topics)

    # --- الختام: وقت الانتهاء الفعلي.
    closing = _first(result, KIND_CLOSING)
    if closing is not None:
        clock = formatting.clock_text(snap.end_time) if snap.end_time else TIME_PENDING
        _set_auto(
            closing["data"],
            "text",
            "وقد انتهى الاجتماع بحمد الله والصلاة والسلام على خير خلقه سيدنا محمد صلى الله عليه وسلم "
            f"في الساعة {clock}.",
        )

    # --- التوقيعات: كل أعضاء اللجنة، والرئيس آخر خانة (مثل المحضر الأصلي).
    signatures = _first(result, KIND_SIGNATURES)
    if signatures is not None:
        ordered = [m for m in snap.members if not m.is_chair] + [m for m in snap.members if m.is_chair]
        desired = [(m.user_id, {"name": m.name, "role_label": m.role_label}) for m in ordered]
        _sync_rows(signatures["data"], desired, remove_missing=True)
        _set_auto(
            signatures["data"],
            "heading",
            f"توقيع أعضاء {snap.committee_name} على محضر الاجتماع {formatting.ordinal_ar(number)} لعام {year}م",
        )

    # --- رقم المراجعة لكل قسم تغيّر.
    for section in result:
        old = before.get(section["id"])
        if old is None:
            section["rev"] = max(int(section.get("rev") or 0), 1)
            continue
        compare_old = {k: v for k, v in old.items() if k not in ("rev", "order")}
        compare_new = {k: v for k, v in section.items() if k not in ("rev", "order")}
        section["rev"] = int(old.get("rev") or 0) + (1 if compare_old != compare_new else 0)
    return result


# ============================== دمج تعديلات المستخدم ==============================


def _clean_text(value: Any, name: str) -> str:
    """نص من المستخدم: لازم يكون نصًا وبطول معقول."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SectionsValidationError(f"قيمة غير صالحة للحقل {name}")
    if len(value) > MAX_TEXT_FIELD:
        raise SectionsValidationError("النص أطول من الحد المسموح")
    return value


def _clean_value(spec: _KindSpec, name: str, value: Any) -> Any:
    """تنظيف قيمة حقل حسب نوعه (عدد/محتوى محرر/نص)."""
    if name in spec.ints:
        low, high = spec.ints[name]
        if isinstance(value, bool) or not isinstance(value, int) or not (low <= value <= high):
            raise SectionsValidationError(f"قيمة غير صالحة للحقل {name}")
        return value
    if name in spec.docs:
        try:
            return validate_editor_doc(value)
        except EditorContentError as exc:
            raise SectionsValidationError(str(exc)) from exc
    return _clean_text(value, name)


def _merge_rows(stored: dict, incoming_rows: Any, spec: _KindSpec) -> None:
    """
    الهدف: دمج صفوف جدول عدّلها المستخدم مع المخزّنة.

    القواعد:
    - صف معروف (key مخزّن): الصف التلقائي تُقفل خاناته اللي تغيّرت قيمتها،
      واليدوي يأخذ القيم الجديدة كما هي.
    - صف بلا key معروف = صف يدوي جديد بمعرّف يولّده الخادم.
    - صف تلقائي اختفى = حذفه المستخدم ⇒ removed_keys حتى لا ترجعه المزامنة.
    - ما يرسله العميل في locked/auto/removed_keys يُتجاهل — الخادم يحسبها.
    التأثيرات: يعدّل stored["rows"] وstored["removed_keys"].
    """
    if incoming_rows is None:
        return
    if not isinstance(incoming_rows, list) or len(incoming_rows) > MAX_ROWS:
        raise SectionsValidationError("صفوف الجدول غير صالحة")
    stored_by_key = {row["key"]: row for row in stored.get("rows") or []}
    merged: list[dict] = []
    seen: set[str] = set()
    for incoming in incoming_rows:
        if not isinstance(incoming, dict):
            raise SectionsValidationError("صفوف الجدول غير صالحة")
        key = incoming.get("key")
        if isinstance(key, str) and key in stored_by_key and key not in seen:
            row = copy.deepcopy(stored_by_key[key])
            for name in spec.row_fields:
                if name not in incoming:
                    continue
                value = _clean_text(incoming[name], name)
                if row.get("auto"):
                    if value != row.get(name, ""):
                        row[name] = value
                        _lock(row, name)
                else:
                    row[name] = value
            seen.add(key)
        else:
            row = {"key": f"manual:{uuid.uuid4()}", "auto": False, "locked": []}
            for name in spec.row_fields:
                row[name] = _clean_text(incoming.get(name, ""), name)
        merged.append(row)
    removed = list(stored.get("removed_keys") or [])
    for key, row in stored_by_key.items():
        if key not in seen and row.get("auto") and key not in removed:
            removed.append(key)
    stored["rows"] = merged
    stored["removed_keys"] = removed


def merge_user_section(stored: dict, incoming: dict) -> dict:
    """
    الهدف: تطبيق تعديل المستخدم على قسم واحد مخزّن.

    المدخلات:
    - stored: القسم المخزّن.
    - incoming: القسم كما أرسلته الواجهة (id، kind، title، body، data).

    المخرجات: نسخة القسم بعد الدمج (rev لا يتغير هنا — يتولاه المستدعي).

    القواعد: نوع القسم لا يتغير. الحقول التلقائية اللي تغيّرت تُقفل. الحقول
    الثابتة (role، placeholder، agenda_item_id، locked، removed_keys) يحددها
    الخادم فقط ولا تُقبل من الواجهة.
    الأخطاء: SectionsValidationError.
    """
    kind = section_kind(stored)
    if (incoming.get("kind") or KIND_TEXT) != kind:
        raise SectionsValidationError("لا يمكن تغيير نوع القسم")
    merged = copy.deepcopy(stored)
    if kind == KIND_TEXT:
        merged["title"] = _clean_text(incoming.get("title"), "title")[:200] or stored.get("title", "قسم")
        merged["body"] = incoming.get("body") if isinstance(incoming.get("body"), str) else stored.get("body", "")
        return merged
    if kind == KIND_META:
        return merged  # بيانات داخلية — لا تُعدّل من الواجهة.

    spec = _SPECS[kind]
    data = merged.setdefault("data", {})
    incoming_data = incoming.get("data")
    if incoming_data is None:
        return merged
    if not isinstance(incoming_data, dict):
        raise SectionsValidationError("بيانات القسم غير صالحة")
    for name in spec.auto:
        if name in incoming_data:
            value = _clean_value(spec, name, incoming_data[name])
            if value != data.get(name):
                data[name] = value
                _lock(data, name)
    for name in spec.free + spec.docs:
        if name in incoming_data:
            data[name] = _clean_value(spec, name, incoming_data[name])
    if spec.row_fields:
        _merge_rows(data, incoming_data.get("rows"), spec)
    if kind == KIND_TOPIC:
        merged["title"] = (
            f"{data.get('ordinal_label', '')}: {data.get('heading', '')}".strip(": ") or "موضوع"
        )[:200]
    return merged


def new_user_section(incoming: dict) -> dict:
    """
    الهدف: قسم جديد يضيفه المستخدم بنفسه (نص، محرر غني، أو موضوع يدوي).
    المخرجات: القسم النظيف بمعرّف من الخادم. الأخطاء: SectionsValidationError
    لو النوع من الأقسام اللي يبنيها القالب فقط.
    """
    kind = incoming.get("kind") or KIND_TEXT
    if kind not in USER_CREATABLE_KINDS:
        raise SectionsValidationError("لا يمكن إضافة هذا النوع من الأقسام")
    if kind == KIND_TEXT:
        base = _new_section(KIND_TEXT, "قسم جديد", {})
        base.pop("data")
    elif kind == KIND_RICH:
        base = _rich(RICH_CUSTOM, "", "", "قسم جديد")
    else:
        base = new_topic_section(None)
    merged = merge_user_section(base, {**incoming, "kind": kind})
    merged["id"] = base["id"]
    return merged


def merge_user_sections(stored_sections: list[dict], incoming_sections: list[dict]) -> list[dict]:
    """
    الهدف: حفظ قائمة الأقسام كاملة (إضافة/حذف/ترتيب) للقالب العام.

    المدخلات: المخزّنة، والقائمة الكاملة من الواجهة (بترتيبها الجديد).
    المخرجات: القائمة بعد الدمج، بأرقام order متتالية حسب ترتيب الواجهة.

    القواعد:
    - قسم موجود: rev لازم يطابق المخزّن، ثم merge_user_section، وrev+1 لو تغيّر.
    - قسم جديد: new_user_section (نص/محرر/موضوع يدوي فقط).
    - قسم محذوف: موضوع تلقائي ⇒ يُسجّل في meta حتى لا ترجعه المزامنة. قسم
      meta لا يُحذف.
    الأخطاء: SectionsValidationError، SectionConflictError.
    """
    stored_by_id = {s["id"]: s for s in stored_sections}
    result: list[dict] = []
    seen: set[str] = set()
    for incoming in incoming_sections:
        section_id = incoming.get("id")
        stored = stored_by_id.get(section_id) if isinstance(section_id, str) else None
        if stored is not None and section_kind(stored) == KIND_META:
            # بيانات داخلية: لا تُعدّل من الواجهة، وتُلحق مرة واحدة بالنهاية.
            seen.add(section_id)
            continue
        if stored is not None and section_id not in seen:
            if int(incoming.get("rev") or 0) != int(stored.get("rev") or 0):
                raise SectionConflictError(stored)
            merged = merge_user_section(stored, incoming)
            if merged != stored:
                merged["rev"] = int(stored.get("rev") or 0) + 1
            result.append(merged)
            seen.add(section_id)
        else:
            result.append(new_user_section(incoming))

    meta = next((s for s in stored_sections if section_kind(s) == KIND_META), None)
    for section_id, stored in stored_by_id.items():
        if section_id in seen:
            continue
        kind = section_kind(stored)
        if kind == KIND_META:
            continue
        agenda_key = (stored.get("data") or {}).get("agenda_item_id") if kind == KIND_TOPIC else None
        if agenda_key and meta is not None:
            removed = list(meta["data"].get("removed_topic_keys") or [])
            if agenda_key not in removed:
                removed.append(agenda_key)
                meta = copy.deepcopy(meta)
                meta["data"]["removed_topic_keys"] = removed
                meta["rev"] = int(meta.get("rev") or 0) + 1
    if meta is not None:
        result.append(meta)
    for index, section in enumerate(result):
        section["order"] = index
    return result


def apply_user_section_update(stored_sections: list[dict], incoming: dict) -> tuple[list[dict], dict]:
    """
    الهدف: تعديل قسم واحد فقط (الحفظ الأساسي أثناء التحرير الجماعي) — لا يلمس
    باقي الأقسام، فتعديلان متزامنان على قسمين مختلفين لا يمسح أحدهما الآخر.

    المدخلات: الأقسام المخزّنة، والقسم المعدّل (لازم يحمل rev الحالي).
    المخرجات: (القائمة الجديدة، القسم بعد الحفظ).
    الأخطاء: SectionsValidationError (قسم غير موجود/بيانات غير صالحة)،
    SectionConflictError (rev قديم).
    """
    section_id = incoming.get("id")
    index = next((i for i, s in enumerate(stored_sections) if s.get("id") == section_id), None)
    if index is None:
        raise SectionsValidationError("القسم غير موجود في المحضر")
    stored = stored_sections[index]
    if int(incoming.get("rev") or 0) != int(stored.get("rev") or 0):
        raise SectionConflictError(stored)
    merged = merge_user_section(stored, incoming)
    if merged != stored:
        merged["rev"] = int(stored.get("rev") or 0) + 1
    result = list(stored_sections)
    result[index] = merged
    return result, merged
