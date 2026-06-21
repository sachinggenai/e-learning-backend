# US-PEND-030: Multi-User Real-Time Collaboration — ARCHITECTURE-FIXED

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task (Feature) |
| **Priority** | 🟢 MEDIUM |
| **Batch** | 7 — Long-Term / Deferred |
| **Depends On** | US-PREREQ-002 (Redis), US-PREREQ-004 (WebSocket) |
| **Estimated Effort** | 7-10 days (single-worker MVP) + 3-5 days (multi-worker hardening) |
| **Target Files** | New: `app/routers/ws_collaboration.py`, `app/services/collaboration/`. Modify: `app/main.py`, `app/services/ai/lock_manager.py`, `app/dependencies/auth_dependencies.py` |

---

## ⚠️ MVP SCOPE: Single-Worker First, Multi-Worker Later

This story is implemented in **two phases**:

**Phase 1 (MVP, 7-10 days):** Single uvicorn worker with `--reload`. In-process presence + Redis pub/sub for future-proofing. Works for development and low-traffic production.

**Phase 2 (Scale, +3-5 days):** Add `PresenceManager` (Redis-backed shared presence) for multi-worker deployments. All code is designed to support this upgrade with zero API changes.

**Why single-worker first:** The `ConnectionManager._rooms` dict is in-process. Redis pub/sub handles cross-worker message broadcasting from day 1, so when you add workers, messages flow. Only presence queries (`get_present_users`) need the upgrade.

---

## User Story

**As a** co-author working on a course with my teammate,
**I want** to see my teammate's changes in real-time and know which pages they're editing,
**So that** we don't accidentally overwrite each other's work.

---

## Current State (Code Verified 2026-06-21)

- ✅ `lock_manager.py` provides READ/WRITE/SESSION locks (pessimistic locking)
- ✅ `stale_detector.py` provides 3-way merge for conflict resolution
- ❌ No real-time presence, no cursor tracking, no live updates
- ❌ No WebSocket endpoint registered in FastAPI
- ❌ `app/dependencies/auth_dependencies.py` has no `get_current_user_ws` function
- ✅ Redis verified operational (US-PREREQ-002) at `localhost:6379`
- ✅ FastAPI WebSocket verified working (US-PREREQ-004)

---

## 🔧 Open-Source Tooling

| Tool | Version | Purpose |
|------|---------|---------|
| **FastAPI WebSocket** | Built-in (Starlette) | WebSocket endpoint — same uvicorn process, same JWT auth |
| **redis-py** | 5.x | Pub/sub for cross-worker broadcast + Redis sets for Phase 2 shared presence |
| **websockets** | 16.x | Already installed (uvicorn dependency) |

**No `broadcaster` package needed.** Using raw `redis-py` pub/sub is simpler and avoids an unnecessary dependency.

---

## Architecture

```
Browser/Client
    │  ws://localhost:8000/ws/courses/{id}/collaborate?token=JWT
    ▼
┌──────────────────────────────────────────────────────┐
│  Uvicorn (single worker, --reload for dev)           │
│                                                      │
│  ConnectionManager (in-process dict)                 │
│    _rooms: { course_id: [ws1, ws2, ...] }            │
│                                                      │
│  Redis pub/sub                                        │
│    Channel: elearning:collab:room:{course_id}        │
│    Broadcasts: user_joined, page_locked,             │
│               content_changed, user_left             │
│                                                      │
│  Phase 2 upgrade: PresenceManager (Redis-backed)     │
│    Key: elearning:collab:presence:{course_id} (Set)  │
│    Key: elearning:collab:users:{course_id} (Hash)    │
└──────────────────────────────────────────────────────┘
```

---

## Enriched Implementation

### File: `app/services/collaboration/__init__.py`

```python
"""Real-time collaboration services — US-PEND-030."""
```

### File: `app/services/collaboration/presence_manager.py`

```python
"""Shared presence tracking via Redis — used in Phase 2 for multi-worker."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)
CHANNEL_PREFIX = "elearning:collab"


class PresenceManager:
    """Redis-backed presence for multi-worker deployments (Phase 2).

    In Phase 1 (single-worker), presence is handled by ConnectionManager._rooms.
    This class is fully implemented but only activated when REDIS_URL is configured
    and the app runs with >1 worker.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self._client: Optional[redis.Redis] = None

    async def start(self):
        self._client = redis.from_url(
            self.redis_url, encoding="utf-8", decode_responses=True
        )
        await self._client.ping()
        logger.info("PresenceManager started (Redis-backed, multi-worker ready)")

    async def stop(self):
        if self._client:
            await self._client.close()

    async def user_joined(self, course_id: str, user_id: str, user_name: str):
        key = f"{CHANNEL_PREFIX}:presence:{course_id}"
        await self._client.sadd(key, user_id)
        await self._client.hset(
            f"{CHANNEL_PREFIX}:users:{course_id}", user_id,
            json.dumps({
                "user_id": user_id, "name": user_name,
                "joined_at": datetime.utcnow().isoformat(),
            }),
        )
        await self._publish(course_id, "user_joined", {
            "user_id": user_id, "name": user_name,
        })

    async def user_left(self, course_id: str, user_id: str):
        await self._client.srem(f"{CHANNEL_PREFIX}:presence:{course_id}", user_id)
        await self._client.hdel(f"{CHANNEL_PREFIX}:users:{course_id}", user_id)
        await self._publish(course_id, "user_left", {"user_id": user_id})

    async def get_present_users(self, course_id: str) -> list:
        users = await self._client.hgetall(
            f"{CHANNEL_PREFIX}:users:{course_id}"
        )
        return [json.loads(v) for v in users.values()]

    async def broadcast_page_locked(
        self, course_id: str, page_id: str, locked_by: str
    ):
        await self._publish(course_id, "page_locked", {
            "page_id": page_id, "locked_by": locked_by,
        })

    async def broadcast_page_unlocked(self, course_id: str, page_id: str):
        await self._publish(course_id, "page_unlocked", {"page_id": page_id})

    async def broadcast_content_changed(
        self, course_id: str, page_id: str, changed_by: str, change_type: str
    ):
        await self._publish(course_id, "content_changed", {
            "page_id": page_id, "changed_by": changed_by,
            "change_type": change_type,
        })

    async def _publish(self, course_id: str, event_type: str, data: dict):
        channel = f"{CHANNEL_PREFIX}:room:{course_id}"
        message = json.dumps({
            "event": event_type, "data": data,
            "timestamp": datetime.utcnow().isoformat(),
        })
        await self._client.publish(channel, message)


# Singleton (Phase 2 — unused in Phase 1 single-worker MVP)
presence = PresenceManager()
```

### File: `app/routers/ws_collaboration.py`

```python
"""WebSocket endpoint for real-time collaboration — US-PEND-030.

Phase 1 (MVP): Single-worker. ConnectionManager handles presence in-process.
Redis pub/sub handles cross-worker message broadcasting (future-proof).
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
REDIS_POOL: Optional[Redis] = None  # Shared connection pool (lazy init)


async def _get_redis() -> Redis:
    """Lazy-init shared Redis connection pool. ONE pool for ALL clients."""
    global REDIS_POOL
    if REDIS_POOL is None:
        REDIS_POOL = Redis.from_url(
            REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return REDIS_POOL


class ConnectionManager:
    """Manages active WebSocket connections per course room (in-process).

    Phase 1: Single-worker — presence lives here.
    Phase 2: Multi-worker — presence moves to PresenceManager (Redis-backed).
    """

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
        """Send message to all clients in a course room."""
        room = self._rooms.get(course_id, [])
        disconnected = []
        for ws in room:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            room.remove(ws)

    def get_present_users(self, course_id: str) -> list[str]:
        """In-process presence query (Phase 1)."""
        return [
            str(id(ws)) for ws in self._rooms.get(course_id, [])
        ]


manager = ConnectionManager()


@router.websocket("/ws/courses/{course_id}/collaborate")
async def collaborate(
    websocket: WebSocket,
    course_id: str,
    token: str = None,
):
    """WebSocket for real-time collaboration. Auth via JWT query param.

    Client → Server: {"action": "ping"|"page_locked"|"page_unlocked"}
    Server → Client: {"event": "user_joined"|"user_left"|"page_locked"|"content_changed"}
    """
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

    # Shared Redis connection (ONE pool, not per-client)
    redis_client = await _get_redis()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"elearning:collab:room:{course_id}")

    try:
        # Broadcast join event via Redis pub/sub
        await redis_client.publish(
            f"elearning:collab:room:{course_id}",
            json.dumps({
                "event": "user_joined",
                "data": {"user_id": user.user_id, "user_name": user.username},
            }),
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
                        json.dumps({
                            "event": action,
                            "data": {**message.get("data", {}), "user_id": user.user_id},
                        }),
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
            json.dumps({
                "event": "user_left",
                "data": {"user_id": user.user_id, "user_name": user.username},
            }),
        )
        # NOTE: DO NOT close redis_client — it's the shared pool
```

### File: `app/dependencies/auth_dependencies.py` — ADD this function

```python
async def get_current_user_ws(token: str) -> UserContext:
    """Verify JWT token for WebSocket connections.

    WebSocket connections send the token as a query parameter:
        ws://host/ws/courses/ID/collaborate?token=eyJ...

    This reuses the existing JWT verification from get_current_user().
    """
    from jose import jwt, JWTError
    from app.services.ai.config import get_ai_config

    cfg = get_ai_config()
    try:
        payload = jwt.decode(
            token,
            cfg.jwt_secret_key,
            algorithms=[cfg.jwt_algorithm],
        )
        user_id = payload.get("sub")
        if not user_id:
            raise JWTError("Missing subject claim")
        return UserContext(
            user_id=user_id,
            username=payload.get("username", user_id),
            tenant_id=payload.get("tenant_id", ""),
            roles=payload.get("roles", []),
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
```

### Integration in `app/main.py`

```python
from app.routers.ws_collaboration import router as ws_router
app.include_router(ws_router)
```

### Integration in `lock_manager.py` — Emit events on lock/unlock

```python
# In LockManager.acquire_lock() after successful lock:
try:
    from app.services.collaboration.presence_manager import presence
    await presence.broadcast_page_locked(
        course_id=course_id, page_id=resource_id, locked_by=user_id,
    )
except Exception:
    pass  # Best-effort — lock still acquired even if broadcast fails

# In LockManager.release_lock() after successful release:
try:
    from app.services.collaboration.presence_manager import presence
    await presence.broadcast_page_unlocked(
        course_id=course_id, page_id=resource_id,
    )
except Exception:
    pass
```

---

## Multi-Worker Upgrade Path (Phase 2)

When scaling beyond 1 worker, two changes are needed:

1. **Replace `manager.get_present_users()`** with `presence.get_present_users()` (Redis-backed)
2. **Add heartbeat** — client sends `{"action": "ping"}` every 30s; server tracks `last_heartbeat` in Redis Hash; a background task cleans up stale entries after 60s

These changes require zero WebSocket API changes. Clients use the same events.

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | 2+ users can connect to same course collaboration room | Two `wscat` instances connect to same URL → both accepted |
| AC-2 | User sees who else is viewing the course (Phase 1: in-process, Phase 2: Redis-backed) | Client receives `user_joined` event with `user_id` and `user_name` |
| AC-3 | When user A locks a page, user B sees the lock event | Lock → Redis pub/sub → all clients receive `page_locked` |
| AC-4 | Disconnected users trigger `user_left` event | Close client → other clients receive `user_left` |

---

## Validation

```bash
pip install redis>=5.0.0
docker compose -f docker-compose.yml up -d redis

# Start app (single worker for MVP)
PYTHONPATH=. uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Test with two terminals (requires wscat: npm install -g wscat)
# Terminal 1:
wscat -c "ws://localhost:8000/ws/courses/COURSE-001/collaborate?token=VALID_JWT"

# Terminal 2:
wscat -c "ws://localhost:8000/ws/courses/COURSE-001/collaborate?token=ANOTHER_JWT"

# Both should receive: {"event":"user_joined","data":{"user_id":"...","user_name":"..."}}
```
