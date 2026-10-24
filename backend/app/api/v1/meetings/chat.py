"""رسائل القناة اللحظية (Socket.IO) المحفوظة."""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.db.session import get_db
from app.schemas.meeting_chat import MeetingChatMessageOut
from app.services import meeting_chat_service
from app.services.meeting_chat_service import MeetingChatForbiddenError, MeetingChatNotFoundError


router = APIRouter(prefix="/meetings", tags=["meetings"])


# ============================== القناة اللحظية (Socket.IO) ==============================
# محادثة الاجتماع + رفع اليد + بث "بند الأجندة قيد المناقشة الآن" —
# تحديث 2026-09-10: انتقلت من WebSocket خام (@router.websocket هنا سابقًا)
# إلى Socket.IO — راجعي app/core/socketio_server.py (معالجات connect/
# chat.send/hand.raise/...) وapp/main.py (تركيب socketio.ASGIApp) للتصميم
# الكامل الجديد، وdb/migrations/0026_meeting_realtime.sql للسياق التاريخي.


@router.get("/{meeting_id}/chat/messages", response_model=list[MeetingChatMessageOut])
async def get_meeting_chat_messages(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[MeetingChatMessageOut]:
    """تحميل تاريخ المحادثة عند فتح لوحة "المحادثة" — الرسائل الجديدة بعدها
    تصل عبر Socket.IO (app/core/socketio_server.py) لا عبر Polling على هذا
    الراوت. يتطلب meetings.join (نفس صلاحية الانضمام للاجتماع)."""
    try:
        messages = await meeting_chat_service.list_messages(
            db, actor=current_user, meeting_id=meeting_id
        )
    except MeetingChatNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MeetingChatForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return [MeetingChatMessageOut.model_validate(m) for m in messages]
