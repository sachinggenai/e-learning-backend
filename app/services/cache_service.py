"""Redis cache layer for AI page reads — US-PEND-026.

Async Redis cache with graceful degradation. If Redis is unavailable,
all operations return None (cache miss) and the caller falls through
to the database. No crash, no error.

Uses SCAN (not KEYS) for pattern invalidation to avoid blocking Redis.

Usage:
    cache = CacheService()
    await cache.start()
    data = await cache.get("page_list:COURSE-001") or await db_query()
    await cache.set("page_list:COURSE-001", data, ttl=30)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)

TTL_PAGE_LIST = 30
TTL_PAGE_FETCH = 60
TTL_COURSE_STRUCTURE = 120
CACHE_PREFIX = "elearning:ai"


class CacheService:
    """Async Redis cache with graceful degradation.

    If Redis is unavailable, all operations return None (cache miss)
    and the caller falls through to the database.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv(
            "REDIS_URL", "redis://localhost:6379/0"
        )
        self._client: Optional[redis.Redis] = None
        self._enabled = True

    async def start(self) -> None:
        try:
            self._client = redis.from_url(
                self.redis_url, encoding="utf-8", decode_responses=True,
                socket_connect_timeout=2, socket_timeout=2,
            )
            await self._client.ping()
            logger.info("CacheService connected to Redis at %s", self.redis_url)
        except Exception as exc:
            logger.warning("Redis unavailable (%s) — caching disabled", exc)
            self._enabled = False
            self._client = None

    async def stop(self) -> None:
        if self._client:
            await self._client.close()
            logger.info("CacheService disconnected")

    async def get(self, key: str) -> Optional[Any]:
        if not self._enabled or not self._client:
            return None
        try:
            value = await self._client.get(f"{CACHE_PREFIX}:{key}")
            return json.loads(value) if value else None
        except Exception:
            return None

    async def set(self, key: str, value: Any, ttl: int = TTL_PAGE_LIST) -> bool:
        if not self._enabled or not self._client:
            return False
        try:
            await self._client.setex(
                f"{CACHE_PREFIX}:{key}", ttl, json.dumps(value, default=str),
            )
            return True
        except Exception:
            return False

    async def invalidate(self, key: str) -> bool:
        if not self._enabled or not self._client:
            return False
        try:
            await self._client.delete(f"{CACHE_PREFIX}:{key}")
            return True
        except Exception:
            return False

    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate keys matching pattern using SCAN (non-blocking).

        Never uses KEYS() which is O(N) and blocks Redis.
        """
        if not self._enabled or not self._client:
            return 0
        count = 0
        try:
            full_pattern = f"{CACHE_PREFIX}:{pattern}"
            async for key in self._client.scan_iter(match=full_pattern, count=10):
                await self._client.delete(key)
                count += 1
        except Exception:
            pass
        return count

    @property
    def is_available(self) -> bool:
        return self._enabled and self._client is not None
