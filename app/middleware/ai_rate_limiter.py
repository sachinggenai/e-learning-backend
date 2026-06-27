"""AI Rate Limiter Middleware - US-BKND-AI-021.

Enforces per-user, per-tenant, and per-endpoint rate limits for all
/api/v1/ai/* requests. Uses in-process sliding window counters (MVP).
Returns structured 429 responses with Retry-After headers.

Configuration via env:
    AI_RATE_LIMIT_USER_REQUESTS (default 100/min)
    AI_RATE_LIMIT_TENANT_REQUESTS (default 1000/min)
    AI_RATE_LIMIT_ENDPOINT_BURST (default 20/10s)
"""

from __future__ import annotations

import os
import time
import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("ai_rate_limiter")

AI_PREFIX = "/api/v1/ai/"


# ---------------------------------------------------------------------------
# In-Process Rate Limit Store (MVP; replace with Redis for production)
# ---------------------------------------------------------------------------

class InProcessRateLimitStore:
    """Sliding-window counter using in-memory timestamp lists."""

    def __init__(self):
        self._windows: dict[str, list[float]] = {}

    def _key(self, *parts: str) -> str:
        return ":".join(parts)

    def increment_and_check(
        self, key: str, limit: int, window_seconds: int
    ) -> tuple[bool, int]:
        """Returns (is_allowed, remaining) after incrementing."""
        now = time.time()
        cutoff = now - window_seconds
        timestamps = self._windows.setdefault(key, [])
        self._windows[key] = [t for t in timestamps if t > cutoff]
        if len(self._windows[key]) >= limit:
            return False, max(0, limit - len(self._windows[key]))
        self._windows[key].append(now)
        return True, max(0, limit - len(self._windows[key]))

    def current_count(self, key: str, window_seconds: int) -> int:
        now = time.time()
        cutoff = now - window_seconds
        return len([t for t in self._windows.get(key, []) if t > cutoff])

    def reset(self, key: str = "") -> None:
        """Reset counters. If key is empty, reset all."""
        if key:
            self._windows.pop(key, None)
        else:
            self._windows.clear()


# ---------------------------------------------------------------------------
# Redis-Backed Rate Limit Store (Phase 0.6)
# ---------------------------------------------------------------------------

class RedisRateLimitStore:
    """Sliding-window rate limiter backed by Redis sorted sets.

    Survives process restarts and works across multiple workers.
    Gracefully degrades to InProcessRateLimitStore when Redis is unavailable.

    Uses the sorted-set sliding window algorithm:
        - Each request is added as a member with score = current_time
        - Count members in window [now - window_seconds, now]
        - Expire old members to keep memory bounded
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        fallback_store: Optional[InProcessRateLimitStore] = None,
    ):
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self._redis: Any = None
        self._fallback = fallback_store or InProcessRateLimitStore()
        self._redis_available = False
        self._init_attempted = False

    async def _ensure_redis(self) -> bool:
        """Lazy-init Redis connection. Returns True if Redis is available."""
        if self._init_attempted:
            return self._redis_available

        self._init_attempted = True
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                self._redis_url,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
            await self._redis.ping()
            self._redis_available = True
            logger.info("Redis rate limit store CONNECTED (%s)", self._redis_url)
        except ImportError:
            logger.warning(
                "redis package not installed — using in-process rate limit store"
            )
        except Exception as exc:
            logger.warning(
                "Redis unavailable (%s) — using in-process rate limit store: %s",
                self._redis_url, exc,
            )
        return self._redis_available

    @staticmethod
    def _key(*parts: str) -> str:
        return "ratelimit:" + ":".join(parts)

    async def increment_and_check(
        self, key: str, limit: int, window_seconds: int
    ) -> tuple[bool, int]:
        """Returns (is_allowed, remaining) using Redis sorted-set window."""
        if not await self._ensure_redis():
            return self._fallback.increment_and_check(key, limit, window_seconds)

        redis_key = self._key(key)
        now = time.time()
        cutoff = now - window_seconds

        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                # Remove expired entries
                pipe.zremrangebyscore(redis_key, 0, cutoff)
                # Count current window
                pipe.zcard(redis_key)
                # Add current request
                pipe.zadd(redis_key, {str(now): now})
                # Set TTL on the key to auto-cleanup
                pipe.expire(redis_key, window_seconds * 2)
                _, current, _, _ = await pipe.execute()

            remaining = max(0, limit - current)
            return current < limit, remaining
        except Exception as exc:
            logger.warning("Redis rate limit error (%s) — falling back to in-process", exc)
            self._redis_available = False
            return self._fallback.increment_and_check(key, limit, window_seconds)

    async def current_count(self, key: str, window_seconds: int) -> int:
        """Count requests in the current window."""
        if not self._redis_available:
            return self._fallback.current_count(key, window_seconds)

        redis_key = self._key(key)
        cutoff = time.time() - window_seconds
        try:
            await self._redis.zremrangebyscore(redis_key, 0, cutoff)
            return await self._redis.zcard(redis_key)
        except Exception:
            return self._fallback.current_count(key, window_seconds)

    async def reset(self, key: str = "") -> None:
        """Reset counters. If key is empty, reset all (including in-process)."""
        self._fallback.reset(key)
        if not self._redis_available:
            return
        try:
            if key:
                await self._redis.delete(key)
            else:
                # Scan and delete all ratelimit keys
                cursor = 0
                while True:
                    cursor, keys = await self._redis.scan(
                        cursor, match="ratelimit:*", count=100
                    )
                    if keys:
                        await self._redis.delete(*keys)
                    if cursor == 0:
                        break
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Rate Limit Middleware
# ---------------------------------------------------------------------------

class AIRateLimitMiddleware(BaseHTTPMiddleware):
    """Enforces AI endpoint rate limits.

    Checks: tenant-level -> user-level -> endpoint burst.
    Each check is sequential; the first violation returns 429.

    Store: Auto-detects Redis. Falls back to InProcessRateLimitStore
    when Redis is unavailable (graceful degradation).
    """

    def __init__(
        self,
        app,
        store: Optional[Any] = None,
        use_redis: Optional[bool] = None,
    ):
        super().__init__(app)
        # If store is explicitly provided, use it directly (for testing)
        if store is not None:
            self.store = store
        elif use_redis is None:
            # Auto-detect: prefer Redis if RATE_LIMIT_STORE=redis (default)
            use_redis = os.getenv("RATE_LIMIT_STORE", "redis").lower() == "redis"
            self.store = RedisRateLimitStore() if use_redis else InProcessRateLimitStore()
        elif use_redis:
            self.store = RedisRateLimitStore()
        else:
            self.store = InProcessRateLimitStore()

        self._is_async_store = isinstance(self.store, RedisRateLimitStore)
        self._store_key_fn = self.store._key
        self._load_config()

    def _load_config(self):
        self.user_req_limit = int(os.getenv("AI_RATE_LIMIT_USER_REQUESTS", "100"))
        self.user_req_window = 60
        self.tenant_req_limit = int(os.getenv("AI_RATE_LIMIT_TENANT_REQUESTS", "1000"))
        self.tenant_req_window = 60
        self.endpoint_burst_limit = int(os.getenv("AI_RATE_LIMIT_ENDPOINT_BURST", "20"))
        self.endpoint_burst_window = 10

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(AI_PREFIX):
            return await call_next(request)

        tenant_id = getattr(request.state, "tenant_id", "default")
        user_id = getattr(request.state, "user_id", "anonymous")
        endpoint = request.url.path

        incr = (
            self.store.increment_and_check
            if not self._is_async_store
            else self.store.increment_and_check
        )

        # Tenant-level
        tenant_key = self._store_key_fn("tenant", tenant_id, "req")
        if self._is_async_store:
            allowed, _ = await self.store.increment_and_check(
                tenant_key, self.tenant_req_limit, self.tenant_req_window
            )
        else:
            allowed, _ = self.store.increment_and_check(
                tenant_key, self.tenant_req_limit, self.tenant_req_window
            )
        if not allowed:
            return self._rate_limit_response(
                "TENANT_RATE_LIMIT_EXCEEDED",
                f"Tenant request quota exceeded ({self.tenant_req_limit}/{self.tenant_req_window}s)",
                self.tenant_req_window,
            )

        # User-level
        user_key = self._store_key_fn("user", user_id, "req")
        if self._is_async_store:
            allowed, _ = await self.store.increment_and_check(
                user_key, self.user_req_limit, self.user_req_window
            )
        else:
            allowed, _ = self.store.increment_and_check(
                user_key, self.user_req_limit, self.user_req_window
            )
        if not allowed:
            return self._rate_limit_response(
                "USER_RATE_LIMIT_EXCEEDED",
                f"User request quota exceeded ({self.user_req_limit}/{self.user_req_window}s)",
                self.user_req_window,
            )

        # Endpoint burst
        burst_key = self._store_key_fn("burst", user_id, endpoint)
        if self._is_async_store:
            allowed, _ = await self.store.increment_and_check(
                burst_key, self.endpoint_burst_limit, self.endpoint_burst_window
            )
        else:
            allowed, _ = self.store.increment_and_check(
                burst_key, self.endpoint_burst_limit, self.endpoint_burst_window
            )
        if not allowed:
            return self._rate_limit_response(
                "ENDPOINT_BURST_LIMIT_EXCEEDED",
                f"Endpoint burst quota exceeded ({self.endpoint_burst_limit}/{self.endpoint_burst_window}s)",
                self.endpoint_burst_window,
            )

        response: Response = await call_next(request)

        # Set rate-limit headers
        response.headers["X-RateLimit-Limit"] = str(self.user_req_limit)
        if self._is_async_store:
            remaining = self.user_req_limit - await self.store.current_count(
                user_key, self.user_req_window
            )
        else:
            remaining = self.user_req_limit - self.store.current_count(
                user_key, self.user_req_window
            )
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response

    def _rate_limit_response(
        self, code: str, message: str, retry_after: int
    ) -> JSONResponse:
        logger.warning("Rate limit: code=%s retry_after=%ds", code, retry_after)
        return JSONResponse(
            status_code=429,
            content={
                "status": "error",
                "code": code,
                "message": message,
                "details": {"retry_after_seconds": retry_after},
                "retryable": True,
            },
            headers={"Retry-After": str(retry_after)},
        )
