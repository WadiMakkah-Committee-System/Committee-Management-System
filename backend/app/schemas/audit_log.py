"""
الهدف:
Pydantic Schemas لسجل النشاط (Activity Log) — عرض "من فعل ماذا ومتى" لمن
يدير النظام (غالبًا شخص غير تقني)، بدل الحاجة للوصول لقاعدة البيانات
مباشرة لفهم ما حدث.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    log_id: uuid.UUID
    actor_name: str | None
    action_type: str
    target_type: str
    target_id: uuid.UUID
    metadata: dict[str, Any] | None
    created_at: datetime

    @classmethod
    def from_orm_entry(cls, entry) -> "AuditLogOut":
        return cls(
            log_id=entry.log_id,
            actor_name=entry.actor.full_name if entry.actor else None,
            action_type=entry.action_type,
            target_type=entry.target_type,
            target_id=entry.target_id,
            metadata=entry.metadata_,
            created_at=entry.created_at,
        )


class AuditLogPageOut(BaseModel):
    items: list[AuditLogOut]
    total: int
    limit: int
    offset: int
