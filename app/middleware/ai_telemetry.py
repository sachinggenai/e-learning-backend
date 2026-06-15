"""AI Telemetry Middleware - US-BKND-AI-021.

Trace ID propagation, request timing, and structured logging for all
/api/v1/ai/* requests. Every AI operation gets a trace_id that
correlates across chat turns, tool calls, and audit records.
"""

from __future__ import annotations

import time
import uuid
import logging
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("ai_telemetry")

# Context variable for downstream services to access trace_id
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def get_current_trace_id() -> str:
    """Retrieve the current trace ID from request context."""
    return trace_id_var.get()


class AITelemetryMiddleware(BaseHTTPMiddleware):
    """Injects trace ID, times requests, and enriches logging.

    1. Extract or generate trace_id from X-Trace-ID header
    2. Set trace_id_var for downstream service access
    3. Time the request
    4. Set response X-Trace-ID header
    5. Log structured request summary
    """

    AI_PREFIX = "/api/v1/ai/"

    def __init__(self, app, metrics_registry=None):
        super().__init__(app)
        self.metrics = metrics_registry
        self._request_counter = 0
        self._error_counter = 0

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(self.AI_PREFIX):
            return await call_next(request)

        # Extract or generate trace ID
        trace_id = request.headers.get("X-Trace-ID", "")
        if not trace_id or not self._is_valid_uuid(trace_id):
            trace_id = str(uuid.uuid4())

        token = trace_id_var.set(trace_id)
        start_time = time.monotonic()

        try:
            response: Response = await call_next(request)
        except Exception:
            self._error_counter += 1
            raise
        finally:
            duration_ms = (time.monotonic() - start_time) * 1000
            trace_id_var.reset(token)

        response.headers["X-Trace-ID"] = trace_id
        self._request_counter += 1

        logger.info(
            "ai_request method=%s path=%s status=%d duration_ms=%.1f trace_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            trace_id,
        )

        return response

    @staticmethod
    def _is_valid_uuid(val: str) -> bool:
        try:
            uuid.UUID(val)
            return True
        except (ValueError, AttributeError):
            return False

    def get_stats(self) -> dict:
        """Return current telemetry stats for health checks."""
        return {
            "requests_total": self._request_counter,
            "errors_total": self._error_counter,
        }
