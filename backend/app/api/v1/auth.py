"""
الهدف:
راوتات المصادقة — تسجيل الدخول/الخروج، تجديد التوكن، تغيير كلمة المرور،
ونسيت كلمة المرور (FR-UM-011 → FR-UM-020).

المسؤولية:
تحويل طلبات HTTP إلى استدعاءات لـ auth_service، وترجمة أخطاء العمل
(AuthError) إلى استجابات HTTP مناسبة (401/400).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, oauth2_scheme
from app.core.security import InvalidTokenError, create_access_token, decode_token
from app.db.session import get_db
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.schemas.user import ChangePasswordRequest
from app.services import auth_service, user_service
from app.services.auth_service import AuthError

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    try:
        user, access_token, refresh_token = await auth_service.authenticate(
            db, username=payload.username, password=payload.password
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        must_change_password=user.must_change_password,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """إصدار Access Token جديد باستخدام Refresh Token صالح."""
    try:
        token_payload = decode_token(payload.refresh_token, expected_type="refresh")
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh Token غير صالح"
        ) from exc

    from app.core.redis_client import is_session_valid

    session_id = token_payload.get("sid")
    if session_id is None or not await is_session_valid(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="انتهت صلاحية الجلسة"
        )

    user = await user_service.get_user(db, token_payload["sub"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="مستخدم غير موجود")

    new_access_token = create_access_token(user.user_id, user.role.value, session_id)
    return TokenResponse(
        access_token=new_access_token,
        refresh_token=payload.refresh_token,
        must_change_password=user.must_change_password,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(token: str = Depends(oauth2_scheme)) -> None:
    """تسجيل الخروج — إبطال الجلسة الحالية فورًا."""
    try:
        payload = decode_token(token, expected_type="access")
    except InvalidTokenError:
        return  # التوكن غير صالح أصلًا — لا شيء لإبطاله
    session_id = payload.get("sid")
    if session_id:
        await auth_service.logout(session_id)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await auth_service.change_password(
            db,
            user=current_user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
) -> None:
    """
    بدء تدفق نسيت كلمة المرور. يرجع 204 دائمًا (سواء وُجد البريد أم لا)
    لمنع تعداد عناوين البريد المسجَّلة (Email Enumeration).
    إرسال رمز OTP فعليًا عبر البريد مهمة لاحقة (تكامل SMTP).
    """
    await auth_service.request_password_reset(db, email=payload.email)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
) -> None:
    try:
        await auth_service.reset_password(
            db,
            email=payload.email,
            otp_code=payload.otp_code,
            new_password=payload.new_password,
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
