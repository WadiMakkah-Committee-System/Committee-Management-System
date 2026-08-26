"""
الهدف:
راوترات وحدة "إدارة الوثائق" — تصنيفات الوثائق (/document-categories)
والوثائق نفسها (/documents: رفع/عرض/تعديل/حذف/تحميل).

ملاحظات:
- رفع الملف (POST /documents) عبر multipart/form-data (UploadFile + Form)
  وليس JSON — الملف الفعلي يمر بالكامل عبر هذا الـ Backend ثم يُخزَّن في
    Supabase Storage (app.core.storage_client)، بدل روابط موقّعة تُعطى
      للعميل مباشرة (قرار عمل موثّق — راجع docstring storage_client.py).
      - صلاحيات تصنيفات الوثائق (document_categories.*) مقسّمة إلى
        create/update/delete × global/department — الفحص هنا يعتمد على نطاق
          التصنيف الفعلي (المُرسَل بالإنشاء أو المخزَّن بالتعديل/الحذف)، لذلك لا
            يمكن فرضه عبر dependencies=[require_permission(...)] الثابت في الديكور
              كبقية الراوترات، ويُفحص يدويًا داخل كل Route.
              - صلاحيات documents.view / documents.search أيّهما كافٍ لعرض/البحث في
                القائمة (require_permission تقبل أكثر من كود وتكتفي بواحد)؛
                  documents.search_content تتحكم فقط في هل يشمل البحث محتوى الوثيقة
                    (content_text) أو العنوان/الوصف فقط.
                    """

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage_client
from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.models.user import User
from app.schemas.document import (
    DocumentCategoryCreate,
    DocumentCategoryOut,
    DocumentCategoryUpdate,
    DocumentOut,
    DocumentUpdate,
)
from app.services import document_service

router = APIRouter(prefix="/documents", tags=["Documents"])
categories_router = APIRouter(prefix="/document-categories", tags=["Document Categories"])


def _parse_uuid_csv(value: str | None) -> list[uuid.UUID]:
      """يحوّل قائمة UUIDs مفصولة بفواصل (من حقل Form نصي) إلى list[UUID]. قيمة فارغة → []."""
      if not value or not value.strip():
                return []
            try:
                      return [uuid.UUID(item.strip()) for item in value.split(",") if item.strip()]
except ValueError as exc:
        raise HTTPException(
                      status_code=status.HTTP_400_BAD_REQUEST, detail="معرّف غير صالح ضمن قوائم الرؤية"
        ) from exc


def _require_category_permission(current_user: User, *, scope: str, action: str) -> None:
      if current_user.role.is_super_admin:
                return
            suffix = "global" if scope == "global" else "department"
    code = f"document_categories.{action}_{suffix}"
    if code not in current_user.role.permission_codes:
              raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN, detail="ليست لديك صلاحية للقيام بهذا الإجراء"
              )


def _storage_error_to_http(exc: storage_client.StorageError) -> HTTPException:
      if isinstance(exc, storage_client.StorageNotConfiguredError):
                return HTTPException(
                              status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                              detail="خدمة تخزين الملفات غير مُهيّأة بعد (راجع إعدادات SUPABASE_* بالبيئة)",
                )
            return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


# ---------------------------------------------------------------------------
# تصنيفات الوثائق
# ---------------------------------------------------------------------------


@categories_router.get(
      "",
      response_model=list[DocumentCategoryOut],
      dependencies=[Depends(require_permission("documents.view", "documents.upload"))],
)
async def list_document_categories(
      current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[DocumentCategoryOut]:
      categories = await document_service.list_categories(db, current_user=current_user)
    return [DocumentCategoryOut.model_validate(c) for c in categories]


@categories_router.post("", response_model=DocumentCategoryOut, status_code=status.HTTP_201_CREATED)
async def create_document_category(
      payload: DocumentCategoryCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> DocumentCategoryOut:
      _require_category_permission(current_user, scope=payload.scope, action="create")
    try:
              category = await document_service.create_category(
                            db,
                            actor=current_user,
                            name=payload.name,
                            scope=payload.scope,
                            department_id=payload.department_id,
              )
except document_service.DocumentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DocumentCategoryOut.model_validate(category)


@categories_router.patch("/{category_id}", response_model=DocumentCategoryOut)
async def update_document_category(
      category_id: uuid.UUID,
      payload: DocumentCategoryUpdate,
      current_user: CurrentUser,
      db: AsyncSession = Depends(get_db),
) -> DocumentCategoryOut:
      existing = await document_service.get_category(db, category_id)
      if existing is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="التصنيف غير موجود")
            _require_category_permission(current_user, scope=existing.scope, action="update")
    try:
              category = await document_service.update_category(
                            db, actor=current_user, category_id=category_id, name=payload.name
              )
except document_service.DocumentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if category is None:
              raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="التصنيف غير موجود")
          return DocumentCategoryOut.model_validate(category)


@categories_router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document_category(
      category_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
      existing = await document_service.get_category(db, category_id)
    if existing is None:
              raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="التصنيف غير موجود")
          _require_category_permission(current_user, scope=existing.scope, action="delete")
    try:
              category = await document_service.delete_category(
                            db, actor=current_user, category_id=category_id
              )
except document_service.DocumentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if category is None:
              raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="التصنيف غير موجود")


# ---------------------------------------------------------------------------
# الوثائق
# ---------------------------------------------------------------------------


@router.get(
      "",
      response_model=list[DocumentOut],
      dependencies=[Depends(require_permission("documents.view", "documents.search"))],
)
async def list_documents(
      current_user: CurrentUser,
      q: str | None = None,
      category_id: uuid.UUID | None = None,
      db: AsyncSession = Depends(get_db),
) -> list[DocumentOut]:
      can_search_content = current_user.role.is_super_admin or (
                "documents.search_content" in current_user.role.permission_codes
      )
      documents = await document_service.list_documents(
          db,
          current_user=current_user,
          q=q,
          category_id=category_id,
          can_search_content=can_search_content,
      )
      return [DocumentOut.model_validate(d) for d in documents]


@router.post(
      "",
      response_model=DocumentOut,
      status_code=status.HTTP_201_CREATED,
      dependencies=[Depends(require_permission("documents.upload"))],
)
async def upload_document(
      current_user: CurrentUser,
      file: UploadFile = File(...),
      title: str = Form(..., min_length=2, max_length=255),
      description: str | None = Form(None),
      category_id: uuid.UUID | None = Form(None),
      is_public: bool = Form(False),
      department_ids: str = Form(""),
      committee_ids: str = Form(""),
      user_ids: str = Form(""),
      db: AsyncSession = Depends(get_db),
) -> DocumentOut:
      content = await file.read()
      try:
                document = await document_service.create_document(
                              db,
                              actor=current_user,
                              title=title,
                              description=description,
                              category_id=category_id,
                              is_public=is_public,
                              department_ids=_parse_uuid_csv(department_ids),
                              committee_ids=_parse_uuid_csv(committee_ids),
                              user_ids=_parse_uuid_csv(user_ids),
                              file_name=file.filename or "unnamed",
                              mime_type=file.content_type or "application/octet-stream",
                              content=content,
                )
except document_service.DocumentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
except storage_client.StorageError as exc:
        raise _storage_error_to_http(exc) from exc
    return DocumentOut.model_validate(document)


@router.get(
      "/{document_id}",
      response_model=DocumentOut,
      dependencies=[Depends(require_permission("documents.view"))],
)
async def get_document(
      document_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> DocumentOut:
      document = await document_service.get_document(
                db, current_user=current_user, document_id=document_id
      )
      if document is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الوثيقة غير موجودة")
            return DocumentOut.model_validate(document)


@router.patch(
      "/{document_id}",
      response_model=DocumentOut,
      dependencies=[Depends(require_permission("documents.update"))],
)
async def update_document(
      document_id: uuid.UUID,
      payload: DocumentUpdate,
      current_user: CurrentUser,
      db: AsyncSession = Depends(get_db),
) -> DocumentOut:
      try:
                document = await document_service.update_document(
                              db,
                              actor=current_user,
                              document_id=document_id,
                              title=payload.title,
                              description=payload.description,
                              category_id=payload.category_id,
                              is_public=payload.is_public,
                              department_ids=payload.department_ids,
                              committee_ids=payload.committee_ids,
                              user_ids=payload.user_ids,
                              category_explicitly_set="category_id" in payload.model_fields_set,
                )
except document_service.DocumentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if document is None:
              raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الوثيقة غير موجودة")
          return DocumentOut.model_validate(document)


@router.delete(
      "/{document_id}",
      status_code=status.HTTP_204_NO_CONTENT,
      dependencies=[Depends(require_permission("documents.delete"))],
)
async def delete_document(
      document_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
      document = await document_service.delete_document(
          db, actor=current_user, document_id=document_id
)
    if document is None:
              raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الوثيقة غير موجودة")


@router.get(
      "/{document_id}/download",
      dependencies=[Depends(require_permission("documents.download"))],
)
async def download_document(
      document_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> Response:
      try:
                result = await document_service.download_document(
                              db, current_user=current_user, document_id=document_id
                )
except storage_client.StorageError as exc:
        raise _storage_error_to_http(exc) from exc
    if result is None:
              raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الوثيقة غير موجودة")
          document, content = result
    return Response(
              content=content,
              media_type=document.mime_type,
              headers={"Content-Disposition": f'attachment; filename="{document.file_name}"'},
    )
