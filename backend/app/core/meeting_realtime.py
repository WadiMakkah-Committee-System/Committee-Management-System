"""
تحديث 2026-09-10: هذا الملف لم يعد مستخدَمًا — استُبدل بالكامل بـ
app/core/socketio_server.py (Socket.IO بدل WebSocket الخام، قرار لاما
2026-09-10). أُبقي هنا فقط للمرجعية التاريخية بدل حذفه فورًا؛ آمن حذفه
لاحقًا بعد التأكد إن التحويل لـSocket.IO مستقر. لا يستورده أي ملف آخر
بالمشروع الآن (تحقّق عبر grep قبل الحذف النهائي لو حبيتِ).
"""

"""
الهدف:
مدير اتصالات WebSocket للحظات الحية داخل غرفة الاجتماع (محادثة + رفع
اليد + أحداث نشاط فورية مثل بدء مناقشة بند أجندة أو نشر قرار للتصويت) —
راجعي رأس db/migrations/0026_meeting_realtime.sql وapp/api/v1/meetings.py
(meeting_live_socket) للتصميم الكامل.

أول استخدام WebSocket بهذا المشروع — بقية الوحدات REST + React Query
polling عبر invalidateQueries (قرار موثّق مع صاحبة المشروع 2026-09-06:
اجتماع حي يحتاج نقلًا فوريًا حقيقيًا، Polling كل ثوانٍ غير كافٍ لتجربة
اجتماع مباشر). Agora RTC (فيديو/صوت) منفصل تمامًا عن هذه القناة —
هذي فقط لأحداث نصية خفيفة (رسائل/إشارات)، الوسائط الثقيلة تمر عبر Agora
حصرًا.

بسيط عمدًا (In-Memory dict، بلا Redis Pub/Sub) — يكفي لعملية واحدة
(instance) واحدة بحجم هذا المشروع؛ لو صار لاحقًا أكثر من عملية Backend
خلف Load Balancer، يحتاج تحويل لـRedis Pub/Sub بدل هذا الـdict المحلي
(كل عملية تشوف فقط الاتصالات المفتوحة معها هي).
"""

import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


class MeetingConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, set[WebSocket]] = {}

    async def connect(self, meeting_id: uuid.UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(meeting_id, set()).add(websocket)

    def disconnect(self, meeting_id: uuid.UUID, websocket: WebSocket) -> None:
        connections = self._connections.get(meeting_id)
        if not connections:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop(meeting_id, None)

    async def broadcast(self, meeting_id: uuid.UUID, payload: dict[str, Any]) -> None:
        """يبث لكل الاتصالات المفتوحة بنفس الاجتماع (بما فيها المُرسِل نفسه —
        الواجهة تعتمد على البث كمصدر وحيد للحقيقة بدل تحديث محلي متفائل،
        لتفادي تكرار العنصر بالواجهة). اتصال مقطوع فعليًا يُزال فورًا بدل
        انتظار استدعاء disconnect لاحقًا — عبر send_json على اتصال Starlette
        قد يرفع RuntimeError (إرسال بعد إغلاق الـsocket) أو WebSocketDisconnect
        (العميل قطع الاتصال فعليًا لكن حلقة receive_json بجانبه لم "تلحظ"
        ذلك بعد — راجعي starlette/websockets.py::send). إصلاح 2026-09-08
        (بلاغ لاما — Traceback فعلي): كان يُمسَك RuntimeError فقط، فأي اتصال
        قديم متروك بالمجموعة يُسقِط WebSocketDisconnect غير المُمسوك من
        broadcast() نفسها، ويُفشِل معه استدعاء الدالة بالكامل — تحديدًا عند
        بث "presence.joined" فور انضمام عضو جديد (meeting_live_socket)، فيفشل
        الـhandshake بالكامل لهذا العضو الجديد بخطأ 500 غير مفهوم بالواجهة،
        رغم أن المشكلة اتصال قديم ميت لا علاقة له بالعضو الجديد أصلًا."""
        connections = self._connections.get(meeting_id)
        if not connections:
            return
        dead: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(payload)
            except (RuntimeError, WebSocketDisconnect):
                dead.append(connection)
        for connection in dead:
            self.disconnect(meeting_id, connection)


connection_manager = MeetingConnectionManager()
