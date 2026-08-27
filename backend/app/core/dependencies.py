"""
الهدف:
فرض الهوية (Authentication) والصلاحيات (Authorization/RBAC) على مستوى
الـ Backend حصرًا، حسب القاعدة الأمنية الأساسية في CLAUDE.md: "لا تثق أبدًا
بأي دور أو معرّف هوية قادم من العميل" — كل طلب محمي يُعاد التحقق من هويته
ودوره من قاعدة البيانات مباشرة، وليس فقط من محتوى التوكن.

المسؤولية:
- get_current_user: استخراج المستخدم الحالي من Access Token + التحقق من
  أن الجلسة ما زالت صالحة في Redis (لم تُبطَل ولم تنتهِ بسبب الخمول) +
  التحقق من أن الحساب ما زال نشطًا وغير محذوف في قاعدة البيانات.
- require_roles: مصنع Dependencies يُستخدم لتقييد راوت معيّن بأدوار محددة
  فقط (مثال: عمليات المستخدمين مقصورة على super_admin).

ملاحظات أمنية:
- التوكن يحمل role كـ "تلميح" فقط لتسريع الواجهة — لكن هنا نُعيد جلب
  المستخدم ودوره الفعلي من قاعدة البيانات بدل الاعتماد على قيمة role
  المخزّنة داخل التوكن، تحسبًا لأي تغيير دور حدث بعد إصدار التوكن.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import is_session_valid, touch_session
from app.core.security import InvalidTokenError, decode_token
from app.db.session import get_db
from app.models.user import User, UserStatus
from app.services import user_service

# tokenUrl فقط للتوثيق التفاعلي (Swagger) — لا يُستخدم فعليًا كمصدر للتحقق
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    استخراج المستخدم الحالي من Access Token، مع طبقات تحقق متعددة:
    1) صحة توقيع/صلاحية JWT نفسه.
    2) أن الجلسة (session_id) ما زالت موجودة في Redis (لم تُبطَل بتسجيل
       خروج، ولم تنتهِ بسبب الخمول).
    3) أن الحساب ما زال موجودًا (غير محذوف) ونشطًا (غير موقوف) في القاعدة.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="بيانات الاعتماد غير صالحة",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(token, expected_type="access")
    except InvalidTokenError as exc:
        raise unauthorized from exc

    session_id: str | None = payload.get("sid")
    if session_id is None or not await is_session_valid(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="انتهت صلاحية الجلسة، يرجى تسجيل الدخول مرة أخرى",
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise unauthorized

    user = await user_service.get_user(db, user_id)
    if user is None:
        raise unauthorized

    if user.status == UserStatus.suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="الحساب موقوف"
        )

    # تجديد مدة الجلسة (Sliding Expiration) عند كل طلب ناجح
    await touch_session(session_id)

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(*required_codes: str):
    """
    مصنع Dependency لتقييد راوت بصلاحية (أو أكثر) محددة من كتالوج الصلاحيات
    الديناميكي — بدل قائمة أدوار ثابتة في الكود. الصلاحيات الفعلية للمستخدم
    تُقرأ من دوره (current_user.role.permission_codes)، والذي بدوره يأتي من
    قاعدة البيانات (عبر get_current_user)، وليس من التوكن مباشرة.

    يكفي أن يملك المستخدم واحدة على الأقل من required_codes للسماح بالطلب.
    ملاحظة أمنية (قرار موثّق من صاحبة المشروع 2026-08-27): لا يوجد أي
    تجاوز تلقائي لـsuper_admin هنا — الوصول محكوم فعليًا بقائمة
    permission_codes المحفوظة لدور المستخدم بقاعدة البيانات، حتى لو كان
    الدور هو super_admin. المسار الآمن الوحيد المتبقّي لاستعادة أي صلاحية
    فُقدت بالخطأ هو شاشة "الأدوار والصلاحيات" نفسها، المحمية بـ
    require_super_admin (يفحص is_super_admin مباشرة، بلا علاقة بقائمة
    الصلاحيات) — فلا يوجد خطر قفل كامل من النظام.
    """

    async def _checker(current_user: CurrentUser) -> User:
        user_codes = current_user.role.permission_codes
        if not any(code in user_codes for code in required_codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ليست لديك صلاحية للقيام بهذا الإجراء",
            )
        return current_user

    return _checker


async def require_super_admin(current_user: CurrentUser) -> User:
    """
    يقيّد راوت بـ super_admin حصرًا (وليس أي صلاحية أخرى) — تُستخدم فقط
    لإدارة الأدوار والصلاحيات نفسها (roles.py)، لأن السماح لدور آخر بمنح
    نفسه أو غيره صلاحيات إضافية يفتح ثغرة تصعيد صلاحيات (Privilege
    Escalation). لاحقًا يمكن تحويلها لصلاحية قابلة للتفويض مثل بقية
    الشاشات، لكن حاليًا تبقى محصورة بالدور الجذري فقط.
    """
    if not current_user.role.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ليست لديك صلاحية للقيام بهذا الإجراء",
        )
    return current_user
