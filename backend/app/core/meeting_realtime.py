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

from fastapi import WebSocket


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
        لتفادي تكرار العنصر بالواجهة). اتصال مقطوع فعليًا (RuntimeError عند
        الإرسال) يُزال فورًا بدل انتظار استدعاء disconnect لاحقًا."""
        connections = self._connections.get(meeting_id)
        if not connections:
            return
        dead: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(payload)
            except RuntimeError:
                dead.append(connection)
        for connection in dead:
            self.disconnect(meeting_id, connection)


connection_manager = MeetingConnectionManager()
