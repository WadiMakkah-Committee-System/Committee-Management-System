"""
الهدف:
راوتات "توقيعي" — التوقيع المحفوظ للمستخدم الحالي، يُستخدم للتوقيع على المحاضر
بدل رسمه كل مرة (القالب العام للمحاضر — قرار صاحب المشروع 2026-11-15).

قواعد الوصول:
- أي مستخدم مسجّل الدخول، على توقيعه هو فقط — المعرّف من التوكن وليس من الطلب
  (لا يوجد أي مسار يقرأ توقيع مستخدم آخر).
- حسابات الضيوف: 403.

المسؤولية: تحويل الطلبات لـuser_signature_service وترجمة أخطائها.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.user_signature import SavedSignatureIn, SavedSignatureOut
from app.services import user_signature_service

router = APIRouter(prefix="/users/me/signature", tags=["Users"])


def _forbidden(exc: Exception) -> HTTPException:
    """403 برسالة الخدمة."""
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.get("", response_model=SavedSignatureOut)
async def get_my_saved_signature(current_user: CurrentUser, db: AsyncSession = Depends(get_db)) -> SavedSignatureOut:
    """
    GET /users/me/signature — توقيعي المحفوظ.
    - 200: الصورة ووقت آخر تحديث. - 404: ما عندي توقيع محفوظ. - 403: حساب ضيف.
    """
    try:
        saved = await user_signature_service.get_my_signature(db, actor=current_user)
    except user_signature_service.SignatureForbiddenError as exc:
        raise _forbidden(exc) from exc
    if saved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="لا يوجد توقيع محفوظ")
    return SavedSignatureOut(signature_image=saved.signature_image, updated_at=saved.updated_at)


@router.put("", response_model=SavedSignatureOut)
async def save_my_signature(
    payload: SavedSignatureIn, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> SavedSignatureOut:
    """
    PUT /users/me/signature — حفظ/استبدال توقيعي (يُرسم من صفحة الملف الشخصي).
    - 200: التوقيع المحفوظ. - 400: صورة غير صالحة. - 403: حساب ضيف.
    التأثيرات: يكتب user_saved_signatures + سجل تدقيق.
    """
    try:
        saved = await user_signature_service.save_my_signature(
            db, actor=current_user, signature_image=payload.signature_image
        )
    except user_signature_service.SignatureValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except user_signature_service.SignatureForbiddenError as exc:
        raise _forbidden(exc) from exc
    return SavedSignatureOut(signature_image=saved.signature_image, updated_at=saved.updated_at)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_saved_signature(current_user: CurrentUser, db: AsyncSession = Depends(get_db)) -> Response:
    """
    DELETE /users/me/signature — حذف توقيعي المحفوظ.
    - 204: انحذف. - 404: ما كان عندي توقيع. - 403: حساب ضيف.
    المحاضر اللي وقّعتها سابقًا لا تتأثر (التوقيع منسوخ فيها).
    """
    try:
        deleted = await user_signature_service.delete_my_signature(db, actor=current_user)
    except user_signature_service.SignatureForbiddenError as exc:
        raise _forbidden(exc) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="لا يوجد توقيع محفوظ")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
