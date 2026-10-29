"""
انتفاخ الاستعلامات لوحدة الوثائق (إعادة هيكلة 2026-10-24): عدد استعلامات
SQL لقائمة الوثائق لا يكبر مع عدد الوثائق — كان فحص الرؤية يستعلم عن لجان
المستخدم لكل وثيقة مشتركة مع لجنة، وخيارات التحميل تجرّ شجرة اللجان
والمستخدمين وأدوارهم وصلاحياتهم لكل وثيقة (403 استعلامًا على بيانات القياس).
"""

from httpx import AsyncClient

from tests.test_documents import _create_approved_committee_with_member, _upload_document
from tests.test_meetings_query_budget import _count


async def _upload_shared(client, auth_headers, committee_id: str, member_id: str, how_many: int):
    for i in range(how_many):
        shared = (
            {"committee_ids": committee_id} if i % 2 == 0 else {"user_ids": member_id}
        )
        upload = await _upload_document(client, auth_headers, title=f"وثيقة {i}", **shared)
        assert upload.status_code == 201, upload.text


async def test_documents_list_query_count_does_not_grow_with_documents(
    client: AsyncClient, auth_headers, roles_by_name
) -> None:
    committee_id, member_headers, member_id = await _create_approved_committee_with_member(
        client, auth_headers, roles_by_name, slug="docbudget", name="لجنة قياس الوثائق"
    )

    await _upload_shared(client, auth_headers, committee_id, member_id, 2)
    few, few_body = await _count(client, "/api/v1/documents", member_headers)

    await _upload_shared(client, auth_headers, committee_id, member_id, 8)
    many, many_body = await _count(client, "/api/v1/documents", member_headers)

    assert len(few_body) == 2 and len(many_body) == 10
    assert many == few, f"list query count grew with item count: {few} -> {many}"
    assert many <= 10, f"documents list uses {many} SQL statements"
    committee_doc = next(d for d in many_body if d["visible_committees"])
    assert committee_doc["visible_committees"][0]["lifecycle_state"]
    assert committee_doc["uploader"]["user_id"]


async def test_document_detail_query_count_is_constant(
    client: AsyncClient, auth_headers, roles_by_name
) -> None:
    committee_id, member_headers, member_id = await _create_approved_committee_with_member(
        client, auth_headers, roles_by_name, slug="docdetail", name="لجنة تفاصيل الوثائق"
    )
    upload = await _upload_document(client, auth_headers, committee_ids=committee_id)
    document_id = upload.json()["document_id"]
    statements, body = await _count(client, f"/api/v1/documents/{document_id}", member_headers)
    assert body["visible_committees"][0]["committee_id"] == committee_id
    assert statements <= 10, f"document detail uses {statements} SQL statements"
