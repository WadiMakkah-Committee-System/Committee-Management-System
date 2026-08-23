"""
الهدف:
مركزية تسجيل كل عمليات إنشاء/تعديل/حذف/إيقاف/تفعيل الحسابات والإدارات في
جدول audit_logs (FR-UM-029)، بدل تكرار منطق التسجيل داخل كل خدمة.

المسؤولية:
دالة واحدة log_action تُستدعى من داخل الخدمات الأخرى (user_service,
department_service) بعد نجاح أي عملية تغيير، وتُدرج سجلًا في audit_logs
ضمن نفس الـ DB session (نفس الـ transaction) — بحيث لو فشلت العملية
الأساسية، لا يُسجَّل تدقيق لعملية لم تحدث فعليًا.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit_log import AuditLog


async def log_action(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None,
    action_type: str,
    target_type: str,
    target_id: uuid.UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    """
    تسجيل عملية تدقيق واحدة. لا يُنفَّذ commit هنا عمدًا — يُترك لطبقة
    الخدمة المستدعية لتضمين هذا السجل ضمن نفس المعاملة (transaction) مع
    العملية الأساسية (مثال: إنشاء مستخدم + تسجيل التدقيق يُحفظان معًا أو
    لا يُحفظ أي منهما).
    """
    entry = AuditLog(
        actor_user_id=actor_user_id,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        metadata_=metadata,
    )
    db.add(entry)


async def list_audit_logs(
    db: AsyncSession,
    *,
    target_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AuditLog], int]:
    """
    سجل النشاط (Activity Log) — لعرض "من فعل ماذا ومتى" لمستخدم غير تقني
    بدون الحاجة للوصول لقاعدة البيانات مباشرة. يرجع (السجلات، العدد الكلي)
    لدعم Pagination في الواجهة.
    """
    base_stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)
    if target_type is not None:
        base_stmt = base_stmt.where(AuditLog.target_type == target_type)
        count_stmt = count_stmt.where(AuditLog.target_type == target_type)

    total = (await db.execute(count_stmt)).scalar_one()

    result = await db.execute(
        base_stmt.options(selectinload(AuditLog.actor))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total
