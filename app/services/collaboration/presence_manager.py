"""Shared presence tracking via Redis — US-PEND-030 (Phase 2 multi-worker).

Phase 1 (MVP): Single-worker uses ConnectionManager._rooms (in-process).
Phase 2 (Scale): This PresenceManager provides Redis-backed shared presence
for multi-worker deployments. Redis pub/sub handles cross-worker broadcasting.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)
CHANNEL_PREFIX = "elearning:collab"


class PresenceManager:
    """Redis-backed presence for multi-worker deployments (US-PEND-030 Phase 2)."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self._client: Optional[redis.Redis] = None

    async def start(self):
        self._client = redis.from_url(
            self.redis_url, encoding="utf-8", decode_responses=True,
        )
        await self._client.ping()

    async def stop(self):
        if self._client:
            await self._client.close()

    async def user_joined(self, course_id: str, user_id: str, user_name: str):
        await self._client.sadd(f"{CHANNEL_PREFIX}:presence:{course_id}", user_id)
        await self._client.hset(
            f"{CHANNEL_PREFIX}:users:{course_id}", user_id,
            json.dumps({"user_id": user_id, "name": user_name,
                        "joined_at": datetime.utcnow().isoformat()}),
        )
        await self._publish(course_id, "user_joined",
                            {"user_id": user_id, "name": user_name})

    async def user_left(self, course_id: str, user_id: str):
        await self._client.srem(f"{CHANNEL_PREFIX}:presence:{course_id}", user_id)
        await self._client.hdel(f"{CHANNEL_PREFIX}:users:{course_id}", user_id)
        await self._publish(course_id, "user_left", {"user_id": user_id})

    async def get_present_users(self, course_id: str) -> list:
        users = await self._client.hgetall(f"{CHANNEL_PREFIX}:users:{course_id}")
        return [json.loads(v) for v in users.values()]

    async def broadcast_page_locked(self, course_id, page_id, locked_by):
        await self._publish(course_id, "page_locked",
                            {"page_id": page_id, "locked_by": locked_by})

    async def broadcast_page_unlocked(self, course_id, page_id):
        await self._publish(course_id, "page_unlocked", {"page_id": page_id})

    async def broadcast_content_changed(self, course_id, page_id, changed_by, change_type):
        await self._publish(course_id, "content_changed",
                            {"page_id": page_id, "changed_by": changed_by,
                             "change_type": change_type})

    async def _publish(self, course_id, event_type, data):
        msg = json.dumps({"event": event_type, "data": data,
                          "timestamp": datetime.utcnow().isoformat()})
        await self._client.publish(f"{CHANNEL_PREFIX}:room:{course_id}", msg)
