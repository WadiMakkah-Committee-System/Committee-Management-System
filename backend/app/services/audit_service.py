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
from sqlalchemy.orm import joinedload, raiseload

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
    target_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    with_total: bool = True,
) -> tuple[list[AuditLog], int | None]:
    """
    سجل النشاط (Activity Log) — لعرض "من فعل ماذا ومتى" لمستخدم غير تقني
    بدون الحاجة للوصول لقاعدة البيانات مباشرة. يرجع (السجلات، العدد الكلي)
    لدعم Pagination في الواجهة. target_id (اختياري، يُستخدم مع target_type)
    يقيّد السجلات لكيان واحد بذاته — راجعي task_service.get_task_activity
    لمثال استخدام (مسار المهمة الموحَّد).
    """
    base_stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)
    if target_type is not None:
        base_stmt = base_stmt.where(AuditLog.target_type == target_type)
        count_stmt = count_stmt.where(AuditLog.target_type == target_type)
    if target_id is not None:
        base_stmt = base_stmt.where(AuditLog.target_id == target_id)
        count_stmt = count_stmt.where(AuditLog.target_id == target_id)

    # with_total=False لمن لا يحتاج العدد الكلي (مسار المهمة يعرض كل السجلات
    # بلا Pagination) — يوفّر استعلام COUNT كامل (تحسين أداء 2026-10-25).
    total = (await db.execute(count_stmt)).scalar_one() if with_total else None

    result = await db.execute(
        # الفاعل بأعمدته فقط (actor_name) — بدون دوره/مسماه/صلاحياته التي
        # كانت تُجرّ تلقائيًا (lazy="selectin" على User.role/job_title →
        # روابط الصلاحيات → الصلاحيات): 5 استعلامات بدل 1+1 (إعادة هيكلة
        # 2026-10-24). JOIN آمن مع LIMIT هنا لأنها علاقة many-to-one.
        base_stmt.options(
            joinedload(AuditLog.actor).raiseload("*", sql_only=True),
            raiseload("*", sql_only=True),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total
