# US-PEND-026: Add Redis Cache Layer — KEYS() FIXED

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task (Feature) |
| **Priority** | 🟢 MEDIUM |
| **Batch** | 7 — Long-Term / Deferred |
| **Depends On** | US-PREREQ-002 (Redis Docker verified operational) |
| **Estimated Effort** | 2-3 days |
| **Target Files** | New: `app/services/cache_service.py`. Modify: `app/services/ai/tool_executor.py`, `app/main.py` |

---

## ⚠️ CRITICAL: `keys()` replaced with `scan_iter()`

The original doc used `self._client.keys(pattern)` which is **O(N) blocking over ALL Redis keys** — dangerous in production (Redis is single-threaded; `KEYS` blocks all other operations). The fix uses `scan_iter()` which iterates in small batches without blocking.

---

## User Story

**As a** user in an AI chat session with frequent page list refreshes,
**I want** page data to be cached so repeated reads don't hit the database,
**So that** my AI chat feels responsive and the database load stays manageable.

---

## Current State

- No Redis caching in the AI subsystem
- Page list/fetch hits database on every tool call

---

## Enriched Implementation

### File: `app/services/cache_service.py`

```python
"""Redis cache layer for AI page reads — US-PEND-026."""
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
    and the caller falls through to the database. No crash, no error.

    Usage:
        cache = CacheService()
        await cache.start()
        data = await cache.get("page_list:COURSE-001") or await db_query()
        await cache.set("page_list:COURSE-001", data, ttl=30)
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
            logger.info("CacheService connected to Redis")
        except Exception as exc:
            logger.warning("Redis unavailable (%s) — caching disabled", exc)
            self._enabled = False
            self._client = None

    async def stop(self) -> None:
        if self._client:
            await self._client.close()

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
        """Invalidate keys matching pattern. Uses SCAN, NOT KEYS.

        SCAN iterates in small batches (~10 keys per iteration) so it
        never blocks Redis for other operations.
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
```

### Integration in `tool_executor.py` (exact code):

```python
# In ToolExecutor._execute_list_pages() — BEFORE the DB query:
from app.services.cache_service import CacheService
cache = app.state.cache  # Set during lifespan startup

cache_key = f"page_list:{course_id}"
cached = await cache.get(cache_key)
if cached is not None:
    return cached  # Cache hit

# ... existing DB query ...
pages = await page_repo.list_by_course(course_id)

# Cache the result (fire-and-forget)
await cache.set(cache_key, pages, ttl=TTL_PAGE_LIST)
return pages
```

### Integration in `app/main.py` lifespan:

```python
# Startup:
from app.services.cache_service import CacheService
cache_service = CacheService()
await cache_service.start()
app.state.cache = cache_service

# Shutdown:
if hasattr(app.state, 'cache'):
    await app.state.cache.stop()
```

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | First `list_pages` hits DB, subsequent within 30s hit Redis | `MONITOR` in Redis CLI shows GET/SETEX calls |
| AC-2 | Page update invalidates cache | After proposal apply → `GET elearning:ai:page_list:COURSE-001` returns nil |
| AC-3 | Redis unavailable → DB fallback (no crash) | Stop Redis container → API still returns data |
| AC-4 | `invalidate_pattern` uses SCAN, not KEYS | `grep "scan_iter\|\.keys(" cache_service.py` — scan_iter present, .keys( absent |

---

## Validation

```bash
pip install redis>=5.0.0
docker compose -f docker-compose.yml up -d redis

# Verify SCAN, not KEYS
grep "scan_iter" app/services/cache_service.py  # Must match
grep "\.keys(" app/services/cache_service.py    # Must NOT match (except in comments)

PYTHONPATH=. python -c "
import asyncio
from app.services.cache_service import CacheService
async def test():
    c = CacheService()
    await c.start()
    await c.set('test', {'ok': True}, ttl=60)
    v = await c.get('test')
    print(f'Get/Set: {v}')
    await c.invalidate('test')
    await c.stop()
asyncio.run(test())
"
```
