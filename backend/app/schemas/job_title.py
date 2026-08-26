"""
الهدف:
Pydantic Schemas الخاصة بالمسميات الوظيفية (Job Titles) — تحدّد شكل
بيانات طلبات وردود وحدة "المسميات الوظيفية" المستقلة (تبويب ثالث تحت
"إدارة المستخدمين").

المسؤولية:
التحقق من صحة الاسم عند الإنشاء/التعديل، وتحديد شكل البيانات المرجَعة
للعميل (تُستخدم أيضًا مضمَّنة داخل UserOut.job_title).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JobTitleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)


class JobTitleUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=150)


class JobTitleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_title_id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime
