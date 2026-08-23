"""
الهدف:
راوت "سجل النشاط" (Activity Log) — يعرض لمن يدير النظام (شخص غير تقني
غالبًا) من فعل ماذا ومتى، اعتمادًا على audit_logs الموجود أصلًا وكان
يُسجَّل داخليًا فقط بدون أي واجهة لعرضه.

قواعد الوصول:
مقصور على super_admin حصرًا — سجل النشاط يكشف تفاصيل حسّاسة عن كل عملية
تمت في النظام (من غيّر ماذا)، فيبقى محصورًا بالدور الجذري حاليًا.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_super_admin
from app.db.session import get_db
from app.schemas.audit_log import AuditLogOut, AuditLogPageOut
from app.services import audit_service

router = APIRouter(
    prefix="/audit-logs",
    tags=["Activity Log"],
    dependencies=[Depends(require_super_admin)],
)


@router.get("", response_model=AuditLogPageOut)
async def list_audit_logs(
    target_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> AuditLogPageOut:
    entries, total = await audit_service.list_audit_logs(
        db, target_type=target_type, limit=limit, offset=offset
    )
    return AuditLogPageOut(
        items=[AuditLogOut.from_orm_entry(e) for e in entries],
        total=total,
        limit=limit,
        offset=offset,
    )
