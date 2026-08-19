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

from sqlalchemy.ext.asyncio import AsyncSession

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
