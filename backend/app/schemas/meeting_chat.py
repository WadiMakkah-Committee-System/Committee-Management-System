"""
الهدف:
Pydantic Schemas لـ"محادثة الاجتماع" — راجعي رأس
db/migrations/0026_meeting_realtime.sql وapp/models/meeting_chat.py
للتصميم الكامل.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.committee import CommitteeMemberUserOut


class MeetingChatMessageCreate(BaseModel):
    """يُستخدَم فقط لتوثيق شكل الحمولة القادمة عبر WebSocket (type=chat.send) —
    راجعي app/api/v1/meetings.py::meeting_live_socket. لا يوجد راوت REST
    لإرسال رسالة، الإرسال عبر WS فقط؛ الاستقبال الأولي (تاريخ المحادثة)
    عبر REST (GET) أدناه."""

    body: str = Field(min_length=1, max_length=2000)


class MeetingChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: uuid.UUID
    meeting_id: uuid.UUID
    body: str
    sender: CommitteeMemberUserOut
    created_at: datetime
