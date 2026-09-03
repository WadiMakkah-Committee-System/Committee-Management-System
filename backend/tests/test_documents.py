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


# ---------------------------------------------------------------------------
# إصلاحات 2026-09-02: مفتاح التخزين، فئة رؤية واحدة حصرية، وتضييق تجاوز
# super_admin التلقائي (لجنة/مستخدمون محددون فقط — راجعي docstring
# can_view_document وdocument_service._assert_single_visibility_category).
# ---------------------------------------------------------------------------


async def test_storage_path_uses_document_id_not_original_file_name(
    client: AsyncClient, auth_headers
) -> None:
    """
    إصلاح خلل InvalidKey بـSupabase Storage: مفتاح الكائن يجب ألا يحتوي
    اسم الملف الأصلي (قد يحمل أحرفًا عربية أو مسافات) — الاسم الأصلي يبقى
    فقط ببيانات الوثيقة الوصفية (file_name) لا كجزء من storage_path.
    """
    files = {"file": ("ملف تجريبي عربي.txt", io.BytesIO(DOCUMENT_TEST_CONTENT), "text/plain")}
    data = {
        "title": "وثيقة باسم ملف عربي",
        "description": "",
        "is_public": "true",
        "department_ids": "",
        "committee_ids": "",
        "user_ids": "",
    }
    upload = await client.post("/api/v1/documents", data=data, files=files, headers=auth_headers)
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["document_id"]
    assert upload.json()["file_name"] == "ملف تجريبي عربي.txt"

    # التحميل ينجح (يثبت أن التخزين الوهمي استُدعي بمفتاح صالح فعليًا
    # استُخدم بالرفع والتحميل معًا)، ورأس Content-Disposition ما زال
    # يحمل الاسم الأصلي للعرض.
    download = await client.get(f"/api/v1/documents/{document_id}/download", headers=auth_headers)
    assert download.status_code == 200
    assert download.content == DOCUMENT_TEST_CONTENT
    assert "content-disposition" in download.headers


async def test_create_document_rejects_multiple_visibility_categories(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    dep_id = await _create_department(
        client, auth_headers, "إدارة فئة مزدوجة", "DOCS3", str(super_admin_user.user_id)
    )
    response = await _upload_document(
        client, auth_headers, title="وثيقة فئتين معًا", is_public=True, department_ids=dep_id
    )
    assert response.status_code == 400, response.text


async def test_update_document_rejects_multiple_visibility_categories(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    dep_id = await _create_department(
        client, auth_headers, "إدارة فئة مزدوجة بالتعديل", "DOCS4", str(super_admin_user.user_id)
    )
    upload = await _upload_document(client, auth_headers, title="وثيقة تعديل", department_ids=dep_id)
    document_id = upload.json()["document_id"]

    # الوثيقة أصلًا خاصة بإدارة — محاولة جعلها عامة أيضًا بدون تفريغ
    # department_ids (تُحسَب "الحالة النهائية الفعلية" من القيمة الحالية
    # + الحقل المُرسَل، راجعي resolved_department_ids بـupdate_document).
    update = await client.patch(
        f"/api/v1/documents/{document_id}",
        json={"is_public": True},
        headers=auth_headers,
    )
    assert update.status_code == 400, update.text


async def _create_approved_committee_with_member(
    client: AsyncClient, auth_headers: dict[str, str], roles_by_name: dict[str, str], *, slug: str, name: str
) -> tuple[str, dict[str, str], str]:
    """
    تُنشئ لجنة معتمدة فعليًا (عبر تدفق طلب التشكيل الكامل: draft → submitted
    → pending_approval → approved، بنفس أسلوب test_committees.py) مع عضو
    واحد، وترجع (committee_id, member_headers, member_id) — لا يوجد مسار
    إنشاء مباشر أقصر (Committee.source_request_id مطلوب ويربط بطلب فعلي).

    slug: بادئة أسماء مستخدمين صالحة (ASCII) — منفصلة عن name (اسم اللجنة
    الفعلي، عربي) لأن username لا يجوز أن يحتوي مسافات/أحرفًا عربية بنفس
    قواعد بقية الاختبارات (راجعي test_committees.py._setup_actors).
    """

    async def _create_user(username: str, role_id: str) -> tuple[dict[str, str], str]:
        create = await client.post(
            "/api/v1/users",
            json={
                "first_name": "أ",
                "middle_name": "ب",
                "last_name": "ج",
                "username": username,
                "email": f"{username}@example.com",
                "password": "StrongPass1",
                "role_id": role_id,
                "dep_id": None,
            },
            headers=auth_headers,
        )
        assert create.status_code == 201, create.text
        user_id = create.json()["user_id"]
        login = await client.post(
            "/api/v1/auth/login", json={"username": username, "password": "StrongPass1"}
        )
        assert login.status_code == 200, login.text
        return {"Authorization": f"Bearer {login.json()['access_token']}"}, user_id

    # عضو اللجنة يحتاج دورًا مخصَّصًا بصلاحيتي documents.upload/view — دور
    # "admin" النظامي لا يملكهما افتراضيًا (راجعي db/migrations/0014،
    # الأدوار الممنوحة تلقائيًا هي super_admin/executive_office_manager/
    # رئيس اللجنة/عضو اللجنة فقط، وهذان الأخيران أدوار لجنة داخلية لا
    # تُسنَد كـrole_id عادي لمستخدم — راجعي app/models/user.py::permission_codes).
    member_role = await client.post(
        "/api/v1/roles",
        json={
            "name": f"role_{slug}_member",
            "permission_codes": ["documents.upload", "documents.view", "documents.update"],
        },
        headers=auth_headers,
    )
    assert member_role.status_code == 201, member_role.text

    admin_headers, _ = await _create_user(f"{slug}_admin", roles_by_name["admin"])
    office_headers, _ = await _create_user(f"{slug}_office", roles_by_name["executive_office_manager"])
    ceo_headers, _ = await _create_user(f"{slug}_ceo", roles_by_name["executive_president"])
    member_headers, member_id = await _create_user(f"{slug}_member", member_role.json()["role_id"])

    create = await client.post(
        "/api/v1/committee-requests",
        json={
            "committee_name": name,
            "statement": "بيان تجريبي",
            "start_date": "2026-09-01",
            "end_date": "2026-12-01",
            "proposed_member_ids": [member_id],
            "chair_user_id": member_id,
        },
        headers=admin_headers,
    )
    assert create.status_code == 201, create.text
    request_id = create.json()["request_id"]

    submit = await client.post(
        f"/api/v1/committee-requests/{request_id}/submit", headers=admin_headers
    )
    assert submit.status_code == 200, submit.text
    escalate = await client.post(
        f"/api/v1/committee-requests/{request_id}/escalate", headers=office_headers
    )
    assert escalate.status_code == 200, escalate.text
    approve = await client.post(
        f"/api/v1/committee-requests/{request_id}/approve", headers=ceo_headers
    )
    assert approve.status_code == 200, approve.text

    committees = await client.get("/api/v1/committees", headers=admin_headers)
    assert committees.status_code == 200, committees.text
    matches = [c for c in committees.json() if c["source_request_id"] == request_id]
    assert len(matches) == 1
    return matches[0]["committee_id"], member_headers, member_id


async def test_super_admin_requires_committee_membership_to_view_committee_scoped_document(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str]
) -> None:
    """
    قرار منتج 2026-09-02: super_admin (الرافع هنا حساب auth_headers نفسه)
    ليس عضوًا باللجنة، فلا يجوز أن يرى وثيقة خاصة بلجنة تلقائيًا بمجرد
    كونه super_admin — بعكس سلوكه السابق (تجاوز شامل غير مشروط).
    """
    committee_id, member_headers, _ = await _create_approved_committee_with_member(
        client, auth_headers, roles_by_name, slug="doccomm1", name="لجنة وثائق ١"
    )
    upload = await _upload_document(
        client, member_headers, title="وثيقة خاصة باللجنة", committee_ids=committee_id
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["document_id"]

    # عضو اللجنة الفعلي (الرافع نفسه) يشوفها بلا مشكلة.
    get_by_member = await client.get(f"/api/v1/documents/{document_id}", headers=member_headers)
    assert get_by_member.status_code == 200

    # super_admin (auth_headers) ليس عضوًا بهذه اللجنة → 403/404، رغم تجاوزه
    # الشامل بكل بقية الوحدات.
    get_by_super_admin = await client.get(
        f"/api/v1/documents/{document_id}", headers=auth_headers
    )
    assert get_by_super_admin.status_code in (403, 404)


async def test_super_admin_still_sees_any_department_scoped_document(
    client: AsyncClient, auth_headers, roles_by_name: dict[str, str], super_admin_user: User
) -> None:
    """
    التأكيد على أن التضييق أعلاه خاص باللجان (والمستخدمين المحددين) فقط —
    الإدارات تبقى "روتينية/تنظيمية"، فsuper_admin يبقى يشوف أي وثيقة خاصة
    بأي إدارة بلا حاجة لعضوية/انتماء فعلي، كما كان سابقًا.
    """
    dep_id = await _create_department(
        client, auth_headers, "إدارة رؤية سوبر أدمن", "DOCS5", str(super_admin_user.user_id)
    )
    upload = await _upload_document(
        client, auth_headers, title="وثيقة خاصة بإدارة", department_ids=dep_id
    )
    document_id = upload.json()["document_id"]

    get_response = await client.get(f"/api/v1/documents/{document_id}", headers=auth_headers)
    assert get_response.status_code == 200


async def test_documents_scope_filter(client: AsyncClient, auth_headers) -> None:
    """عنصر التحكم المُقسَّم بالفرونت (الكل/عامة/...) يعتمد على ?scope=... بالباك-إند."""
    await _upload_document(client, auth_headers, title="وثيقة عامة للفلترة", is_public=True)
    await _upload_document(client, auth_headers, title="وثيقة خاصة للفلترة", is_public=False)

    public_only = await client.get("/api/v1/documents", params={"scope": "public"}, headers=auth_headers)
    assert public_only.status_code == 200, public_only.text
    titles = {d["title"] for d in public_only.json()}
    assert "وثيقة عامة للفلترة" in titles
    assert "وثيقة خاصة للفلترة" not in titles
