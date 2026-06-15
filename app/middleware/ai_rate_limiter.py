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
# Rate Limit Middleware
# ---------------------------------------------------------------------------

class AIRateLimitMiddleware(BaseHTTPMiddleware):
    """Enforces AI endpoint rate limits.

    Checks: tenant-level -> user-level -> endpoint burst.
    Each check is sequential; the first violation returns 429.
    """

    def __init__(self, app, store: Optional[InProcessRateLimitStore] = None):
        super().__init__(app)
        self.store = store or InProcessRateLimitStore()
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

        # Tenant-level
        tenant_key = self.store._key("tenant", tenant_id, "req")
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
        user_key = self.store._key("user", user_id, "req")
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
        burst_key = self.store._key("burst", user_id, endpoint)
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
        response.headers["X-RateLimit-Remaining"] = str(
            self.user_req_limit
            - self.store.current_count(user_key, self.user_req_window)
        )

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
