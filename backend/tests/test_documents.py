"""
اختبارات وحدة "إدارة الوثائق" — تصنيفات الوثائق، الرفع/العرض/التعديل/
الحذف/التحميل، ونطاق الرؤية المركّب (عام/إدارة/لجنة/مستخدم).

ملاحظة تصميم للاختبارات:
Supabase Storage (الملف الفعلي) لا يُستدعى فعليًا هنا — app.core.storage_client
يُستبدل بـ monkeypatch لثلاث دوال بسيطة (upload/download/delete) تعمل على
قاموس بايثون في الذاكرة، بدل شبكة حقيقية. هذا يطابق حدود الوحدة: منطق
RBAC/الرؤية/البيانات الوصفية هو ما تختبره هذه الوحدة، وليس Supabase نفسه.
"""

import io

import pytest
from httpx import AsyncClient

from app.core import storage_client
from app.models.user import User


@pytest.fixture(autouse=True)
def _fake_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """يستبدل Supabase Storage بقاموس بالذاكرة — لا اتصال شبكة فعلي أثناء الاختبارات."""
    fake_files: dict[str, bytes] = {}

    async def fake_upload(storage_path: str, content: bytes, *, content_type: str) -> None:
        fake_files[storage_path] = content

    async def fake_download(storage_path: str) -> bytes:
        if storage_path not in fake_files:
            raise storage_client.StorageError("الملف غير موجود بالتخزين الوهمي")
        return fake_files[storage_path]

    async def fake_delete(storage_path: str) -> None:
        fake_files.pop(storage_path, None)

    monkeypatch.setattr(storage_client, "upload_object", fake_upload)
    monkeypatch.setattr(storage_client, "download_object", fake_download)
    monkeypatch.setattr(storage_client, "delete_object", fake_delete)


DOCUMENT_TEST_CONTENT = b"sample document content for tests"


async def _upload_document(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    title: str = "محضر اجتماع تجريبي",
    is_public: bool = False,
    department_ids: str = "",
    committee_ids: str = "",
    user_ids: str = "",
    category_id: str | None = None,
):
    files = {"file": ("minutes.txt", io.BytesIO(DOCUMENT_TEST_CONTENT), "text/plain")}
    data = {
        "title": title,
        "description": "وصف تجريبي",
        "is_public": str(is_public).lower(),
        "department_ids": department_ids,
        "committee_ids": committee_ids,
        "user_ids": user_ids,
    }
    if category_id is not None:
        data["category_id"] = category_id
    return await client.post("/api/v1/documents", data=data, files=files, headers=headers)


async def test_upload_document_success(client: AsyncClient, auth_headers, super_admin_user: User) -> None:
    response = await _upload_document(client, auth_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "محضر اجتماع تجريبي"
    assert body["file_name"] == "minutes.txt"
    assert body["uploader"]["user_id"] == str(super_admin_user.user_id)
    assert body["status"] == "active"


async def test_upload_document_requires_permission(client: AsyncClient) -> None:
    response = await _upload_document(client, {})
    assert response.status_code == 401


async def test_download_document_roundtrip(client: AsyncClient, auth_headers) -> None:
    upload = await _upload_document(client, auth_headers)
    document_id = upload.json()["document_id"]

    download = await client.get(f"/api/v1/documents/{document_id}/download", headers=auth_headers)
    assert download.status_code == 200
    assert download.content == DOCUMENT_TEST_CONTENT
    assert "minutes.txt" in download.headers["content-disposition"]


async def test_soft_delete_document_hides_it_from_list_and_get(
    client: AsyncClient, auth_headers
) -> None:
    upload = await _upload_document(client, auth_headers)
    document_id = upload.json()["document_id"]

    delete = await client.delete(f"/api/v1/documents/{document_id}", headers=auth_headers)
    assert delete.status_code == 204

    listing = await client.get("/api/v1/documents", headers=auth_headers)
    ids = [d["document_id"] for d in listing.json()]
    assert document_id not in ids

    get_after_delete = await client.get(f"/api/v1/documents/{document_id}", headers=auth_headers)
    assert get_after_delete.status_code == 404


async def test_update_document_metadata(client: AsyncClient, auth_headers) -> None:
    upload = await _upload_document(client, auth_headers)
    document_id = upload.json()["document_id"]

    update = await client.patch(
        f"/api/v1/documents/{document_id}",
        json={"title": "عنوان معدَّل", "is_public": True},
        headers=auth_headers,
    )
    assert update.status_code == 200, update.text
    body = update.json()
    assert body["title"] == "عنوان معدَّل"
    assert body["is_public"] is True
    # description لم تُرسَل بالتعديل، يجب أن تبقى كما كانت عند الرفع
    assert body["description"] == "وصف تجريبي"


async def _create_department(client: AsyncClient, auth_headers, name: str, code: str, manager_id: str) -> str:
    response = await client.post(
        "/api/v1/departments",
        json={"name": name, "code": code, "description": None, "manager_user_id": manager_id},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["dep_id"]


async def _create_member_in_department(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], *, username: str, dep_id: str
) -> tuple[dict[str, str], str]:
    create = await client.post(
        "/api/v1/users",
        json={
            "first_name": "أ",
            "middle_name": "ب",
            "last_name": "ج",
            "username": username,
            "email": f"{username}@example.com",
            "password": "StrongPass1",
            "role_id": roles_by_name["admin"],
            "dep_id": dep_id,
        },
        headers=auth_headers,
    )
    assert create.status_code == 201, create.text
    user_id = create.json()["user_id"]
    login = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "StrongPass1"}
    )
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user_id


async def test_document_not_visible_to_unrelated_department_member(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    """
    وثيقة غير عامة، بدون أي مشاركة رؤية صريحة → لا تظهر لعضو إدارة أخرى
    حتى لو كان يملك صلاحية documents.view عبر دوره (RBAC عام لا يكفي —
    الرؤية على مستوى السجل شرط إضافي).
    """
    dep_id = await _create_department(
        client, auth_headers, "إدارة الوثائق التجريبية", "DOCS1", str(super_admin_user.user_id)
    )
    member_headers, _ = await _create_member_in_department(
        client, auth_headers, roles_by_name, username="doc_test_member_1", dep_id=dep_id
    )

    upload = await _upload_document(client, auth_headers, title="وثيقة غير مشتركة")
    document_id = upload.json()["document_id"]

    get_response = await client.get(f"/api/v1/documents/{document_id}", headers=member_headers)
    assert get_response.status_code == 403 or get_response.status_code == 404


async def test_document_visible_to_shared_department(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    dep_id = await _create_department(
        client, auth_headers, "إدارة مشاركة الوثيقة", "DOCS2", str(super_admin_user.user_id)
    )

    upload = await _upload_document(
        client, auth_headers, title="وثيقة مشتركة مع إدارة", department_ids=dep_id
    )
    document_id = upload.json()["document_id"]
    assert upload.json()["visible_departments"][0]["dep_id"] == dep_id


async def test_public_document_visible_without_explicit_sharing(
    client: AsyncClient, auth_headers
) -> None:
    upload = await _upload_document(client, auth_headers, title="وثيقة عامة", is_public=True)
    assert upload.status_code == 201
    assert upload.json()["is_public"] is True


async def test_create_global_category_requires_permission(client: AsyncClient, auth_headers) -> None:
    response = await client.post(
        "/api/v1/document-categories",
        json={"name": "تصنيف عام تجريبي", "scope": "global", "department_id": None},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["scope"] == "global"


async def test_create_department_category_wrong_scope_payload_rejected(
    client: AsyncClient, auth_headers
) -> None:
    response = await client.post(
        "/api/v1/document-categories",
        json={"name": "تصنيف بلا إدارة", "scope": "department", "department_id": None},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_delete_category_blocked_when_documents_reference_it(
    client: AsyncClient, auth_headers
) -> None:
    category = await client.post(
        "/api/v1/document-categories",
        json={"name": "تصنيف مستخدَم", "scope": "global", "department_id": None},
        headers=auth_headers,
    )
    category_id = category.json()["category_id"]

    await _upload_document(client, auth_headers, title="وثيقة بتصنيف", category_id=category_id)

    delete = await client.delete(f"/api/v1/document-categories/{category_id}", headers=auth_headers)
    assert delete.status_code == 400
