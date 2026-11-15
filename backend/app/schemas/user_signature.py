"""
الهدف:
Pydantic Schemas لـ"توقيعي" — التوقيع المحفوظ للمستخدم الحالي (migration 0049).
"""

from datetime import datetime

from pydantic import BaseModel, Field


class SavedSignatureIn(BaseModel):
    """حفظ/استبدال التوقيع: صورة PNG بصيغة data URL (يتحقق منها الخادم بالتفصيل)."""

    signature_image: str = Field(min_length=30, max_length=300_000)


class SavedSignatureOut(BaseModel):
    """التوقيع المحفوظ للمستخدم الحالي فقط."""

    signature_image: str
    updated_at: datetime
