"""WebSocket endpoint for real-time collaboration — US-PEND-030.

Phase 1 (MVP): Single uvicorn worker. ConnectionManager handles presence
in-process. Redis pub/sub broadcasts messages (future-proof for scaling).

Auth: JWT token passed as query parameter ?token=eyJ... because browsers'
WebSocket API does not support custom headers.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

from app.dependencies.auth_dependencies import get_current_user_ws

logger = logging.getLogger(__name__)
router = APIRouter()

REDIS_URL = "redis://localhost:6379/0"
REDIS_POOL: Optional[Redis] = None


async def _get_redis() -> Redis:
    global REDIS_POOL
    if REDIS_POOL is None:
        REDIS_POOL = Redis.from_url(
            REDIS_URL, encoding="utf-8", decode_responses=True,
        )
    return REDIS_POOL


class ConnectionManager:
    def __init__(self):
        self._rooms: dict[str, list[WebSocket]] = {}

    async def connect(self, course_id: str, ws: WebSocket):
        await ws.accept()
        self._rooms.setdefault(course_id, []).append(ws)

    def disconnect(self, course_id: str, ws: WebSocket):
        room = self._rooms.get(course_id, [])
        if ws in room:
            room.remove(ws)

    async def broadcast(self, course_id: str, message: str):
        room = self._rooms.get(course_id, [])
        for ws in list(room):
            try:
                await ws.send_text(message)
            except Exception:
                if ws in room:
                    room.remove(ws)


manager = ConnectionManager()


@router.websocket("/ws/courses/{course_id}/collaborate")
async def collaborate(websocket: WebSocket, course_id: str, token: str = None):
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return
    try:
        user = await get_current_user_ws(token)
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await manager.connect(course_id, websocket)
    logger.info("WS: user=%s joined course=%s", user.user_id, course_id)

    redis_client = await _get_redis()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"elearning:collab:room:{course_id}")

    try:
        await redis_client.publish(
            f"elearning:collab:room:{course_id}",
            json.dumps({"event": "user_joined",
                        "data": {"user_id": user.user_id, "user_name": user.username}}),
        )

        import asyncio

        async def redis_listener():
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    await manager.broadcast(course_id, msg["data"])

        async def client_listener():
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                action = message.get("action", "")
                if action == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))
                elif action in ("page_locked", "page_unlocked", "content_changed"):
                    await redis_client.publish(
                        f"elearning:collab:room:{course_id}",
                        json.dumps({"event": action,
                                    "data": {**message.get("data", {}),
                                             "user_id": user.user_id}}),
                    )

        redis_task = asyncio.create_task(redis_listener())
        client_task = asyncio.create_task(client_listener())
        done, pending = await asyncio.wait(
            [redis_task, client_task], return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

    except WebSocketDisconnect:
        logger.info("WS: user=%s left course=%s", user.user_id, course_id)
    finally:
        manager.disconnect(course_id, websocket)
        await pubsub.unsubscribe(f"elearning:collab:room:{course_id}")
        await redis_client.publish(
            f"elearning:collab:room:{course_id}",
            json.dumps({"event": "user_left",
                        "data": {"user_id": user.user_id, "user_name": user.username}}),
        )
