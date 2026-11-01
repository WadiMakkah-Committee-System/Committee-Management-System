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

from app.core.background import run_detached
from app.core.config import settings
from app.core.dependencies import CurrentUser, oauth2_scheme
from app.core.security import InvalidTokenError, create_access_token, decode_token
from app.db.session import get_db
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    ResetPasswordRequest,
    TokenResponse,
    VerifyResetCodeRequest,
)
from app.api.v1.users import build_my_profile
from app.schemas.user import ChangePasswordRequest
from app.services import auth_service, notification_service, user_service
from app.services.auth_service import AuthError

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    try:
        # الملف الشخصي يُبنى داخل معاملة الدخول نفسها قبل commit (تحسين أداء
        # 2026-10-28 — راجعي auth_service.authenticate).
        user, access_token, refresh_token, profile = await auth_service.authenticate(
            db,
            username=payload.username,
            password=payload.password,
            before_commit=lambda u: build_my_profile(db, u),
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        must_change_password=user.must_change_password,
        user=profile,
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

    new_access_token = create_access_token(
        user.user_id, user.role.name if user.role else None, session_id
    )
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
    POST /auth/forgot-password — عام (بدون مصادقة). FR-UM-018.

    بدء تدفق نسيت كلمة المرور. يرجع 204 دائمًا (بريد موجود أم لا، حساب
    موقوف، أو طلب متكرر داخل مهلة إعادة الإرسال) لمنع تعداد عناوين البريد
    المسجَّلة (Email Enumeration).

    تحديث 2026-10-31: إرسال رمز OTP فعليًا بالبريد عبر run_detached بعد
    الـcommit (نفس نمط إشعارات الاجتماعات — راجعي core/background.py) حتى
    لا تنتظر الاستجابة مزوّد البريد، ولا يختلف زمنها بين بريد موجود وغير موجود.
    422: صيغة بريد غير صالحة.
    """
    result = await auth_service.request_password_reset(db, email=payload.email)
    if result is not None:
        user, otp_code = result
        run_detached(
            notification_service.notify_password_reset_code(
                email=user.email,
                first_name=user.first_name,
                otp_code=otp_code,
                expires_minutes=settings.PASSWORD_RESET_OTP_MINUTES,
            )
        )


@router.post("/verify-reset-code", status_code=status.HTTP_204_NO_CONTENT)
async def verify_reset_code(
    payload: VerifyResetCodeRequest, db: AsyncSession = Depends(get_db)
) -> None:
    """
    POST /auth/verify-reset-code — عام (بدون مصادقة). FR-UM-018.

    التحقق من رمز الاستعادة كخطوة مستقلة قبل إدخال كلمة المرور الجديدة.
    لا يستهلك الرمز (يبقى صالحًا لـ/reset-password).
    204: الرمز صحيح. 400: رسالة عامة موحّدة لكل حالات الفشل (تُحتسب
    المحاولة الخاطئة ضمن حد PASSWORD_RESET_MAX_ATTEMPTS). 422: صيغة غير صالحة.
    """
    try:
        await auth_service.verify_reset_code(db, email=payload.email, otp_code=payload.otp_code)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
) -> None:
    """
    POST /auth/reset-password — عام (بدون مصادقة). FR-UM-018.

    تعيين كلمة مرور جديدة بعد إعادة التحقق من الرمز، ثم إبطال كل جلسات
    المستخدم على كل الأجهزة. 204: نجاح. 400: رمز غير صالح (رسالة عامة).
    422: صيغة رمز غير صالحة أو كلمة مرور تخالف السياسة.
    """
    try:
        await auth_service.reset_password(
            db,
            email=payload.email,
            otp_code=payload.otp_code,
            new_password=payload.new_password,
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
