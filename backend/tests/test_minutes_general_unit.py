"""
اختبارات وحدة "القالب العام" للمحاضر — الدوال النقية بدون قاعدة بيانات:
التنسيق (هجري/وقت/ترتيب)، بناء الأقسام ومزامنتها، دمج تعديلات المستخدم
(الأقفال، المحذوف، rev)، التحقق من محتوى المحرر، والتوقيع المحفوظ، وملف PDF.

ملاحظة: conftest.py يفرّغ الجداول تلقائيًا قبل كل اختبار (autouse) — هذه
الاختبارات لا تستخدم القاعدة لكنها تمر بنفس التجهيز.
"""

import base64
import copy
import io
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from PIL import Image
from pypdf import PdfReader

from app.services import user_signature_service
from app.services.minutes_general import formatting as F
from app.services.minutes_general import sections as S
from app.services.minutes_general.editor_content import EditorContentError, validate_editor_doc
from app.services.minutes_general.pdf import GeneralMinutesPdfData, build_general_minutes_pdf


def _snap(**overrides) -> S.MeetingSnapshot:
    """لقطة اجتماع عن بعد منعقد: رئيس + عضو + أمين سر، ضيف، بندان."""
    base = dict(
        committee_name="لجنة التقنية",
        meeting_title="اجتماع لجنة التقنية",
        mode="remote",
        location=None,
        scheduled_at=datetime(2025, 1, 16, 14, 0, tzinfo=UTC),
        end_time=None,
        started=True,
        meeting_number=6,
        meeting_year=2025,
        members=(
            S.MemberInfo("chair", "أحمد علي", "رئيس اللجنة", True),
            S.MemberInfo("m1", "سارة محمد", "عضو اللجنة"),
            S.MemberInfo("sec", "خالد", "أمين سر اللجنة"),
        ),
        attended_user_ids=frozenset({"chair"}),
        guests=(S.GuestInfo("g1", "ضيف"),),
        agenda=(S.AgendaInfo("a1", "الموازنة", 0), S.AgendaInfo("a2", "إنشاء شركة", 1)),
    )
    base.update(overrides)
    return S.MeetingSnapshot(**base)


def _by_kind(sections: list[dict], kind: str, role: str | None = None) -> dict:
    return next(
        s for s in sections if s["kind"] == kind and (role is None or (s.get("data") or {}).get("role") == role)
    )


def _topics(sections: list[dict]) -> list[dict]:
    return [s for s in sorted(sections, key=lambda s: s["order"]) if s["kind"] == "topic"]


def _doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def _png_data_url(size: int = 40) -> str:
    buffer = io.BytesIO()
    Image.new("RGBA", (size, size // 2), (0, 0, 0, 255)).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


# ============================== التنسيق ==============================


def test_ordinals_cover_compound_numbers() -> None:
    assert F.ordinal_ar(1) == "الأول"
    assert F.ordinal_ar(6) == "السادس"
    assert F.ordinal_ar(11) == "الحادي عشر"
    assert F.ordinal_ar(12) == "الثاني عشر"
    assert F.ordinal_ar(20) == "العشرون"
    assert F.ordinal_ar(21) == "الحادي والعشرون"
    assert F.ordinal_ar(150) == "150"


def test_date_and_time_match_original_minutes() -> None:
    """المحضر الأصلي: الخميس 1446/07/16هـ الموافق 2025/01/16م — الساعة 05:00 مساءً."""
    moment = datetime(2025, 1, 16, 14, 0, tzinfo=UTC)  # 17:00 بتوقيت الرياض
    assert F.date_text(moment) == "الخميس 1446/07/16هـ الموافق 2025/01/16م"
    assert F.time_text(moment) == "الساعة 05:00 مساءً"
    assert F.clock_text(datetime(2025, 1, 16, 6, 30, tzinfo=UTC)) == "09:30 صباحاً"
    assert F.clock_text(datetime(2025, 1, 16, 21, 0, tzinfo=UTC)) == "12:00 صباحاً"  # منتصف الليل


def test_date_outside_umm_al_qura_range_falls_back_to_gregorian() -> None:
    assert F.date_text(datetime(1800, 1, 1, 12, tzinfo=UTC)) == "الأربعاء 1800/01/01م"


# ============================== البناء والمزامنة ==============================


def test_initial_build_follows_original_layout() -> None:
    sections = S.sync_sections(None, _snap())
    kinds = [s["kind"] for s in sorted(sections, key=lambda s: s["order"])]
    assert kinds == [
        "header", "title", "rich", "members_table", "guests_table", "rich", "agenda_table",
        "rich", "topic", "topic", "closing", "signatures", "meta",
    ]
    header = _by_kind(sections, "header")["data"]
    assert header["place_text"] == "عبر الاتصال المرئي"
    assert header["subject_text"] == "محضر اجتماع لجنة التقنية"
    assert _by_kind(sections, "title")["data"]["line2"] == "لجنة التقنية - الاجتماع السادس لعام 2025م"

    members = _by_kind(sections, "members_table")["data"]["rows"]
    assert [r["key"] for r in members] == ["chair", "m1", "sec"]  # الرئيس أولًا
    assert (members[0]["status_label"], members[0]["mode_label"]) == ("حاضر", "عن بعد")
    assert (members[1]["status_label"], members[1]["mode_label"]) == ("غائب", "غائب")

    guest = _by_kind(sections, "guests_table")["data"]["rows"][0]
    assert (guest["name"], guest["role_label"]) == ("ضيف", "ضيف خارجي")

    topics = _topics(sections)
    assert [t["data"]["ordinal_label"] for t in topics] == ["الموضوع الأول", "الموضوع الثاني"]
    assert [t["data"]["decision_number"] for t in topics] == ["(1-6-2025)", "(2-6-2025)"]

    signatures = _by_kind(sections, "signatures")["data"]["rows"]
    assert [r["key"] for r in signatures] == ["m1", "sec", "chair"]  # الرئيس آخرًا
    assert "......" in _by_kind(sections, "closing")["data"]["text"]  # الاجتماع ما انتهى


def test_status_blank_before_start_and_for_in_person() -> None:
    before_start = S.sync_sections(None, _snap(started=False))
    row = _by_kind(before_start, "members_table")["data"]["rows"][1]
    assert (row["status_label"], row["mode_label"]) == ("", "عن بعد")

    in_person = S.sync_sections(None, _snap(mode="in_person", location="قاعة الاجتماعات"))
    assert _by_kind(in_person, "header")["data"]["place_text"] == "قاعة الاجتماعات"
    row = _by_kind(in_person, "members_table")["data"]["rows"][0]
    assert (row["status_label"], row["mode_label"]) == ("", "حضوري")


def test_resync_without_changes_keeps_revisions() -> None:
    sections = S.sync_sections(None, _snap())
    again = S.sync_sections(sections, _snap())
    assert again == sections


def test_sync_updates_auto_fields_and_bumps_rev_only_for_changed_sections() -> None:
    sections = S.sync_sections(None, _snap())
    later = S.sync_sections(
        sections,
        _snap(attended_user_ids=frozenset({"chair", "m1"}), end_time=datetime(2025, 1, 16, 15, 30, tzinfo=UTC)),
    )
    members = _by_kind(later, "members_table")
    assert members["data"]["rows"][1]["status_label"] == "حاضر"
    assert members["rev"] == 2
    assert "06:30 مساءً" in _by_kind(later, "closing")["data"]["text"]
    assert _by_kind(later, "header")["rev"] == 1  # لم يتغير


def test_manual_edits_are_locked_against_sync() -> None:
    sections = S.sync_sections(None, _snap())
    members = _by_kind(sections, "members_table")
    edited = copy.deepcopy(members)
    edited["data"]["rows"][1]["status_label"] = "حاضر"  # الرئيس صحّح حالة عضو
    edited["data"]["rows"][1]["role_label"] = "عضو"  # و صفته
    sections, saved = S.apply_user_section_update(sections, edited)
    assert saved["rev"] == members["rev"] + 1
    assert set(saved["data"]["rows"][1]["locked"]) == {"status_label", "role_label"}

    # المزامنة لاحقًا لا تغيّر الخانات المقفلة — لكن آلية الحضور تتبع الحالة الجديدة.
    synced = S.sync_sections(sections, _snap())
    row = _by_kind(synced, "members_table")["data"]["rows"][1]
    assert (row["status_label"], row["role_label"], row["mode_label"]) == ("حاضر", "عضو", "عن بعد")


def test_unchanged_auto_values_do_not_lock() -> None:
    sections = S.sync_sections(None, _snap())
    header = copy.deepcopy(_by_kind(sections, "header"))
    _, saved = S.apply_user_section_update(sections, header)
    assert saved["data"]["locked"] == []
    assert saved["rev"] == header["rev"]  # لا تغيير ⇒ لا مراجعة جديدة


def test_deleted_auto_row_does_not_come_back_and_manual_rows_stay() -> None:
    sections = S.sync_sections(None, _snap())
    guests = copy.deepcopy(_by_kind(sections, "guests_table"))
    guests["data"]["rows"] = [{"name": "زائر يدوي", "mode_label": "حضوري", "role_label": "مستشار"}]
    sections, saved = S.apply_user_section_update(sections, guests)
    assert saved["data"]["removed_keys"] == ["g1"]
    manual = saved["data"]["rows"][0]
    assert manual["auto"] is False and manual["key"].startswith("manual:")

    synced = S.sync_sections(sections, _snap(guests=(S.GuestInfo("g1", "ضيف"), S.GuestInfo("g2", "ضيف ثاني"))))
    keys = [r["key"] for r in _by_kind(synced, "guests_table")["data"]["rows"]]
    assert "g1" not in keys and "g2" in keys and keys[-1].startswith("manual:")


def test_new_agenda_item_adds_topic_and_deleted_untouched_topic_disappears() -> None:
    sections = S.sync_sections(None, _snap())
    # كتابة حيثيات في الموضوع الأول (فيُعتبر "ملموس").
    first = copy.deepcopy(_topics(sections)[0])
    first["data"]["background"] = _doc("حيثيات مكتوبة")
    sections, _ = S.apply_user_section_update(sections, first)

    agenda = (S.AgendaInfo("a1", "الموازنة", 0), S.AgendaInfo("a3", "بند جديد", 1))  # a2 انحذف، a3 جديد
    synced = S.sync_sections(sections, _snap(agenda=agenda))
    topics = _topics(synced)
    assert [t["data"]["agenda_item_id"] for t in topics] == ["a1", "a3"]
    assert topics[1]["data"]["decision_number"] == "(2-6-2025)"

    # بند فيه كتابة وانحذف من جدول الأعمال ⇒ يبقى (ما نضيّع كتابة أحد).
    synced = S.sync_sections(synced, _snap(agenda=(S.AgendaInfo("a3", "بند جديد", 0),)))
    assert [t["data"]["agenda_item_id"] for t in _topics(synced)] == ["a3", "a1"]


def test_meeting_number_edit_flows_into_title_and_decisions() -> None:
    sections = S.sync_sections(None, _snap())
    title = copy.deepcopy(_by_kind(sections, "title"))
    title["data"]["meeting_number"] = 9
    sections, _ = S.apply_user_section_update(sections, title)
    synced = S.sync_sections(sections, _snap())
    assert _by_kind(synced, "title")["data"]["line2"] == "لجنة التقنية - الاجتماع التاسع لعام 2025م"
    assert [t["data"]["decision_number"] for t in _topics(synced)] == ["(1-9-2025)", "(2-9-2025)"]
    assert "التاسع" in _by_kind(synced, "signatures")["data"]["heading"]


def test_stale_rev_is_rejected() -> None:
    sections = S.sync_sections(None, _snap())
    stale = copy.deepcopy(_by_kind(sections, "header"))
    stale["rev"] = 0
    with pytest.raises(S.SectionConflictError) as exc:
        S.apply_user_section_update(sections, stale)
    assert exc.value.current["id"] == stale["id"]


def test_kind_cannot_change_and_unknown_section_rejected() -> None:
    sections = S.sync_sections(None, _snap())
    header = copy.deepcopy(_by_kind(sections, "header"))
    header["kind"] = "text"
    with pytest.raises(S.SectionsValidationError):
        S.apply_user_section_update(sections, header)
    with pytest.raises(S.SectionsValidationError):
        S.apply_user_section_update(sections, {"id": "nope", "kind": "text", "rev": 0})


def test_server_managed_fields_ignore_client_values() -> None:
    sections = S.sync_sections(None, _snap())
    topic = copy.deepcopy(_topics(sections)[0])
    topic["data"]["agenda_item_id"] = "hacked"
    topic["data"]["locked"] = ["heading"]
    _, saved = S.apply_user_section_update(sections, topic)
    assert saved["data"]["agenda_item_id"] == "a1"
    assert saved["data"]["locked"] == []


def test_full_save_deletes_topic_with_tombstone_and_keeps_meta() -> None:
    sections = S.sync_sections(None, _snap())
    second_topic = _topics(sections)[1]
    # الواجهة ترسل كل الأقسام كما استلمتها (بما فيها meta) — لازم ما يتكرر.
    incoming = [copy.deepcopy(s) for s in sections if s["id"] != second_topic["id"]]
    incoming.append({"id": "new", "kind": "rich", "title": "قسم", "data": {"content": _doc("ملاحظة")}})
    merged = S.merge_user_sections(sections, incoming)
    assert sum(1 for s in merged if s["kind"] == "meta") == 1
    meta = _by_kind(merged, "meta")
    assert meta["data"]["removed_topic_keys"] == ["a2"]
    assert any(s["kind"] == "rich" and s["data"]["role"] == "custom" for s in merged)
    assert [t["data"]["agenda_item_id"] for t in _topics(S.sync_sections(merged, _snap()))] == ["a1"]


def test_template_blocks_cannot_be_added_by_users() -> None:
    sections = S.sync_sections(None, _snap())
    with pytest.raises(S.SectionsValidationError):
        S.merge_user_sections(sections, sections + [{"id": "x", "kind": "members_table", "data": {}}])


# ============================== محتوى المحرر ==============================


def test_editor_content_whitelist() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "attrs": {"textAlign": "right", "onclick": "x"}, "content": [
                {"type": "text", "text": "نص", "marks": [{"type": "bold"}, {"type": "bold"}]},
            ]},
            {"type": "table", "content": [{"type": "tableRow", "content": [
                {"type": "tableHeader", "attrs": {"colspan": 2, "style": "x"}, "content": [{"type": "paragraph"}]},
            ]}]},
        ],
    }
    clean = validate_editor_doc(doc)
    assert clean["content"][0]["attrs"] == {"textAlign": "right"}
    assert clean["content"][0]["content"][0]["marks"] == [{"type": "bold"}]
    assert clean["content"][1]["content"][0]["content"][0]["attrs"] == {"colspan": 2}
    assert validate_editor_doc({"type": "doc", "content": [{"type": "paragraph"}]}) is None  # فارغ

    for bad in (
        {"type": "doc", "content": [{"type": "iframe"}]},
        {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "x", "marks": [{"type": "link"}]}]}]},
        {"type": "html", "content": []},
        {"type": "doc", "content": [{"type": "heading", "attrs": {"level": 9}}]},
    ):
        with pytest.raises(EditorContentError):
            validate_editor_doc(bad)


# ============================== التوقيع المحفوظ (تحقق) ==============================


def test_signature_image_validation() -> None:
    good = _png_data_url()
    assert user_signature_service.validate_signature_image(good) == good
    for bad in (
        "data:image/jpeg;base64,AAAA" + "A" * 40,
        "data:image/png;base64,@@@@" + "A" * 40,
        "data:image/png;base64," + base64.b64encode(b"not a png at all, sorry").decode(),
    ):
        with pytest.raises(user_signature_service.SignatureValidationError):
            user_signature_service.validate_signature_image(bad)


async def test_guest_accounts_cannot_have_saved_signature() -> None:
    guest = SimpleNamespace(is_guest=True, user_id=None)
    with pytest.raises(user_signature_service.SignatureForbiddenError):
        await user_signature_service.get_my_signature(None, actor=guest)  # type: ignore[arg-type]


# ============================== PDF ==============================


def test_pdf_builds_with_signature_page() -> None:
    sections = S.sync_sections(None, _snap(end_time=datetime(2025, 1, 16, 15, 0, tzinfo=UTC)))
    topic = _topics(sections)[0]
    topic["data"]["background"] = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Revenue 2024 A = -2,796,978.43"}]},
            {"type": "orderedList", "content": [{"type": "listItem", "content": [_doc("أولاً")["content"][0]]}]},
            {"type": "table", "content": [{"type": "tableRow", "content": [
                {"type": "tableCell", "attrs": {"colspan": 2}, "content": [_doc("خلية")["content"][0]]},
            ]}]},
        ],
    }
    pdf = build_general_minutes_pdf(
        GeneralMinutesPdfData(document_title="محضر", sections=sections, signatures={"chair": _png_data_url(120)})
    )
    reader = PdfReader(io.BytesIO(pdf))
    assert pdf.startswith(b"%PDF")
    assert len(reader.pages) >= 2  # التوقيعات بصفحة مستقلة
