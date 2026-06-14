# US-AI-021: Add Production Observability, Rate Limits, and Rollout Gates

**Status:** Draft  
**Priority:** MUST (Production)  
**Depends on:** US-AI-002 (Feature Flags and Model Config), US-AI-010 (Apply Safety, Audit, and Outbox)  
**Source flows:** All flows, cross-cutting (Platform Runtime and Operations Flow)  
**Epic Owner:** Technical Product Owner  

---

## 1. Functional Specification

### 1.1 User Story

As an Operator, I want operational controls and telemetry around AI usage, so that cost, latency, and failure modes are visible and bounded.

### 1.2 Overview

The AI authoring subsystem must expose production-grade observability, rate limiting, and rollout gating before it can be enabled in production environments. Three concerns are addressed together because they share infrastructure (middleware, telemetry pipeline, configuration sources):

1. **Observability** — Every AI operation emits a trace ID that correlates requests across chat turns, tool calls, proposal lifecycles, validation, and outbox events. Metrics are emitted for volume, latency, error rates, token consumption, and cost. Structured logs carry trace context for queryability.

2. **Rate Limits** — Per-user, per-tenant, and per-endpoint rate limits protect downstream AI providers from abuse and contain blast radius of misbehaving clients. Exceeded quotas return structured 429 responses with retry-after headers and clear error codes.

3. **Rollout Gates** — AI functionality can be gradually enabled per environment, tenant, organization, user role, and route. Percentage-based rollouts allow canarying. Feature flags are hot-reloadable without server restart.

### 1.3 Actors

| Actor | Role |
|---|---|
| Operator (Admin) | Configures rate limits, rollout percentages, feature flags; monitors dashboards and alerts |
| Author (User) | Receives rate-limit errors with retry guidance; subject to rollout gates |
| AI Orchestrator | Emits trace IDs, metrics, and structured logs for each operation |
| Rate Limiter Middleware | Enforces per-user, per-tenant, per-endpoint limits; returns 429 responses |
| Rollout Gate Middleware | Checks feature flags, tenant allowlist, user role, rollout percentage |
| Monitoring System (Prometheus/Grafana/Sentry) | Scrapes metrics, visualizes dashboards, fires alerts |
| Backend System | Writes telemetry events to `ai_telemetry_events` table for offline analysis |

### 1.4 Flows

#### Flow 1: Trace ID Propagation Across AI Operations

1. Frontend initiates an AI operation (chat turn, propose, confirm-apply) including an optional client-generated `X-Trace-ID` header (UUID v4).
2. If no `X-Trace-ID` is provided, the backend generates one at the first middleware layer.
3. The trace ID is injected into the request-scoped logging context (`logging.MDC` or `contextvars`) and the response header `X-Trace-ID`.
4. Every downstream call (DB queries, LLM provider calls, outbox writes) logs the trace ID.
5. The trace ID is persisted in all relevant database records:
   - `ai_sessions.trace_id` (first trace of the session)
   - `ai_telemetry_events.trace_id`
   - `ai_audit_logs.trace_id`
   - `outbox_events.trace_id`
6. The frontend stores the trace ID from the first response and re-sends it for subsequent operations in the same session, enabling end-to-end correlation.

#### Flow 2: Rate Limit Enforcement

1. Every request to `/api/v1/ai/*` passes through the `RateLimitMiddleware`.
2. The middleware extracts the tenant ID (from JWT or header), user ID (from auth), and endpoint path.
3. A counter is incremented in the rate-limit store (Redis or in-process dict for MVP).
4. If the counter exceeds the configured limit for the window, the middleware:
   a. Returns HTTP 429 Too Many Requests.
   b. Sets `Retry-After` header (seconds until reset).
   c. Returns a structured error body matching the `error_envelope.py` pattern.
   d. Logs a rate-limit telemetry event.
5. If the counter is within limits, the request proceeds and the middleware decrements the counter if the request fails with 5xx (to avoid penalizing the caller for server errors).

#### Flow 3: Rollout Gate Evaluation

1. Every request to `/api/v1/ai/*` passes through the `RolloutGateMiddleware`.
2. The middleware evaluates:
   a. **Global kill switch**: `AI_AUTHORING_ENABLED` env var — if `false`, all AI routes return `404 FEATURE_NOT_AVAILABLE`.
   b. **Environment gate**: If `AI_AUTHORING_ENABLED_ENVS` is set, only matching environments pass.
   c. **Tenant allowlist**: If `AI_TENANT_ALLOWLIST` is set, only listed tenant IDs pass.
   d. **Role allowlist**: If `AI_ROLE_ALLOWLIST` is set, only users with matching roles pass.
   e. **Percentage rollout**: If `AI_ROLLOUT_PERCENTAGE` is set (0-100), a deterministic hash of `tenant_id + user_id` modulo 100 is compared to the percentage. Users above the threshold are blocked.
3. Blocked requests return `404 FEATURE_NOT_AVAILABLE` without revealing whether the feature exists.
4. Every gate evaluation is logged as a telemetry event with the gate name, decision, and input parameters.

#### Flow 4: Metrics Emission

1. A Prometheus metrics endpoint (`/api/v1/metrics`) is exposed, gated by admin authentication.
2. The following metric categories are emitted:

   **Counters:**
   - `ai_requests_total{tenant, endpoint, status}` — Request volume
   - `ai_tool_calls_total{tool_name, status}` — Tool call volume
   - `ai_llm_calls_total{provider, model, status}` — LLM provider call volume
   - `ai_proposals_created{operation}` — Proposal creation volume
   - `ai_proposals_applied{operation, status}` — Proposal apply outcomes
   - `ai_rate_limits_exceeded{tenant, endpoint}` — Rate limit hits
   - `ai_rollout_gate_blocked{gate_name}` — Rollout gate blocks
   - `ai_token_usage_total{model, type}` — Token consumption (input/output)

   **Histograms:**
   - `ai_llm_latency_seconds{provider, model}` — LLM response latency
   - `ai_request_latency_seconds{endpoint}` — API request latency
   - `ai_tool_call_duration_seconds{tool_name}` — Tool call duration
   - `ai_tool_call_rounds_per_turn` — Number of tool-call rounds per chat turn

   **Gauges:**
   - `ai_active_sessions{tenant}` — Currently active sessions
   - `ai_rate_limit_remaining{tenant, user, endpoint}` — Remaining quota

3. Metrics are exposed at `/api/v1/metrics` for Prometheus scraping.
4. A dashboard specification (JSON for Grafana) is provided in the documentation.

### 1.5 Error Conditions

| Condition | HTTP Status | Error Code | Behavior |
|---|---|---|---|
| Rate limit exceeded | 429 | `RATE_LIMIT_EXCEEDED` | Structured error with Retry-After, limits reset time, and quota details |
| Daily user quota exceeded | 429 | `USER_DAILY_QUOTA_EXCEEDED` | Shows reset time (midnight UTC) and current usage vs limit |
| Monthly tenant budget exceeded | 429 | `TENANT_MONTHLY_BUDGET_EXCEEDED` | Shows current billing period usage and admin contact |
| Feature not available (gate) | 404 | `FEATURE_NOT_AVAILABLE` | Generic "resource not found" to avoid information leak |
| AI authoring disabled globally | 404 | `FEATURE_NOT_AVAILABLE` | Same generic response |
| Invalid trace ID format | 400 | `INVALID_TRACE_ID` | Accepts UUID v4 only |
| Rate limit store unavailable | 200 (pass) | N/A | Fail-open: allow request, log warning, emit metric |
| Tenant not in allowlist | 404 | `FEATURE_NOT_AVAILABLE` | Generic response, log gate event with `tenant_not_in_allowlist` |

---

## 2. Technical Specification

### 2.1 Trace ID Format and Propagation

**Trace ID Format:**
- UUID v4 string (36 characters, e.g., `a1b2c3d4-e5f6-7890-abcd-ef1234567890`)
- Generated via `uuid.uuid4()` at the middleware layer
- Accepted in `X-Trace-ID` request header from clients

**Middleware implementation in `app/middleware/ai_telemetry.py`:**

```python
"""Middleware for trace ID propagation, request logging, timing, and metrics."""
from __future__ import annotations
import time
import uuid
import logging
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# Context variable so services can access the current trace ID without
# passing it explicitly through every function signature.
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


class AITelemetryMiddleware(BaseHTTPMiddleware):
    """Injects trace ID, records request metrics, and enriches logging context.

    Operations:
      1. Extract or generate trace_id from X-Trace-ID header.
      2. Set trace_id_var for downstream service access.
      3. Time the request and emit latency histogram.
      4. Increment request counter (tagged by endpoint and status).
      5. Set response X-Trace-ID header.
      6. Log structured request summary (method, path, status, duration, trace_id).
    """

    AI_PREFIX = "/api/v1/ai/"

    def __init__(self, app: ASGIApp, metrics_registry=None):
        super().__init__(app)
        self.metrics = metrics_registry  # Prometheus Counter/Histogram references

    async def dispatch(self, request: Request, call_next):
        # Only instrument /api/v1/ai/* paths
        if not request.url.path.startswith(self.AI_PREFIX):
            return await call_next(request)

        trace_id = request.headers.get("X-Trace-ID", "")
        if not trace_id or not self._is_valid_uuid(trace_id):
            trace_id = str(uuid.uuid4())

        token = trace_id_var.set(trace_id)
        start_time = time.monotonic()

        response: Response = await call_next(request)
        duration = time.monotonic() - start_time

        response.headers["X-Trace-ID"] = trace_id

        # Emit metrics (Prometheus counters/histograms)
        if self.metrics:
            self.metrics["requests_total"].labels(
                endpoint=request.url.path,
                method=request.method,
                status=response.status_code,
            ).inc()
            self.metrics["request_latency_seconds"].labels(
                endpoint=request.url.path,
            ).observe(duration)

        logger.info(
            "AI request: method=%s path=%s status=%d duration=%.3f trace_id=%s",
            request.method, request.url.path, response.status_code,
            duration, trace_id,
        )

        trace_id_var.reset(token)
        return response

    @staticmethod
    def _is_valid_uuid(val: str) -> bool:
        try:
            uuid.UUID(val)
            return True
        except (ValueError, AttributeError):
            return False


def get_current_trace_id() -> str:
    """Retrieve the current trace ID from context."""
    return trace_id_var.get()
```

### 2.2 Rate Limit Middleware

**Rate Limit Categories:**

| Category | Scope | Default Limit | Window | Storage |
|---|---|---|---|---|
| User AI requests | Per user | 100 | 1 minute | Redis/In-process |
| Tenant AI requests | Per tenant | 1000 | 1 minute | Redis/In-process |
| User daily tokens | Per user | 100000 | 24 hours (UTC midnight) | Redis/In-process |
| Tenant daily tokens | Per tenant | 1000000 | 24 hours (UTC midnight) | Redis/In-process |
| Session active proposals | Per session | 10 | Session lifetime | In-process/cache |
| Per-endpoint burst | Per user per endpoint | 20 | 10 seconds | Redis/In-process |

**Implementation in `app/middleware/ai_rate_limiter.py`:**

```python
"""Rate limit middleware for AI endpoints — per-user, per-tenant, per-endpoint."""
from __future__ import annotations
import os
import time
import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.utils.error_envelope import build_error

logger = logging.getLogger(__name__)


class InProcessRateLimitStore:
    """Simple in-memory sliding-window counter (MVP; replace with Redis later)."""

    def __init__(self):
        self._windows: dict[str, list[float]] = {}

    def _key(self, *parts: str) -> str:
        return ":".join(parts)

    def increment_and_check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Returns (is_allowed, remaining) after incrementing the counter."""
        now = time.time()
        timestamps = self._windows.setdefault(key, [])
        # Prune expired entries
        cutoff = now - window_seconds
        self._windows[key] = [t for t in timestamps if t > cutoff]
        if len(self._windows[key]) >= limit:
            return False, max(0, limit - len(self._windows[key]))
        self._windows[key].append(now)
        return True, limit - len(self._windows[key])

    def current_count(self, key: str, window_seconds: int) -> int:
        now = time.time()
        cutoff = now - window_seconds
        timestamps = [t for t in self._windows.get(key, []) if t > cutoff]
        return len(timestamps)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforces rate limits per user, per tenant, and per endpoint.

    Configuration via environment variables:
      AI_RATE_LIMIT_USER_REQUESTS        default 100 per minute
      AI_RATE_LIMIT_TENANT_REQUESTS      default 1000 per minute
      AI_RATE_LIMIT_USER_DAILY_TOKENS    default 100000 per day
      AI_RATE_LIMIT_ENDPOINT_BURST       default 20 per 10 seconds
    """

    AI_PREFIX = "/api/v1/ai/"

    def __init__(self, app: ASGIApp, store: Optional[InProcessRateLimitStore] = None):
        super().__init__(app)
        self.store = store or InProcessRateLimitStore()
        self._load_config()

    def _load_config(self):
        self.user_req_limit = int(os.getenv("AI_RATE_LIMIT_USER_REQUESTS", "100"))
        self.user_req_window = 60  # seconds
        self.tenant_req_limit = int(os.getenv("AI_RATE_LIMIT_TENANT_REQUESTS", "1000"))
        self.tenant_req_window = 60
        self.endpoint_burst_limit = int(os.getenv("AI_RATE_LIMIT_ENDPOINT_BURST", "20"))
        self.endpoint_burst_window = 10
        self.user_daily_tokens_limit = int(os.getenv("AI_RATE_LIMIT_USER_DAILY_TOKENS", "100000"))
        self.tenant_daily_tokens_limit = int(os.getenv("AI_RATE_LIMIT_TENANT_DAILY_TOKENS", "1000000"))

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(self.AI_PREFIX):
            return await call_next(request)

        # Resolve identity from request state (set by auth middleware)
        tenant_id = getattr(request.state, "tenant_id", "default")
        user_id = getattr(request.state, "user_id", "anonymous")
        endpoint = request.url.path

        # Check tenant-level rate limit
        tenant_key = self.store._key("tenant", tenant_id, "req")
        allowed, remaining = self.store.increment_and_check(
            tenant_key, self.tenant_req_limit, self.tenant_req_window
        )
        if not allowed:
            return self._rate_limit_response(
                "TENANT_RATE_LIMIT_EXCEEDED",
                f"Tenant request quota exceeded ({self.tenant_req_limit} per {self.tenant_req_window}s)",
                self.tenant_req_window,
                {"limit": self.tenant_req_limit, "window_seconds": self.tenant_req_window},
            )

        # Check user-level rate limit
        user_key = self.store._key("user", user_id, "req")
        allowed, remaining = self.store.increment_and_check(
            user_key, self.user_req_limit, self.user_req_window
        )
        if not allowed:
            return self._rate_limit_response(
                "USER_RATE_LIMIT_EXCEEDED",
                f"User request quota exceeded ({self.user_req_limit} per {self.user_req_window}s)",
                self.user_req_window,
                {"limit": self.user_req_limit, "window_seconds": self.user_req_window},
            )

        # Check endpoint burst limit
        burst_key = self.store._key("burst", user_id, endpoint)
        allowed, remaining = self.store.increment_and_check(
            burst_key, self.endpoint_burst_limit, self.endpoint_burst_window
        )
        if not allowed:
            return self._rate_limit_response(
                "ENDPOINT_BURST_LIMIT_EXCEEDED",
                f"Endpoint burst quota exceeded ({self.endpoint_burst_limit} per {self.endpoint_burst_window}s)",
                self.endpoint_burst_window,
                {"limit": self.endpoint_burst_limit, "window_seconds": self.endpoint_burst_window},
            )

        response: Response = await call_next(request)
        # Set rate-limit headers
        response.headers["X-RateLimit-Limit"] = str(self.user_req_limit)
        response.headers["X-RateLimit-Remaining"] = str(
            self.store.current_count(user_key, self.user_req_window)
        )
        return response

    def _rate_limit_response(self, code: str, message: str, retry_after: int, details: dict) -> JSONResponse:
        logger.warning("Rate limit hit: code=%s retry_after=%ds", code, retry_after)
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content=build_error(
                code=code,
                message=message,
                field="request",
                details=details,
            ),
        )
```

### 2.3 Rollout Gate Middleware

**Implementation in `app/middleware/ai_rollout_gate.py`:**

```python
"""Rollout gate middleware — feature flags, tenant/role allowlists, percentage rollout."""
from __future__ import annotations
import os
import hashlib
import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.utils.error_envelope import build_error

logger = logging.getLogger(__name__)


class RolloutGateMiddleware(BaseHTTPMiddleware):
    """Evaluates rollout gates for AI endpoints.

    Gates (evaluated in order; first rejecting gate short-circuits):
      1. Global kill switch: AI_AUTHORING_ENABLED
      2. Environment allowlist: AI_AUTHORING_ENABLED_ENVS
      3. Tenant allowlist: AI_TENANT_ALLOWLIST
      4. Role allowlist: AI_ROLE_ALLOWLIST
      5. Percentage rollout: AI_ROLLOUT_PERCENTAGE
    """

    AI_PREFIX = "/api/v1/ai/"

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self._reload_config()

    def _reload_config(self):
        """Reload all gate config from env vars (callable at runtime for hot-reload)."""
        self.global_enabled = os.getenv("AI_AUTHORING_ENABLED", "false").lower() in ("true", "1", "yes")
        self.enabled_envs_str = os.getenv("AI_AUTHORING_ENABLED_ENVS", "staging,production")
        self._enabled_envs = {e.strip().lower() for e in self.enabled_envs_str.split(",") if e.strip()}
        self.tenant_allowlist_str = os.getenv("AI_TENANT_ALLOWLIST", "")
        self._tenant_allowlist = {t.strip() for t in self.tenant_allowlist_str.split(",") if t.strip()}
        self.role_allowlist_str = os.getenv("AI_ROLE_ALLOWLIST", "admin,instructor,author")
        self._role_allowlist = {r.strip().lower() for r in self.role_allowlist_str.split(",") if r.strip()}
        rollout_pct = os.getenv("AI_ROLLOUT_PERCENTAGE", "100")
        try:
            self.rollout_percentage = max(0, min(100, int(rollout_pct)))
        except ValueError:
            self.rollout_percentage = 100
        self.current_env = os.getenv("ENVIRONMENT", "development").lower()

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(self.AI_PREFIX):
            return await call_next(request)

        # Gate 1: Global kill switch
        if not self.global_enabled:
            logger.info("Rollout gate blocked: global kill switch (AI_AUTHORING_ENABLED=false)")
            return self._blocked_response("global_kill_switch")

        # Gate 2: Environment allowlist
        if self.current_env not in self._enabled_envs:
            logger.info("Rollout gate blocked: environment '%s' not in allowlist", self.current_env)
            return self._blocked_response("environment_not_allowed")

        # Resolve identity
        tenant_id = getattr(request.state, "tenant_id", "default")
        user_id = getattr(request.state, "user_id", "anonymous")
        user_role = getattr(request.state, "role", "anonymous")

        # Gate 3: Tenant allowlist
        if self._tenant_allowlist and tenant_id not in self._tenant_allowlist:
            logger.info("Rollout gate blocked: tenant '%s' not in allowlist", tenant_id)
            return self._blocked_response("tenant_not_in_allowlist")

        # Gate 4: Role allowlist
        if user_role.lower() not in self._role_allowlist:
            logger.info("Rollout gate blocked: role '%s' not in allowlist", user_role)
            return self._blocked_response("role_not_allowed")

        # Gate 5: Percentage rollout
        if self.rollout_percentage < 100:
            # Deterministic hash of tenant+user
            seed = f"{tenant_id}:{user_id}"
            hash_val = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % 100
            if hash_val >= self.rollout_percentage:
                logger.info("Rollout gate blocked: user hash %d >= rollout %d%%", hash_val, self.rollout_percentage)
                return self._blocked_response("rollout_percentage")

        return await call_next(request)

    def _blocked_response(self, gate: str) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=build_error(
                code="FEATURE_NOT_AVAILABLE",
                message="The requested resource was not found.",
                field="request",
                details={"gate": gate},
            ),
        )
```

### 2.4 Telemetry Events Database Table

**Table: `ai_telemetry_events`**

```sql
CREATE TABLE ai_telemetry_events (
    id              SERIAL PRIMARY KEY,
    event_id        VARCHAR(64) UNIQUE NOT NULL,
    trace_id        VARCHAR(64) NOT NULL,
    session_id      VARCHAR(64) REFERENCES ai_sessions(session_id) ON DELETE SET NULL,
    event_type      VARCHAR(64) NOT NULL,  -- 'rate_limit_exceeded', 'rollout_gate_blocked',
                                           -- 'llm_call', 'tool_call', 'proposal_created',
                                           -- 'proposal_applied', 'validation_result',
                                           -- 'context_refresh', 'model_fallback'
    event_version   INTEGER NOT NULL DEFAULT 1,
    payload         JSONB NOT NULL,  -- Event-specific data
    severity        VARCHAR(16) NOT NULL DEFAULT 'info'
                    CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical')),

    -- Identity
    tenant_id       VARCHAR(128),
    user_id         VARCHAR(128),

    -- Timing
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    duration_ms     INTEGER,  -- Optional: execution time for the event

    -- Indexes for query performance
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_telemetry_trace ON ai_telemetry_events(trace_id);
CREATE INDEX idx_telemetry_type ON ai_telemetry_events(event_type);
CREATE INDEX idx_telemetry_tenant ON ai_telemetry_events(tenant_id);
CREATE INDEX idx_telemetry_occurred ON ai_telemetry_events(occurred_at DESC);
CREATE INDEX idx_telemetry_session ON ai_telemetry_events(session_id);
```

**SQLAlchemy ORM Model in `app/models/ai_telemetry.py`:**

```python
"""ORM model for AI telemetry events — observability and offline analysis."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, ForeignKey, TIMESTAMP, BigInteger
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMPTZ

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class AITelemetryEventRecord(Base):
    __tablename__ = "ai_telemetry_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, default=_uuid)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("ai_sessions.session_id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    event_type: Mapped[str] = mapped_column(String(64))
    event_version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="info")

    tenant_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, default=datetime.utcnow)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, default=datetime.utcnow)
```

### 2.5 Metrics Definitions (Prometheus)

**File: `app/services/ai/metrics.py`**

```python
"""Prometheus metric definitions for AI observability."""
from __future__ import annotations

from prometheus_client import Counter, Histogram, Gauge
from prometheus_client import REGISTRY


def _safe_register(metric):
    """Register a metric, suppressing duplicate-registration errors on reload."""
    try:
        REGISTRY.register(metric)
    except ValueError:
        pass
    return metric


# ── Counters ──────────────────────────────────────────────────────────────────

ai_requests_total = Counter(
    "ai_requests_total",
    "Total AI requests processed",
    ["endpoint", "method", "status"],
)

ai_tool_calls_total = Counter(
    "ai_tool_calls_total",
    "Total AI tool calls made",
    ["tool_name", "status"],
)

ai_llm_calls_total = Counter(
    "ai_llm_calls_total",
    "Total LLM provider calls",
    ["provider", "model", "status"],
)

ai_proposals_created = Counter(
    "ai_proposals_created",
    "Total AI proposals created",
    ["operation"],
)

ai_proposals_applied = Counter(
    "ai_proposals_applied",
    "Total AI proposals applied, by outcome",
    ["operation", "status"],
)

ai_rate_limits_exceeded = Counter(
    "ai_rate_limits_exceeded",
    "Total rate limit exceeded events",
    ["tenant", "endpoint", "limit_type"],
)

ai_rollout_gate_blocked = Counter(
    "ai_rollout_gate_blocked",
    "Total rollout gate blocks",
    ["gate_name"],
)

ai_token_usage_total = Counter(
    "ai_token_usage_total",
    "Total token consumption by model and type",
    ["model", "token_type"],  # token_type: input | output
)

ai_validation_errors_total = Counter(
    "ai_validation_errors_total",
    "Total validation errors by category",
    ["category"],  # schema, business_rule, accessibility, export
)

ai_safety_events_total = Counter(
    "ai_safety_events_total",
    "Total safety guardrail events",
    ["rule_triggered", "action"],  # action: blocked | redacted | logged
)

# ── Histograms ────────────────────────────────────────────────────────────────

ai_llm_latency_seconds = Histogram(
    "ai_llm_latency_seconds",
    "LLM provider response latency in seconds",
    ["provider", "model"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
)

ai_request_latency_seconds = Histogram(
    "ai_request_latency_seconds",
    "HTTP request latency in seconds",
    ["endpoint"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

ai_tool_call_duration_seconds = Histogram(
    "ai_tool_call_duration_seconds",
    "Duration of individual tool calls in seconds",
    ["tool_name"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)

ai_tool_call_rounds_per_turn = Histogram(
    "ai_tool_call_rounds_per_turn",
    "Number of tool-call rounds per chat turn",
    buckets=(1, 2, 3, 5, 8, 10, 15, 20),
)

ai_proposal_lifecycle_duration_seconds = Histogram(
    "ai_proposal_lifecycle_duration_seconds",
    "Time from proposal creation to apply or expiry",
    ["operation"],
    buckets=(1, 5, 30, 60, 300, 900, 3600),
)

# ── Gauges ────────────────────────────────────────────────────────────────────

ai_active_sessions = Gauge(
    "ai_active_sessions",
    "Current number of active AI sessions",
    ["tenant"],
)

ai_pending_proposals = Gauge(
    "ai_pending_proposals",
    "Current number of pending proposals",
    ["operation"],
)

ai_rate_limit_remaining = Gauge(
    "ai_rate_limit_remaining",
    "Remaining requests in current rate-limit window",
    ["tenant", "user", "limit_type"],
)
```

### 2.6 Pydantic DTOs

**File: `app/routers/ai_observability_dtos.py`**:

```python
"""Pydantic models for AI observability, rate limit, and rollout endpoints."""
from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class RateLimitStatusResponse(BaseModel):
    """Current rate limit status for the requesting user/tenant."""
    limit: int
    remaining: int
    reset_at: datetime
    limit_type: str = Field(..., description="user | tenant | endpoint_burst")


class UsageSummaryResponse(BaseModel):
    """Usage summary for the requesting user/tenant."""
    requests_this_minute: int
    requests_this_hour: int
    requests_today: int
    tokens_input_today: int
    tokens_output_today: int
    estimated_cost_usd_today: float
    tenant_monthly_cost_usd: float
    tenant_monthly_budget_usd: float


class RolloutGateStatusResponse(BaseModel):
    """Current rollout gate status for the requesting user."""
    ai_enabled: bool
    environment_allowed: bool
    tenant_allowed: bool
    role_allowed: bool
    rollout_percentage_eligible: bool
    gate_blocked_by: Optional[str] = None


class MetricsEndpointResponse(BaseModel):
    """Prometheus metrics response (text/plain, not modeled in JSON)."""
    pass  # Handled as raw text response


class TelemetryQueryParams(BaseModel):
    trace_id: Optional[str] = None
    event_type: Optional[str] = None
    tenant_id: Optional[str] = None
    session_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
```

### 2.7 API Contracts

#### GET /api/v1/ai/observability/rate-limit-status

Returns the current rate-limit status for the authenticated user/tenant.

**Response 200:**
```json
{
  "limit": 100,
  "remaining": 87,
  "reset_at": "2026-06-14T10:01:00Z",
  "limit_type": "user"
}
```

**Response 429 (from middleware — all endpoints):**
```json
{
  "code": "USER_RATE_LIMIT_EXCEEDED",
  "field": "request",
  "message": "User request quota exceeded (100 per 60s)",
  "details": {
    "limit": 100,
    "window_seconds": 60,
    "retry_after_seconds": 45
  }
}
```

#### GET /api/v1/ai/observability/usage-summary

Returns cumulative usage for the current user/tenant.

**Response 200:**
```json
{
  "requests_this_minute": 12,
  "requests_this_hour": 234,
  "requests_today": 890,
  "tokens_input_today": 450000,
  "tokens_output_today": 85000,
  "estimated_cost_usd_today": 2.45,
  "tenant_monthly_cost_usd": 145.30,
  "tenant_monthly_budget_usd": 500.00
}
```

#### GET /api/v1/ai/observability/rollout-status

Returns the rollout gate evaluation for the current request context.

**Response 200:**
```json
{
  "ai_enabled": true,
  "environment_allowed": true,
  "tenant_allowed": true,
  "role_allowed": true,
  "rollout_percentage_eligible": true,
  "gate_blocked_by": null
}
```

**Response 200 (when blocked):**
```json
{
  "ai_enabled": false,
  "environment_allowed": true,
  "tenant_allowed": true,
  "role_allowed": false,
  "rollout_percentage_eligible": true,
  "gate_blocked_by": "role_not_allowed"
}
```

#### GET /api/v1/ai/observability/telemetry

Queries persisted telemetry events. Admin-only.

**Response 200:**
```json
{
  "events": [
    {
      "event_id": "evt_abc123",
      "trace_id": "a1b2c3d4-...",
      "session_id": "sess_001",
      "event_type": "llm_call",
      "event_version": 1,
      "payload": {
        "provider": "anthropic",
        "model": "claude-sonnet-4",
        "input_tokens": 4523,
        "output_tokens": 1287,
        "status": "success",
        "duration_ms": 3450
      },
      "severity": "info",
      "tenant_id": "tenant_001",
      "user_id": "user_042",
      "occurred_at": "2026-06-14T09:23:45Z",
      "duration_ms": 3450
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

#### GET /api/v1/metrics

Prometheus metrics endpoint. Protected by admin auth.

**Response 200:** `text/plain` with Prometheus exposition format:
```
# HELP ai_requests_total Total AI requests processed
# TYPE ai_requests_total counter
ai_requests_total{endpoint="/api/v1/ai/chat",method="POST",status="200"} 142.0
ai_requests_total{endpoint="/api/v1/ai/proposals/delete-page",method="POST",status="200"} 23.0
# HELP ai_llm_latency_seconds LLM provider response latency
# TYPE ai_llm_latency_seconds histogram
ai_llm_latency_seconds_bucket{provider="anthropic",model="claude-sonnet-4",le="1.0"} 12.0
ai_llm_latency_seconds_bucket{provider="anthropic",model="claude-sonnet-4",le="5.0"} 89.0
ai_llm_latency_seconds_bucket{provider="anthropic",model="claude-sonnet-4",le="+Inf"} 95.0
ai_llm_latency_seconds_count{provider="anthropic",model="claude-sonnet-4"} 95.0
```

### 2.8 Service Signatures

**File: `app/services/ai/telemetry_service.py`**

```python
"""Service for recording AI telemetry events to the database."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_telemetry import AITelemetryEventRecord


class TelemetryService:
    """Persists AI telemetry events for offline querying and analysis.

    This service is non-blocking: failures to write telemetry are logged
    but never bubble up to the caller. Use fire-and-forget or background
    task patterns for production.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def record_event(
        self,
        trace_id: str,
        event_type: str,
        payload: dict,
        severity: str = "info",
        session_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[str]:
        """Persist a telemetry event. Returns event_id on success, None on failure."""
        try:
            record = AITelemetryEventRecord(
                event_id=str(uuid.uuid4()),
                trace_id=trace_id,
                session_id=session_id,
                event_type=event_type,
                event_version=1,
                payload=payload,
                severity=severity,
                tenant_id=tenant_id,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
                duration_ms=duration_ms,
            )
            self.session.add(record)
            await self.session.flush()
            return record.event_id
        except Exception:
            import logging
            logger = logging.getLogger(__name__)
            logger.exception("Failed to persist telemetry event (trace=%s)", trace_id)
            return None

    async def query_events(
        self,
        trace_id: Optional[str] = None,
        event_type: Optional[str] = None,
        session_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Query telemetry events with filters. Returns (events, total_count)."""
        from sqlalchemy import select, func, and_

        q = select(AITelemetryEventRecord)
        count_q = select(func.count(AITelemetryEventRecord.id))

        conditions = []
        if trace_id:
            conditions.append(AITelemetryEventRecord.trace_id == trace_id)
        if event_type:
            conditions.append(AITelemetryEventRecord.event_type == event_type)
        if session_id:
            conditions.append(AITelemetryEventRecord.session_id == session_id)
        if tenant_id:
            conditions.append(AITelemetryEventRecord.tenant_id == tenant_id)
        if start_time:
            conditions.append(AITelemetryEventRecord.occurred_at >= start_time)
        if end_time:
            conditions.append(AITelemetryEventRecord.occurred_at <= end_time)

        if conditions:
            q = q.where(and_(*conditions))
            count_q = count_q.where(and_(*conditions))

        q = q.order_by(AITelemetryEventRecord.occurred_at.desc())
        q = q.offset(offset).limit(limit)

        total_result = await self.session.execute(count_q)
        total = total_result.scalar() or 0

        result = await self.session.execute(q)
        records = result.scalars().all()

        events = []
        for r in records:
            events.append({
                "event_id": r.event_id,
                "trace_id": r.trace_id,
                "session_id": r.session_id,
                "event_type": r.event_type,
                "event_version": r.event_version,
                "payload": r.payload,
                "severity": r.severity,
                "tenant_id": r.tenant_id,
                "user_id": r.user_id,
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
                "duration_ms": r.duration_ms,
            })

        return events, total
```

### 2.9 API Router

**File: `app/routers/ai_observability.py`**

```python
"""AI Observability, rate limit status, and rollout gate endpoints."""
from __future__ import annotations
import os
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response as StarletteResponse

from app.db.config import get_session
from app.utils.error_envelope import api_http_exception
from app.middleware.ai_rate_limiter import InProcessRateLimitStore
from app.middleware.ai_rollout_gate import RolloutGateMiddleware
from app.services.ai.telemetry_service import TelemetryService

from app.routers.ai_observability_dtos import (
    RateLimitStatusResponse,
    UsageSummaryResponse,
    RolloutGateStatusResponse,
    TelemetryQueryParams,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai/observability", tags=["AI Observability"])

# Singleton reference set at startup (avoids circular import)
_rate_limit_store: InProcessRateLimitStore | None = None
_rollout_gate: RolloutGateMiddleware | None = None


def configure_observability(store: InProcessRateLimitStore, gate: RolloutGateMiddleware):
    """Set singleton references for rate limit store and rollout gate."""
    global _rate_limit_store, _rollout_gate
    _rate_limit_store = store
    _rollout_gate = gate


@router.get(
    "/rate-limit-status",
    response_model=RateLimitStatusResponse,
    summary="Current rate limit status for the caller",
)
async def get_rate_limit_status(
    request: Request,
):
    """Returns how many requests the current user/tenant has remaining."""
    if not _rate_limit_store:
        raise api_http_exception(503, "RATE_LIMITER_NOT_READY", "Rate limiter not initialized")

    user_id = getattr(request.state, "user_id", "anonymous")
    tenant_id = getattr(request.state, "tenant_id", "default")
    user_key = _rate_limit_store._key("user", user_id, "req")

    window_seconds = int(os.getenv("AI_RATE_LIMIT_USER_REQUESTS_WINDOW", "60"))
    limit = int(os.getenv("AI_RATE_LIMIT_USER_REQUESTS", "100"))
    remaining = max(0, limit - _rate_limit_store.current_count(user_key, window_seconds))
    reset_at = datetime.utcnow()

    return RateLimitStatusResponse(
        limit=limit,
        remaining=remaining,
        reset_at=reset_at,
        limit_type="user",
    )


@router.get(
    "/usage-summary",
    response_model=UsageSummaryResponse,
    summary="Usage summary for the current user/tenant",
)
async def get_usage_summary(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Returns cumulative token usage and cost estimates."""
    user_id = getattr(request.state, "user_id", "anonymous")
    tenant_id = getattr(request.state, "tenant_id", "default")

    telemetry = TelemetryService(session)

    # Count events today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    events_today, _ = await telemetry.query_events(
        tenant_id=tenant_id,
        start_time=today_start,
        limit=10000,
    )

    tokens_input = 0
    tokens_output = 0
    for evt in events_today:
        if evt["event_type"] == "llm_call":
            payload = evt.get("payload", {})
            tokens_input += payload.get("input_tokens", 0)
            tokens_output += payload.get("output_tokens", 0)

    # Rough cost estimate (example rates)
    cost_per_input_million = float(os.getenv("AI_COST_PER_MILLION_INPUT_TOKENS", "3.0"))
    cost_per_output_million = float(os.getenv("AI_COST_PER_MILLION_OUTPUT_TOKENS", "15.0"))
    estimated_cost = (tokens_input / 1_000_000 * cost_per_input_million) + \
                     (tokens_output / 1_000_000 * cost_per_output_million)

    return UsageSummaryResponse(
        requests_this_minute=0,  # Computed from in-memory store in real implementation
        requests_this_hour=0,
        requests_today=len(events_today),
        tokens_input_today=tokens_input,
        tokens_output_today=tokens_output,
        estimated_cost_usd_today=round(estimated_cost, 4),
        tenant_monthly_cost_usd=0.0,  # Aggregated from monthly query
        tenant_monthly_budget_usd=float(os.getenv("AI_TENANT_MONTHLY_BUDGET_USD", "500")),
    )


@router.get(
    "/rollout-status",
    response_model=RolloutGateStatusResponse,
    summary="Current rollout gate status for the caller",
)
async def get_rollout_status(request: Request):
    """Evaluates all rollout gates for the current request context."""
    if not _rollout_gate:
        raise api_http_exception(503, "ROLLOUT_GATE_NOT_READY", "Rollout gate not initialized")

    _rollout_gate._reload_config()

    user_id = getattr(request.state, "user_id", "anonymous")
    tenant_id = getattr(request.state, "tenant_id", "default")
    user_role = getattr(request.state, "role", "anonymous")

    import hashlib

    env_ok = _rollout_gate.current_env in _rollout_gate._enabled_envs
    tenant_ok = not _rollout_gate._tenant_allowlist or tenant_id in _rollout_gate._tenant_allowlist
    role_ok = user_role.lower() in _rollout_gate._role_allowlist

    if _rollout_gate.rollout_percentage >= 100:
        pct_ok = True
    else:
        seed = f"{tenant_id}:{user_id}"
        hash_val = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % 100
        pct_ok = hash_val < _rollout_gate.rollout_percentage

    gates = {
        "global_kill_switch": _rollout_gate.global_enabled,
        "environment_not_allowed": env_ok,
        "tenant_not_in_allowlist": tenant_ok,
        "role_not_allowed": role_ok,
        "rollout_percentage": pct_ok,
    }

    blocked_by = next((k for k, v in gates.items() if not v), None)

    return RolloutGateStatusResponse(
        ai_enabled=all(gates.values()),
        environment_allowed=env_ok,
        tenant_allowed=tenant_ok,
        role_allowed=role_ok,
        rollout_percentage_eligible=pct_ok,
        gate_blocked_by=blocked_by,
    )


@router.get("/telemetry", summary="Query telemetry events (admin only)")
async def query_telemetry(
    trace_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Query persisted telemetry events with filters."""
    telemetry = TelemetryService(session)
    events, total = await telemetry.query_events(
        trace_id=trace_id,
        event_type=event_type,
        session_id=session_id,
        tenant_id=tenant_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )
    return {"events": events, "total": total, "limit": limit, "offset": offset}


# Mount Prometheus metrics endpoint at /api/v1/metrics (not under /observability)
prometheus_router = APIRouter(tags=["Metrics"])


@prometheus_router.get("/api/v1/metrics", summary="Prometheus metrics endpoint")
async def get_metrics(request: Request):
    """Exposes Prometheus metrics in text format."""
    # Auth check: admin only
    role = getattr(request.state, "role", "anonymous")
    if role not in ("admin", "superadmin"):
        raise api_http_exception(403, "FORBIDDEN", "Admin access required")
    return StarletteResponse(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
```

### 2.10 Environment Variables

Add to `.env.example` and `.env`:

```ini
# ============================================
# AI Observability
# ============================================
# Trace ID format: UUID v4. Clients may send X-Trace-ID header.
AI_TELEMETRY_ENABLED=true

# ============================================
# AI Rate Limits
# ============================================
# Per-user requests per minute window
AI_RATE_LIMIT_USER_REQUESTS=100
# Per-tenant requests per minute window
AI_RATE_LIMIT_TENANT_REQUESTS=1000
# Per-endpoint burst limit per 10-second window
AI_RATE_LIMIT_ENDPOINT_BURST=20
# Per-user daily token limit (input + output)
AI_RATE_LIMIT_USER_DAILY_TOKENS=100000
# Per-tenant daily token limit
AI_RATE_LIMIT_TENANT_DAILY_TOKENS=1000000

# ============================================
# AI Rollout Gates
# ============================================
# Master switch for all AI authoring features
AI_AUTHORING_ENABLED=false
# Comma-separated list of environments where AI is enabled
AI_AUTHORING_ENABLED_ENVS=staging,production
# Comma-separated tenant allowlist (empty = all tenants)
AI_TENANT_ALLOWLIST=
# Comma-separated role allowlist (lowercase)
AI_ROLE_ALLOWLIST=admin,instructor,author
# Percentage of users who see AI (0-100). 100 = all eligible.
AI_ROLLOUT_PERCENTAGE=100

# ============================================
# AI Cost Tracking
# ============================================
# Per-model pricing for cost estimation (USD per million tokens)
AI_COST_PER_MILLION_INPUT_TOKENS=3.00
AI_COST_PER_MILLION_OUTPUT_TOKENS=15.00
# Monthly cost cap per tenant (USD)
AI_TENANT_MONTHLY_BUDGET_USD=500.00

# ============================================
# AI Monitoring
# ============================================
# Sentry DSN for error tracking (production)
# SENTRY_DSN=https://your-sentry-dsn@sentry.io/project-id
```

### 2.11 Alembic Migration

**File: `alembic/versions/20260614_0002_add_ai_telemetry_events.py`**

```python
"""Add ai_telemetry_events table for AI observability.

Revision ID: 20260614_0002
Revises: 20260614_0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMPTZ

revision = "20260614_0002"
down_revision = "20260614_0001"  # Previous AI persistence migration
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_telemetry_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="info"),
        sa.Column("tenant_id", sa.String(128), nullable=True),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("occurred_at", TIMESTAMPTZ(), nullable=False, server_default=sa.func.now()),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["session_id"], ["ai_sessions.session_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("idx_telemetry_trace", "ai_telemetry_events", ["trace_id"])
    op.create_index("idx_telemetry_type", "ai_telemetry_events", ["event_type"])
    op.create_index("idx_telemetry_tenant", "ai_telemetry_events", ["tenant_id"])
    op.create_index(
        "idx_telemetry_occurred", "ai_telemetry_events",
        [sa.text("occurred_at DESC")]
    )
    op.create_index("idx_telemetry_session", "ai_telemetry_events", ["session_id"])

    # Add trace_id to existing AI tables
    op.add_column("ai_sessions", sa.Column("trace_id", sa.String(64), nullable=True))
    op.add_column("ai_proposals", sa.Column("trace_id", sa.String(64), nullable=True))
    op.add_column("ai_audit_logs", sa.Column("trace_id", sa.String(64), nullable=True))
    op.add_column("outbox_events", sa.Column("trace_id", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("outbox_events", "trace_id")
    op.drop_column("ai_audit_logs", "trace_id")
    op.drop_column("ai_proposals", "trace_id")
    op.drop_column("ai_sessions", "trace_id")
    op.drop_table("ai_telemetry_events")
```

### 2.12 Main Application Registration

**In `app/main.py`**:

```python
# ── New imports ──────────────────────────────
from app.middleware.ai_telemetry import AITelemetryMiddleware
from app.middleware.ai_rate_limiter import RateLimitMiddleware, InProcessRateLimitStore
from app.middleware.ai_rollout_gate import RolloutGateMiddleware
from app.routers import ai_observability
from app.services.ai.metrics import (
    ai_requests_total, ai_request_latency_seconds,
    ai_llm_calls_total, ai_tool_calls_total,
    ai_proposals_created, ai_proposals_applied,
    ai_rate_limits_exceeded, ai_rollout_gate_blocked,
    ai_token_usage_total, ai_active_sessions,
)

# ── In lifespan startup section ──────────────
import app.models.ai_telemetry  # noqa: F401

# ── After app = FastAPI(...) ─────────────────
# Initialize rate-limit store (singleton)
_rate_limit_store = InProcessRateLimitStore()

# Add middleware (order matters: outermost first)
app.add_middleware(
    AITelemetryMiddleware,
    metrics_registry={
        "requests_total": ai_requests_total,
        "request_latency_seconds": ai_request_latency_seconds,
    },
)
app.add_middleware(
    RolloutGateMiddleware,
)
app.add_middleware(
    RateLimitMiddleware,
    store=_rate_limit_store,
)

# ── Configure observability router singleton ──
from app.middleware.ai_rollout_gate import RolloutGateMiddleware
# The rollout gate middleware instance is retrieved from app.user_middleware
gate_mw = None
for mw in app.user_middleware:
    if mw.cls == RolloutGateMiddleware:
        gate_mw = mw.options  # the instance is stored as the first positional arg
        break
# In practice, you'd store the instance reference directly; simplified here.

from app.routers.ai_observability import configure_observability
configure_observability(_rate_limit_store, RolloutGateMiddleware(app))

# ── Register routers ────────────────────────
api_router.include_router(ai_observability.router)
api_router.include_router(ai_observability.prometheus_router)
```

### 2.13 Grafana Dashboard JSON

A reference file `docs/AI_Implemenation/01_SystemArchitecture/grafana_ai_dashboard.json` is provided with the following panels:
- **AI Request Volume** — Total requests by endpoint (bar chart, last 1h)
- **Request Latency p50/p95/p99** — Latency histogram by endpoint
- **LLM Provider Calls** — Call volume by provider/model (stacked bar)
- **LLM Latency** — Latency by provider/model (heatmap)
- **Token Usage** — Input/output tokens per model (area chart)
- **Error Rate** — 4xx and 5xx rates by endpoint
- **Rate Limit Hits** — Rate limit exceeded events by limit type
- **Rollout Gate Blocks** — Blocked requests by gate name
- **Active Sessions** — Current active sessions by tenant (gauge)
- **Proposal Status** — Proposals created vs applied by operation
- **Cost Tracking** — Daily estimated cost by tenant (area chart)
- **Tool Call Distribution** — Tool call volume by tool and status
- **Safety Events** — Guardrail triggers by rule (bar chart)

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Requirement | Target | Measurement |
|---|---|---|
| Middleware overhead (trace + rate limit + gate) | < 5 ms p95 per request | Addition to baseline endpoint latency |
| Rate limit store lookup | < 2 ms p99 | In-process dict or Redis GET |
| Metrics endpoint scrape duration | < 100 ms | Prometheus scrape duration |
| Telemetry event persistence | < 50 ms p95 | Time to INSERT into `ai_telemetry_events` |
| Rate limit check on 429 path | < 1 ms | Early return before routing |

### 3.2 Rate Limit Accuracy

| Requirement | Implementation |
|---|---|
| Sliding window precision | Within 1 second of actual window boundary for in-process store |
| Counter consistency | Per-key mutex or atomic increment (Redis INCR for production) |
| Fail-open behavior | If rate-limit store is unreachable, allow request, log warning |
| Counter reset | In-memory counters lost on restart; Redis counters survive |

### 3.3 Security

| Requirement | Implementation |
|---|---|
| Trace ID not from untrusted source | Backend validates UUID v4 format; regenerates if invalid |
| Rate limit error not leaking info | Error details include limit/window but never internal state |
| Rollout gate not revealing feature existence | Blocked requests return 404 (not 403) |
| Metrics endpoint protected | Admin-only access; returns 403 for non-admin roles |
| Telemetry query protected | Admin-only; tenant-scoped to prevent cross-tenant data access |

### 3.4 Availability

| Requirement | Implementation |
|---|---|
| Rate limiter failure | Fail-open: allow request, log error, emit `ai_rate_limiter_failures` metric |
| Rollout gate failure | Fail-closed: block request (conservative default) |
| Telemetry write failure | Non-blocking: log error, continue request |
| Metrics endpoint failure | Does not affect application availability |

### 3.5 Observability Targets

| Requirement | Implementation |
|---|---|
| Trace ID coverage | All `/api/v1/ai/*` requests |
| Trace ID persistence | In all AI-related DB records (`ai_telemetry_events`, `ai_audit_logs`, `ai_proposals`, `ai_sessions`, `outbox_events`) |
| Metric cardinality bound | Labels bounded: endpoints (< 20), providers (< 5), models (< 10), tools (< 15), tenants (< 1000) |
| Log retention | 30 days in aggregation system (Grafana Loki/Elasticsearch) |
| Metric retention | 90 days in Prometheus/Thanos |
| Alert on rate limit > 80% | Warning when any user exceeds 80% of daily token limit |
| Alert on error rate > 5% | Warning when any endpoint exceeds 5% 5xx rate over 5 minutes |

---

## 4. Current State

### 4.1 What Exists Today

1. **Feature Flags**: `app/utils/feature_flags.py` defines a `FeatureFlagService` with environment-based flags including `rate_limiting`, `ai_suggestions`, and `performance_monitoring`. The `rate_limiting` flag exists but has no implementation. The `require_feature_async` dependency returns 404 for disabled features.

2. **Health Endpoints**: `app/routers/health.py` provides `/health`, `/health/detailed`, `/health/ready`, `/health/live`. These are basic K8s-style probes and do not include AI-specific health metrics.

3. **Logging**: The application uses Python `logging.getLogger(__name__)` throughout. There is no structured logging, no trace ID propagation, and no context variable for request-scoped metadata.

4. **Error Envelope**: `app/utils/error_envelope.py` provides `build_error()` and `api_http_exception()` returning `{code, field, message, details}`. This pattern should be used for all rate limit and rollout gate error responses.

5. **Analytics Router**: `app/routers/analytics.py` provides course-level learner analytics (scores, completion, interaction events). This is learner-facing analytics, not operational observability for AI.

6. **Environment Configuration**: `.env.example` has placeholders for `SENTRY_DSN` (commented out) and `LOG_LEVEL`. No rate limit, rollout gate, or telemetry config vars exist.

7. **No Middleware Layer**: There is no middleware for request tracing, rate limiting, or feature gating beyond the basic CORS middleware.

8. **No Metrics Exposure**: There is no Prometheus metrics endpoint or metric registration in the codebase.

9. **No Telemetry Database Table**: The `ai_telemetry_events` table does not exist.

10. **Dependencies**: `prometheus_client` is not in `requirements.txt`. Sentry SDK is commented out in `requirements.prod.txt`.

### 4.2 What is Missing

1. `AITelemetryMiddleware` — trace ID injection, request timing, structured logging
2. `RateLimitMiddleware` — sliding-window counters per user, tenant, endpoint
3. `RolloutGateMiddleware` — global kill switch, environment/tenant/role gates, percentage rollout
4. `AITelemetryEventRecord` ORM model and `ai_telemetry_events` table
5. `TelemetryService` — event persistence with non-blocking semantics
6. `Metrics definitions` — Prometheus counters, histograms, gauges
7. `ai_observability` router — rate-limit status, usage summary, rollout status, telemetry query
8. `/api/v1/metrics` endpoint — Prometheus scrape target, admin-protected
9. Alembic migration — create `ai_telemetry_events`, add `trace_id` to existing AI tables
10. `trace_id` columns on `ai_sessions`, `ai_proposals`, `ai_audit_logs`, `outbox_events`
11. Environment variables — all rate limit, rollout gate, cost tracking, and telemetry config
12. `prometheus_client` added to `requirements.txt` / `requirements.prod.txt`
13. `sentry-sdk[fastapi]` uncommented and configured in `requirements.prod.txt`
14. Grafana dashboard JSON template
15. Unit and integration tests for all middleware components

### 4.3 Dependencies on Earlier Stories

| Story | Dependency |
|---|---|
| US-AI-002 | Feature flag configuration pattern (`AI_AUTHORING_ENABLED`), environment detection |
| US-AI-003 | Isolated AI API module structure (`/api/v1/ai/*` routes) |
| US-AI-004 | `ai_sessions`, `ai_proposals`, `ai_audit_logs`, `outbox_events` tables (need `trace_id` columns added) |
| US-AI-010 | Apply safety (audit/outbox records must carry trace IDs) |

---

## 5. Expansion Points

### 5.1 Distributed Rate Limit Store (Redis) (Post-MVP)

The MVP uses an in-process `InProcessRateLimitStore` which does not survive restarts and does not work across multiple workers/instances. A production upgrade should replace it with Redis-backed counters using `INCR` + `EXPIRE` for atomic sliding windows. The `RateLimitMiddleware` should accept a pluggable store interface (`RateLimitStoreProtocol`) so the backend can be swapped without changing business logic.

### 5.2 Adaptive Rate Limiting (Post-MVP)

Instead of static limits, adaptive rate limiting adjusts limits based on historical usage patterns, provider health, and system load. If the LLM provider is returning 429s, the middleware could dynamically reduce the per-user limit. This requires a feedback loop from the LLM provider response processing into the rate limit store.

### 5.3 Per-Model Rate Limits (Post-MVP)

When US-AI-026 (Multi-Provider Model Routing) is implemented, rate limits should differentiate by model tier: cheap/fast models get higher limits, premium models get tighter limits. The `limit_type` label should include the model tier.

### 5.4 Token-Based Rate Limiting (Post-MVP)

The MVP rate limits on request count. A more accurate strategy is token-based rate limiting where each request consumes tokens proportional to its expected cost (input tokens + output tokens * cost_multiplier). This prevents a single token-heavy request from exhausting the quota.

### 5.5 Self-Service Admin UI for Rollout Configuration (Post-MVP)

The MVP configuration is entirely env-var driven. A future story should provide an admin API and UI for:
- Toggling `AI_AUTHORING_ENABLED` per tenant
- Adjusting `AI_ROLLOUT_PERCENTAGE` without restart
- Viewing per-tenant usage dashboards
- Setting per-tenant rate limit overrides

### 5.6 OpenTelemetry Integration (Post-MVP)

The MVP trace ID system is custom. Long-term, it should be replaced with OpenTelemetry for:
- Automatic trace propagation across services
- Integration with distributed tracing backends (Jaeger, Zipkin)
- Standardized span attributes and semantic conventions
- Auto-instrumentation of DB queries, HTTP calls, and LLM calls

### 5.7 Anomaly Detection Alerts (Post-MVP)

Machine learning-based anomaly detection on metric streams (unexpected latency spikes, token usage surges, error rate changes) should be configured in the monitoring system to alert operators before users are impacted.

### 5.8 A/B Test Integration (Post-MVP)

The `AI_ROLLOUT_PERCENTAGE` gate uses deterministic hashing. This cohort assignment can be reused by US-AI-042 (System Prompt A/B Testing) to ensure a user in the 50% rollout consistently gets the same prompt variant, maintaining experiment integrity.

---

## 6. Validation and Test Scenarios

### 6.1 Unit Tests (Service Layer)

**File: `tests/test_ai_middleware/test_ai_telemetry.py`**

```python
class TestTraceIdGeneration:
    async def test_generates_trace_id_when_missing(self, async_client):
        """Request without X-Trace-ID header gets a generated UUID v4."""
        pass

    async def test_uses_client_trace_id_when_valid(self, async_client):
        """Valid UUID v4 in X-Trace-ID header is accepted and propagated."""
        pass

    async def test_rejects_invalid_trace_id_format(self, async_client):
        """Non-UUID trace ID is replaced with a generated one."""
        pass

    async def test_trace_id_in_response_header(self, async_client):
        """Response includes X-Trace-ID header matching request or generated."""
        pass

    async def test_trace_id_context_var_accesible(self, async_client):
        """get_current_trace_id() returns the active trace ID within request scope."""
        pass


class TestRequestTiming:
    async def test_records_latency_metric(self, async_client, mock_metrics):
        """A successful request increments the latency histogram."""
        pass

    async def test_records_status_code_counter(self, async_client, mock_metrics):
        """A successful request increments the requests_total counter with correct status."""
        pass

    async def test_records_4xx_counter(self, async_client, mock_metrics):
        """A 4xx response increments the requests_total counter with 4xx status."""
        pass

    async def test_non_ai_routes_not_instrumented(self, async_client, mock_metrics):
        """Requests outside /api/v1/ai/ do not increment AI metrics."""
        pass
```

**File: `tests/test_ai_middleware/test_ai_rate_limiter.py`**

```python
class TestInProcessRateLimitStore:
    async def test_increment_within_limit_returns_allowed(self):
        """Incrementing below limit returns (True, remaining)."""
        pass

    async def test_increment_exceeding_limit_returns_blocked(self):
        """Incrementing past limit returns (False, 0)."""
        pass

    async def test_window_expiration(self):
        """Entries older than window_seconds are pruned and limit resets."""
        pass

    async def test_current_count_accuracy(self):
        """current_count returns correct count for unexpired entries."""
        pass

    async def test_independent_keys(self):
        """Different keys have independent counters."""
        pass

    async def test_zero_limit_blocks_all(self):
        """A limit of 0 blocks every request."""
        pass


class TestRateLimitMiddleware:
    async def test_user_rate_limit_exceeded_returns_429(self, async_client):
        """Sending more than limit requests in a window returns 429."""
        pass

    async def test_429_response_has_retry_after_header(self, async_client):
        """429 response includes Retry-After header."""
        pass

    async def test_429_response_body_format(self, async_client):
        """429 response body matches error_envelope pattern."""
        pass

    async def test_tenant_rate_limit_exceeded_returns_429(self, async_client):
        """Exceeding tenant-level limit returns 429."""
        pass

    async def test_endpoint_burst_limit_exceeded_returns_429(self, async_client):
        """Exceeding endpoint burst limit returns 429."""
        pass

    async def test_rate_limit_resets_after_window(self, async_client):
        """After the window expires, requests succeed again."""
        pass

    async def test_non_ai_routes_not_rate_limited(self, async_client):
        """Requests outside /api/v1/ai/ are not subject to AI rate limits."""
        pass

    async def test_rate_limit_headers_on_success(self, async_client):
        """Successful responses include X-RateLimit-Limit and X-RateLimit-Remaining."""
        pass

    async def test_rate_limit_store_unavailable_fails_open(self, async_client, monkeypatch):
        """If the store raises an exception, the request is allowed (fail-open)."""
        pass
```

**File: `tests/test_ai_middleware/test_ai_rollout_gate.py`**

```python
class TestRolloutGateMiddleware:
    async def test_global_kill_switch_blocks_all(self, async_client, monkeypatch):
        """AI_AUTHORING_ENABLED=false blocks all AI requests with 404."""
        pass

    async def test_environment_gate_blocks_wrong_env(self, async_client, monkeypatch):
        """AI_AUTHORING_ENABLED_ENVS not matching current env returns 404."""
        pass

    async def test_tenant_allowlist_blocks_unknown_tenant(self, async_client, monkeypatch):
        """Tenant not in AI_TENANT_ALLOWLIST receives 404."""
        pass

    async def test_role_allowlist_blocks_wrong_role(self, async_client, monkeypatch):
        """User role not in AI_ROLE_ALLOWLIST receives 404."""
        pass

    async def test_percentage_rollout_blocks_above_threshold(self, async_client, monkeypatch):
        """User whose hash exceeds AI_ROLLOUT_PERCENTAGE receives 404."""
        pass

    async def test_percentage_rollout_below_threshold_passes(self, async_client, monkeypatch):
        """User whose hash is below AI_ROLLOUT_PERCENTAGE passes through."""
        pass

    async def test_percentage_rollout_deterministic_for_user(self, async_client, monkeypatch):
        """The same user consistently passes or is blocked (deterministic hash)."""
        pass

    async def test_all_gates_pass_returns_next_middleware(self, async_client, monkeypatch):
        """When all gates pass, request proceeds to the next middleware/handler."""
        pass

    async def test_non_ai_routes_not_gated(self, async_client):
        """Requests outside /api/v1/ai/ bypass the rollout gate."""
        pass

    async def test_blocked_response_is_404_not_403(self, async_client, monkeypatch):
        """Blocked requests return 404 (not 403) to avoid information leakage."""
        pass
```

**File: `tests/test_ai_telemetry_service.py`**

```python
class TestTelemetryService:
    async def test_record_event_persists(self, db_session):
        """Recording an event creates a row in ai_telemetry_events."""
        pass

    async def test_record_event_returns_event_id(self, db_session):
        """Successful recording returns the event_id string."""
        pass

    async def test_record_event_failure_does_not_raise(self, db_session, monkeypatch):
        """A database error during recording is logged but does not raise."""
        pass

    async def test_query_by_trace_id(self, db_session):
        """Events can be queried by trace_id."""
        pass

    async def test_query_by_event_type(self, db_session):
        """Events can be queried by event_type."""
        pass

    async def test_query_by_tenant_id(self, db_session):
        """Events can be queried by tenant_id."""
        pass

    async def test_query_by_time_range(self, db_session):
        """Events can be filtered by occurred_at time range."""
        pass

    async def test_query_pagination(self, db_session):
        """Query respects limit and offset parameters."""
        pass

    async def test_query_returns_total_count(self, db_session):
        """Query response includes total matching count independent of pagination."""
        pass
```

### 6.2 Integration Tests (API Layer)

**File: `tests/test_ai_observability_api.py`**

```python
class TestRateLimitStatusAPI:
    async def test_get_rate_limit_status_returns_200(self, async_client, mock_auth):
        """GET /api/v1/ai/observability/rate-limit-status returns 200."""
        pass

    async def test_get_rate_limit_status_response_shape(self, async_client, mock_auth):
        """Response includes limit, remaining, reset_at, limit_type."""
        pass

    async def test_get_rate_limit_status_without_auth_returns_403(self, async_client):
        """Unauthenticated requests are rejected."""
        pass


class TestUsageSummaryAPI:
    async def test_get_usage_summary_returns_200(self, async_client, mock_auth):
        """GET /api/v1/ai/observability/usage-summary returns 200."""
        pass

    async def test_get_usage_summary_includes_cost(self, async_client, mock_auth):
        """Response includes estimated_cost_usd_today."""
        pass

    async def test_get_usage_summary_includes_token_counts(self, async_client, mock_auth):
        """Response includes tokens_input_today and tokens_output_today."""
        pass


class TestRolloutStatusAPI:
    async def test_get_rollout_status_when_enabled(self, async_client, mock_auth, monkeypatch):
        """When all gates pass, ai_enabled is true."""
        pass

    async def test_get_rollout_status_when_blocked(self, async_client, mock_auth, monkeypatch):
        """When a gate blocks, ai_enabled is false and gate_blocked_by is set."""
        pass


class TestTelemetryQueryAPI:
    async def test_query_telemetry_returns_events(self, async_client, mock_admin_auth):
        """GET /api/v1/ai/observability/telemetry returns events list."""
        pass

    async def test_query_telemetry_requires_admin(self, async_client, mock_auth):
        """Non-admin users get 403."""
        pass

    async def test_query_telemetry_pagination(self, async_client, mock_admin_auth):
        """Response includes total, limit, offset."""
        pass


class TestMetricsEndpoint:
    async def test_metrics_endpoint_returns_prometheus_format(self, async_client, mock_admin_auth):
        """GET /api/v1/metrics returns text/plain with Prometheus metrics."""
        pass

    async def test_metrics_endpoint_requires_admin(self, async_client, mock_auth):
        """Non-admin users get 403."""
        pass

    async def test_metrics_includes_counters(self, async_client, mock_admin_auth):
        """Response includes ai_requests_total and other expected metrics."""
        pass
```

### 6.3 E2E Scenarios

**Scenario 1: Full observability trace across a chat turn**
1. Frontend sends `POST /api/v1/ai/chat` with `X-Trace-ID: abc-123`.
2. Backend propagates `abc-123` through tool calls, proposal creation, and LLM call.
3. LLM call emits telemetry event with `event_type=llm_call`, `trace_id=abc-123`.
4. Tool call emits telemetry event with `event_type=tool_call`, `trace_id=abc-123`.
5. Proposal creation emits telemetry event with `event_type=proposal_created`, `trace_id=abc-123`.
6. Response includes `X-Trace-ID: abc-123`.
7. Operator queries `/api/v1/ai/observability/telemetry?trace_id=abc-123` and gets all 3 events.

**Scenario 2: Rate limit exceeded with retry guidance**
1. User sends 101 AI requests within 1 minute (limit is 100).
2. Request 101 returns 429 with `Retry-After: 30` and error body with `code=USER_RATE_LIMIT_EXCEEDED`.
3. Frontend shows "You've reached the rate limit. Please wait 30 seconds and try again."
4. After 60 seconds from the first request, the window resets.
5. User retries and succeeds (200).

**Scenario 3: Rollout gate blocks by tenant allowlist**
1. Operator sets `AI_TENANT_ALLOWLIST=tenant_acme,tenant_globex`.
2. User from `tenant_unknown` sends an AI request.
3. Request returns 404 with `code=FEATURE_NOT_AVAILABLE`.
4. Telemetry event `rollout_gate_blocked` is written with `gate_name=tenant_not_in_allowlist`.
5. User from `tenant_acme` sends an AI request.
6. Request proceeds to the handler (200).

**Scenario 4: Gradual rollout percentage**
1. Operator sets `AI_ROLLOUT_PERCENTAGE=10` (10% of users).
2. Users with hash < 10 can access AI features.
3. Users with hash >= 10 get 404.
4. Operator monitors error rate and feedback for the 10% cohort for 24 hours.
5. Operator increases to `AI_ROLLOUT_PERCENTAGE=50`.
6. Approximately 40% of previously blocked users now get access (deterministic).

**Scenario 5: Metrics endpoint accessible to admins**
1. Admin calls `GET /api/v1/metrics`.
2. Response is `text/plain` with all registered Prometheus metrics.
3. Non-admin caller gets 403.
4. Metrics include all categories from section 2.5.

**Scenario 6: Rate limiter fail-open on store failure**
1. The `InProcessRateLimitStore` raises an exception (simulated).
2. Rate limit middleware logs the error and allows the request.
3. Request proceeds to handler.
4. Metric `ai_rate_limiter_failures` is incremented.
5. Operator alert fires because the fail-open metric exceeds threshold.

### 6.4 Safety Invariant Tests

```python
# Invariant: rate limit block does not reveal internal state
async def test_invariant_rate_limit_error_no_internals(test_client, monkeypatch):
    monkeypatch.setenv("AI_RATE_LIMIT_USER_REQUESTS", "1")
    response = await send_ai_requests(test_client, 2)
    assert response.status_code == 429
    body = response.json()
    assert "details" in body
    assert "internal" not in str(body).lower()

# Invariant: rollout gate block returns 404 not 403
async def test_invariant_rollout_block_is_404(test_client, monkeypatch):
    monkeypatch.setenv("AI_AUTHORING_ENABLED", "false")
    response = test_client.post("/api/v1/ai/chat", json={...})
    assert response.status_code == 404
    assert "FEATURE_NOT_AVAILABLE" in response.text

# Invariant: telemetry write failure does not block the main request
async def test_invariant_telemetry_failure_non_blocking(test_client, monkeypatch, db_session):
    async def failing_persist(*args, **kwargs):
        raise DatabaseError("connection lost")
    monkeypatch.setattr("app.services.ai.telemetry_service.TelemetryService.record_event", failing_persist)
    response = test_client.post("/api/v1/ai/chat", json={...})
    assert response.status_code == 200  # Request succeeds despite telemetry failure

# Invariant: metrics endpoint does not affect application availability
async def test_invariant_metrics_independent(test_client):
    """Even if metrics registration fails, the app continues serving requests."""
    pass
```

### 6.5 Concurrency Tests

```python
async def test_concurrent_rate_limit_counters_accurate(async_client, async_http_client):
    """50 concurrent requests from the same user are accurately counted against the limit."""
    pass

async def test_concurrent_telemetry_writes_do_not_corrupt(async_client, async_http_client):
    """100 concurrent telemetry event writes do not cause integrity errors."""
    pass

async def test_rollout_gate_deterministic_across_requests(async_client, monkeypatch):
    """A user above the rollout percentage is consistently blocked across requests."""
    pass
```

---

## 7. Definition of Done

### 7.1 Code Complete

- [ ] `app/middleware/ai_telemetry.py` — `AITelemetryMiddleware` with trace ID propagation, request timing, structured logging
- [ ] `app/middleware/ai_rate_limiter.py` — `RateLimitMiddleware` with `InProcessRateLimitStore` and sliding-window counters
- [ ] `app/middleware/ai_rollout_gate.py` — `RolloutGateMiddleware` with global kill switch, env/tenant/role gates, percentage rollout
- [ ] `app/models/ai_telemetry.py` — `AITelemetryEventRecord` ORM model
- [ ] `app/services/ai/telemetry_service.py` — `TelemetryService` with `record_event` and `query_events`
- [ ] `app/services/ai/metrics.py` — All Prometheus counters, histograms, gauges as specified in section 2.5
- [ ] `app/routers/ai_observability.py` — Observability, rate-limit, usage, rollout-status, and telemetry query endpoints
- [ ] `app/routers/ai_observability_dtos.py` — All Pydantic request/response models
- [ ] `app/main.py` — Middleware registration, router registration, model import
- [ ] Alembic migration `20260614_0002` — Create `ai_telemetry_events`, add `trace_id` columns
- [ ] `requirements.prod.txt` — uncomment `sentry-sdk[fastapi]`, add `prometheus_client>=0.19.0`
- [ ] `.env.example` — All environment variables documented in section 2.10
- [ ] `docs/AI_Implemenation/01_SystemArchitecture/grafana_ai_dashboard.json` — Dashboard JSON template

### 7.2 Tests Pass

- [ ] All unit tests pass (20+ tests in `test_ai_middleware/` suite)
- [ ] All integration tests pass (12+ tests in `test_ai_observability_api.py`)
- [ ] All safety invariant tests pass (4 tests)
- [ ] All concurrency tests pass (3 tests)
- [ ] Existing health endpoint tests still pass (regression)
- [ ] Existing AI proposal tests still pass with `trace_id` column added (regression)
- [ ] Coverage >= 85% for new middleware and service code

### 7.3 Documentation

- [ ] API contracts documented in OpenAPI spec
- [ ] Environment variables added to `.env.example` with descriptions
- [ ] Grafana dashboard JSON saved to `docs/AI_Implemenation/01_SystemArchitecture/grafana_ai_dashboard.json`
- [ ] Runbook entry: "How to enable AI for a tenant" (env var changes)
- [ ] Runbook entry: "How to interpret AI metrics and dashboards"

### 7.4 Security

- [ ] Metrics endpoint is admin-protected (returns 403 for non-admin)
- [ ] Telemetry query endpoint is admin-protected and tenant-scoped
- [ ] Rollout gate blocked requests return 404, never 403
- [ ] Rate limit error does not reveal internal implementation details
- [ ] Trace ID from untrusted sources is validated and regenerated if invalid

### 7.5 Operational Readiness

- [ ] `AI_AUTHORING_ENABLED` defaults to `false` in production `.env.example`
- [ ] Rate limiter defaults (100 req/min per user) are reasonable for MVP
- [ ] Fail-open behavior for rate-limiter store failures is verified
- [ ] Fail-closed behavior for rollout gate failures is verified
- [ ] Telemetry write failures do not affect request processing
- [ ] Prometheus metrics are scrapable and include all required categories
- [ ] Dashboard panels display meaningful data within 5 minutes of first request

---

## 8. Tasks

### Task 1: Create AI Telemetry ORM Model

**Files to create/modify:**
- `app/models/ai_telemetry.py` (new)
- `app/models/__init__.py` (add import)

**Acceptance:**
- `AITelemetryEventRecord` has all columns as specified in section 2.4.
- `event_id` auto-generated as UUID v4.
- `trace_id`, `event_type`, `payload` are required fields.
- `session_id` has FK to `ai_sessions.session_id` with ON DELETE SET NULL.
- Model is importable and registered with `Base.metadata`.

**Effort:** 1.5 hours
**Dependencies:** US-AI-004 (ai_sessions table)

---

### Task 2: Add trace_id Columns to Existing AI Tables

**Files to modify:**
- `app/models/ai_proposal.py` (add `trace_id` column)
- AI session model (add `trace_id` column)
- AI audit model (add `trace_id` column)
- Outbox event model (add `trace_id` column)

**Acceptance:**
- `ai_sessions`, `ai_proposals`, `ai_audit_logs`, `outbox_events` all have nullable `trace_id` column (String(64)).
- Existing tests pass (null trace_id is acceptable).

**Effort:** 30 minutes
**Dependencies:** Task 1, US-AI-004

---

### Task 3: Implement AITelemetryMiddleware

**File to create:**
- `app/middleware/ai_telemetry.py`

**Acceptance:**
- Extracts or generates UUID v4 trace ID from `X-Trace-ID` header.
- Sets `trace_id_var` context variable for downstream access.
- Response includes `X-Trace-ID` header matching the processed trace ID.
- Records request latency histogram and requests_total counter.
- All `/api/v1/ai/*` paths are instrumented; other paths are skipped.
- Structured log entry at INFO level for each AI request.
- `get_current_trace_id()` function retrieves trace ID from context.

**Effort:** 4 hours
**Dependencies:** None (standalone middleware)

---

### Task 4: Implement InProcessRateLimitStore

**File to create:**
- `app/middleware/ai_rate_limiter.py` (InProcessRateLimitStore class)

**Acceptance:**
- Sliding-window counter with configurable window size and limit.
- `increment_and_check(key, limit, window_seconds)` returns `(is_allowed, remaining)`.
- Expired entries are pruned on each check.
- `current_count(key, window_seconds)` returns the current count.
- Thread-safe for concurrent access within a single process.
- Different keys have independent counters.

**Effort:** 3 hours
**Dependencies:** None

---

### Task 5: Implement RateLimitMiddleware

**File to create/modify:**
- `app/middleware/ai_rate_limiter.py` (RateLimitMiddleware class)

**Acceptance:**
- Checks tenant-level rate limit first (`AI_RATE_LIMIT_TENANT_REQUESTS`).
- Checks user-level rate limit second (`AI_RATE_LIMIT_USER_REQUESTS`).
- Checks endpoint burst limit third (`AI_RATE_LIMIT_ENDPOINT_BURST`).
- 429 response includes `Retry-After` header and structured error body.
- Successful responses include `X-RateLimit-Limit` and `X-RateLimit-Remaining` headers.
- Only `/api/v1/ai/*` paths are rate-limited.
- Fail-open: if the store raises, log warning and allow request.

**Effort:** 5 hours
**Dependencies:** Task 4

---

### Task 6: Implement RolloutGateMiddleware

**File to create:**
- `app/middleware/ai_rollout_gate.py`

**Acceptance:**
- Gate 1 (global kill switch): `AI_AUTHORING_ENABLED` checked first.
- Gate 2 (environment allowlist): `AI_AUTHORING_ENABLED_ENVS` checked second.
- Gate 3 (tenant allowlist): `AI_TENANT_ALLOWLIST` checked third.
- Gate 4 (role allowlist): `AI_ROLE_ALLOWLIST` checked fourth.
- Gate 5 (percentage rollout): `AI_ROLLOUT_PERCENTAGE` with deterministic UUID hashing.
- All blocked requests return `404 FEATURE_NOT_AVAILABLE`.
- Only `/api/v1/ai/*` paths are gated.
- `_reload_config()` allows runtime re-read of env vars.
- Each gate evaluation logs the decision for audit.

**Effort:** 5 hours
**Dependencies:** None

---

### Task 7: Implement TelemetryService

**File to create:**
- `app/services/ai/telemetry_service.py`

**Acceptance:**
- `record_event` persists an `AITelemetryEventRecord` and returns `event_id`.
- `record_event` does not raise exceptions on DB failure (logs and returns None).
- `query_events` supports filters by `trace_id`, `event_type`, `session_id`, `tenant_id`, `time_range`.
- `query_events` returns `(events_list, total_count)` with limit/offset pagination.
- Events are ordered by `occurred_at DESC`.

**Effort:** 3 hours
**Dependencies:** Task 1

---

### Task 8: Implement Prometheus Metrics Definitions

**File to create:**
- `app/services/ai/metrics.py`

**Acceptance:**
- All counters, histograms, and gauges from section 2.5 are defined.
- Metrics use `prometheus_client` library.
- `_safe_register()` handles duplicate registration gracefully.
- Metric names follow Prometheus naming conventions.
- Labels are bounded as specified.

**Effort:** 2 hours
**Dependencies:** None

---

### Task 9: Create Observability Router and Metrics Endpoint

**Files to create/modify:**
- `app/routers/ai_observability.py` (new)
- `app/routers/ai_observability_dtos.py` (new)
- `app/main.py` (register routers and middleware)

**Acceptance:**
- `GET /api/v1/ai/observability/rate-limit-status` returns current limits.
- `GET /api/v1/ai/observability/usage-summary` returns token counts and costs.
- `GET /api/v1/ai/observability/rollout-status` returns gate evaluation.
- `GET /api/v1/ai/observability/telemetry` returns filtered events (admin only).
- `GET /api/v1/metrics` returns Prometheus text format (admin only).
- All three middleware classes are registered in the correct order.
- Router is included in `api_router` under `/api/v1` prefix.
- AI telemetry model is imported during startup.

**Effort:** 5 hours
**Dependencies:** Tasks 3, 5, 6, 7, 8

---

### Task 10: Create Alembic Migration

**File to create:**
- `alembic/versions/20260614_0002_add_ai_telemetry_events.py`

**Acceptance:**
- Creates `ai_telemetry_events` table with all columns and indexes.
- Adds `trace_id` column to `ai_sessions`, `ai_proposals`, `ai_audit_logs`, `outbox_events`.
- Downgrade drops `ai_telemetry_events` and removes `trace_id` columns.
- Migration runs cleanly against both SQLite (dev) and PostgreSQL (prod).

**Effort:** 1.5 hours
**Dependencies:** Tasks 1, 2

---

### Task 11: Update Dependencies and Environment Configuration

**Files to modify:**
- `requirements.prod.txt` (uncomment sentry-sdk, add prometheus_client)
- `.env.example` (add all variables from section 2.10)
- `.env` (add defaults for local development)

**Acceptance:**
- `prometheus_client>=0.19.0` added to `requirements.prod.txt`.
- `sentry-sdk[fastapi]` uncommented in `requirements.prod.txt`.
- All 15+ environment variables from section 2.10 are in `.env.example` with descriptions.
- Local `.env` has safe defaults for development.

**Effort:** 30 minutes
**Dependencies:** None

---

### Task 12: Write Unit Tests for Middleware

**Files to create:**
- `tests/test_ai_middleware/test_ai_telemetry.py`
- `tests/test_ai_middleware/test_ai_rate_limiter.py`
- `tests/test_ai_middleware/test_ai_rollout_gate.py`
- `tests/test_ai_telemetry_service.py`

**Acceptance:**
- All test scenarios from section 6.1 are covered.
- Safety invariant tests from section 6.4 pass.
- Concurrency tests from section 6.5 pass.
- Tests mock the store or use in-memory implementations.
- Coverage >= 85% for middleware and telemetry service.

**Effort:** 8 hours
**Dependencies:** Tasks 3, 4, 5, 6, 7

---

### Task 13: Write Integration Tests for API Layer

**File to create:**
- `tests/test_ai_observability_api.py`

**Acceptance:**
- All test scenarios from section 6.2 are covered.
- Tests use `TestClient` with mocked auth.
- Existing AI route tests still pass (regression).
- Tests cover success, error, admin-auth, and non-admin paths.

**Effort:** 4 hours
**Dependencies:** Task 9

---

### Task 14: Create Grafana Dashboard Template

**File to create:**
- `docs/AI_Implemenation/01_SystemArchitecture/grafana_ai_dashboard.json`

**Acceptance:**
- Dashboard JSON includes all 12 panels from section 2.13.
- Panels reference correct Prometheus metric names.
- Dashboard variables (tenant, environment) are configurable.
- Importable into Grafana without modification.

**Effort:** 2 hours
**Dependencies:** Task 8 (metric names must be finalized)

---

### Task 15: Documentation and Code Review

**Files to modify:**
- `docs/AI_Implemenation/00_User_StoriesUseCases/USER_STORIES.md` (update status)
- `docs/API.md` or OpenAPI spec (add new endpoints)
- Runbook entries

**Acceptance:**
- All new endpoints are documented in OpenAPI spec.
- Environment variables are documented in `.env.example`.
- Grafana dashboard JSON is committed.
- Story is marked complete in the canonical user stories list.
- PR has two approvals.

**Effort:** 3 hours
**Dependencies:** Tasks 9, 12, 13, 14

---

### Task 16: Code Review and Merge

**Acceptance:**
- All CI checks pass.
- Two approvals on the PR.
- No regression in existing tests.
- `AI_AUTHORING_ENABLED` defaults to `false` in production.
- Rate limits default to reasonable values (100 req/min per user).

**Effort:** 2 hours
**Dependencies:** All prior tasks

---

## Summary

| Metric | Value |
|---|---|
| New files | 9 |
| Modified files | 8 |
| New tables | 1 (ai_telemetry_events) |
| Modified tables | 4 (add trace_id columns) |
| New API endpoints | 6 |
| New middleware components | 3 (telemetry, rate limiter, rollout gate) |
| New services | 1 (TelemetryService) |
| Prometheus metrics | 12 counters, 5 histograms, 3 gauges |
| Total estimated effort | ~50 hours |
| Key safety invariant | Telemetry write failures never block user requests |
| Key risk | InProcessRateLimitStore does not scale across processes; Redis upgrade required for multi-worker production |
