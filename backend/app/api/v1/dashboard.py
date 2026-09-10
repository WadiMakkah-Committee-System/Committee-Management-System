"""
الهدف:
راوت REST لوحدة "لوحة التحكم" — مسار واحد فقط (GET /dashboard/summary).
راجعي رأس app/services/dashboard_service.py للتفصيل الكامل، وخصوصًا
لماذا لا يوجد أي require_permission هنا: كل قسم من الاستجابة محكوم أصلًا
بصلاحيات وحدته الحقيقية (استدعاء list_* الأصلي لكل وحدة)، فأي مستخدم
مسجّل دخول يحصل على نسخته الخاصة والصحيحة من لوحة التحكم دون استثناء —
يطابق حرفيًا SRS: "توجيه المستخدم بعد تسجيل الدخول للوحة التحكم المناسبة
لدوره وصلاحياته"، بلا حاجة لبوابة صلاحية إضافية على المسار نفسه.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.dashboard import DashboardSummary
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> DashboardSummary:
    return await dashboard_service.get_dashboard_summary(db, actor=current_user)
