"""
WebSocket Real-Time Attendance Monitoring Channel.
Protected by JWT verification on connection handshake.
"""
import json
import logging
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from backend.app.core.security import decode_token

logger = logging.getLogger("smartpresence.ws")
router = APIRouter(tags=["WebSockets"])


class SessionConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.setdefault(session_id, set()).add(websocket)
        logger.info("WebSocket client joined session monitor %s", session_id)

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        conns = self.active_connections.get(session_id)
        if conns and websocket in conns:
            conns.remove(websocket)
            if not conns:
                del self.active_connections[session_id]

    async def broadcast_session_event(self, session_id: str, event: dict) -> None:
        conns = list(self.active_connections.get(session_id, set()))
        if not conns:
            return
        message = json.dumps(event)
        stale: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(session_id, ws)


ws_manager = SessionConnectionManager()


@router.websocket("/ws/attendance/{session_id}")
async def attendance_session_ws(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(...),
):
    payload = decode_token(token)
    if not payload or payload.get("role") not in ("teacher", "admin"):
        await websocket.close(code=1008, reason="Unauthorized WebSocket access")
        return

    await ws_manager.connect(session_id, websocket)
    try:
        await websocket.send_text(json.dumps({"type": "connected", "session_id": session_id}))
        while True:
            # Keep connection alive and handle client pings
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        ws_manager.disconnect(session_id, websocket)
