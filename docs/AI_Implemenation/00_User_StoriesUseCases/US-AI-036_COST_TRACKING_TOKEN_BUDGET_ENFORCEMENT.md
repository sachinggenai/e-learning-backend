# US-AI-036: Cost Tracking and Token Budget Enforcement

**Status:** Draft
**Priority:** SHOULD for MVP, MUST for production
**Depends on:** US-AI-002 (Feature Flags and Model Config), US-AI-026 (Multi-Provider Model Routing and Fallback)
**Source flow:** 24. Cost Tracking and Token Budget Enforcement
**Epic Owner:** Technical Product Owner

---

## 1. Functional Specification

### 1.1 User Story

As a **Platform Operator**, I want per-tenant and per-user token budget enforcement with cost tracking across all AI model interactions, so that AI usage stays within allocated financial limits and cost overruns are prevented proactively.

As a **Finance Admin**, I want to query historical AI cost data grouped by tenant, user, model, and date range, so that I can reconcile invoices, chargeback costs to business units, and forecast future AI spend.

As an **Author**, I want to receive clear warnings when I am approaching my daily token limit and a clear error when the limit is reached, so that I am not surprised by silent request failures and know when I can resume usage.

### 1.2 Overview

The AI authoring subsystem calls external LLM providers (Anthropic, OpenAI, etc.) on every chat turn, tool call, and generation request. Without metering and enforcement, a single user or a runaway agent loop could exhaust the monthly budget in minutes. This epic delivers the metering, budgeting, and enforcement layer that makes AI spend observable and controllable.

Three capabilities are delivered together because they share the `ai_usage_records` table and the `CostTracker` service:

1. **Request-Level Metering** — Every AI request (chat turn, tool call, generation) records input tokens, output tokens, cached input tokens, the model used, provider latency, and computed cost. This data flows from the LLM provider's API response metadata into a persistent `ai_usage_records` table.

2. **Budget Enforcement** — Per-tenant monthly cost caps and per-user daily token limits are evaluated before every request. Approaching thresholds trigger warning headers; exceeded limits return HTTP 429 with structured error bodies and `Retry-After` headers.

3. **Usage Reporting** — A usage API exposes current-period consumption, remaining budget, historical trends, and per-model breakdowns for dashboards, alerting, and chargeback.

**Key design decisions:**

- **Post-billing, not pre-billing**: Usage is recorded after the provider responds (post-billing), not estimated before the request. Budget checks use the sum of *already-recorded* usage plus the *current request's* provider-reported usage. This avoids any estimation error that could arise from pre-request token counting.
- **Cost is computed, not stored directly**: Raw token counts are stored. Cost is computed from a pricing table that maps `(model_id, provider)` to per-token rates. This allows retroactive cost corrections when providers change pricing.
- **Budget checks are best-effort with eventual consistency**: A small overshoot (up to `AI_BUDGET_OVERAGE_TOLERANCE_USD`, default $5.00) is tolerated to avoid rejecting requests due to clock skew or concurrent-writer races. The periodic budget sync job reconciles the exact running total.
- **Warning headers, not errors**: At or above 80% of a budget, every response includes `X-AI-Budget-Warning` and `X-AI-Budget-Remaining` headers. The frontend can display a persistent banner. Only hard-exceeded budgets return 429.
- **Separate from rate limiting**: Rate limits (US-AI-021) protect API capacity. Token budgets protect financial cost. A user can be within rate limits but over budget, or within budget but rate-limited.
- **Feature-flagged**: The entire cost-tracking subsystem is gated behind the `FEATURE_AI_COST_TRACKING` feature flag so it can be toggled independently of AI authoring itself.

### 1.3 Actors

| Actor | Role |
|---|---|
| Platform Operator (Admin) | Configures budget limits per tenant and per user; monitors dashboards; receives threshold alerts |
| Finance Admin | Queries historical cost data for invoicing and chargeback; adjusts pricing tables when provider costs change |
| Author (User) | Receives budget warning headers and over-budget 429 errors with clear reset-time messaging |
| AI Orchestrator | Calls `CostTracker.record()` after every LLM response; calls `CostTracker.check_budget()` before every LLM request |
| CostTracker (Service) | Core service that records usage, checks budgets against configurable limits, computes cost from token counts and pricing table |
| ModelRouter (US-AI-026) | Passes per-request provider metadata (`model_id`, `provider`) into the response for CostTracker to consume |
| BudgetSyncJob (Background) | Periodic job that reconciles running totals from `ai_usage_records` into denormalized `ai_usage_aggregates` for fast budget checks |
| Prometheus Exporter | Exposes cost and token metrics (`ai_tokens_total`, `ai_cost_total`, `ai_budget_remaining`) for dashboarding |

### 1.4 Flows

#### Flow 1: Request-Level Metering (Post-Provider)

**Precondition:** A user's chat turn or tool-call round trips through the AI Orchestrator (US-AI-023) and ModelRouter (US-AI-026). The provider has returned a response with usage metadata.

1. The `ModelRouter` receives the provider's raw response, which includes usage blocks:
   ```json
   {
     "usage": {
       "input_tokens": 452,
       "output_tokens": 188,
       "cache_creation_input_tokens": 0,
       "cache_read_input_tokens": 120
     }
   }
   ```
2. The `ModelRouter` resolves the `model_id` and `provider` from the routing decision (e.g., `claude-sonnet-4-20250514`, `anthropic`).
3. The router calls `CostTracker.record(session_id, user_id, tenant_id, model_id, provider, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, latency_ms)`.
4. `CostTracker.record()` performs the following steps within a synchronous DB transaction:
   a. Inserts a row into `ai_usage_records`.
   b. Calls `_compute_cost(model_id, provider, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens)` using the in-memory pricing table.
   c. Updates the denormalized `running_balance` on the `ai_usage_aggregates` row for `(tenant_id, user_id, date)`:
      ```sql
      UPDATE ai_usage_aggregates
      SET total_input_tokens = total_input_tokens + :input_tokens,
          total_output_tokens = total_output_tokens + :output_tokens,
          total_cost = total_cost + :computed_cost,
          request_count = request_count + 1
      WHERE tenant_id = :t AND user_id = :u AND usage_date = :d;
      ```
   d. If no aggregate row exists, upserts one.
5. The record insertion is non-blocking to the request — failure to write usage records MUST NOT fail the user-facing request. A background retry queue handles write failures.
6. The computed cost is NOT returned to the caller. Only tracking succeeds/fails.
7. If pricing table lookup fails for the model, the record is still inserted with `cost=0` and a `pricing_unknown` flag is set to `true` for offline reconciliation.

#### Flow 2: Budget Check (Pre-Provider)

**Precondition:** A user's request enters the AI Orchestrator. The orchestrator has resolved `user_id`, `tenant_id` from the JWT.

1. The orchestrator calls `CostTracker.check_budget(user_id, tenant_id)` before building the LLM request.
2. `CostTracker.check_budget()` evaluates:
   a. **Global kill switch**: If `AI_COST_TRACKING_ENABLED` is `false`, return `{allowed: true}` immediately (no metering or enforcement).
   b. **Tenant monthly cap**: Fetch the running cost for the current month from `ai_usage_aggregates` (or sum `ai_usage_records` as fallback). Compare against `AI_TENANT_MONTHLY_COST_CAP_USD` (default: unset = unlimited).
      - If `(aggregated_cost + AI_BUDGET_OVERAGE_TOLERANCE_USD) >= cap`, return `{allowed: false, reason: "TENANT_MONTHLY_COST_EXCEEDED", reset_at: <start_of_next_month>}`.
      - If `(aggregated_cost / cap) >= 0.80`, set `warning = true`.
   c. **User daily token limit**: Fetch the running token total for today from `ai_usage_aggregates`. Compare against `AI_USER_DAILY_TOKEN_LIMIT` (default: unset = unlimited).
      - If `(aggregated_tokens + AI_TOKEN_OVERAGE_TOLERANCE) >= limit`, return `{allowed: false, reason: "USER_DAILY_TOKEN_LIMIT_EXCEEDED", reset_at: <start_of_next_day>}`.
      - If `(aggregated_tokens / limit) >= 0.80`, set `warning = true`.
   d. **User monthly cost cap** (optional): Same logic as tenant monthly cap but scoped to the user. Configured via `AI_USER_MONTHLY_COST_CAP_USD`.
3. If `allowed == false`, the orchestrator skips the LLM call entirely and returns HTTP 429 with structured error body (see Section 2.3).
4. If `warning == true`, the orchestrator includes `X-AI-Budget-Warning: true` and `X-AI-Budget-Remaining: <remaining_percentage>%` in the response headers.
5. Budget check result is logged as a telemetry event (US-AI-021) with `{user_id, tenant_id, allowed, warning, reason, remaining_budget, remaining_tokens}`.

#### Flow 3: Usage Reporting API

1. Frontend admin panel calls `GET /api/v1/ai/usage/summary?tenant_id=tenant-1&period=monthly&from=2026-06-01&to=2026-06-30`.
2. Backend queries `ai_usage_aggregates` or `ai_usage_records` for the period, grouped by the requested dimension.
3. Response includes:
   ```json
   {
     "period": {"from": "2026-06-01T00:00:00Z", "to": "2026-06-30T23:59:59Z"},
     "tenantId": "tenant-1",
     "summary": {
       "totalCost": 142.53,
       "totalInputTokens": 1420000,
       "totalOutputTokens": 380000,
       "totalCacheCreationTokens": 50000,
       "totalCacheReadTokens": 120000,
       "totalRequests": 3400,
       "budgetCap": 500.00,
       "budgetRemaining": 357.47,
       "budgetUsagePercent": 28.5
     },
     "byModel": [
       {"model": "claude-sonnet-4-20250514", "cost": 98.20, "requests": 1800, "avgTokensPerRequest": 620},
       {"model": "claude-haiku-3-5-20241022", "cost": 44.33, "requests": 1600, "avgTokensPerRequest": 310}
     ],
     "byUser": [
       {"userId": "user-1", "cost": 82.10, "requests": 1200, "dailyTokenLimit": 100000, "todayTokens": 42000},
       {"userId": "user-2", "cost": 60.43, "requests": 2200, "dailyTokenLimit": 50000, "todayTokens": 18000}
     ],
     "generatedAt": "2026-06-14T12:00:00Z"
   }
   ```
4. Additional endpoints support drill-down to individual usage records for audit reconciliation.

#### Flow 4: Budget Sync Background Job (Reconciliation)

1. Every `AI_BUDGET_SYNC_INTERVAL_SECONDS` (default 300), a background job runs:
   ```
   SELECT tenant_id, user_id, DATE(created_at) as usage_date,
          SUM(input_tokens) as total_input,
          SUM(output_tokens) as total_output,
          SUM(cost) as total_cost,
          COUNT(*) as request_count
   FROM ai_usage_records
   WHERE created_at >= NOW() - INTERVAL '2 days'
   GROUP BY tenant_id, user_id, DATE(created_at);
   ```
2. For each group, the job upserts `ai_usage_aggregates` — this catches any rows that missed the inline update in Flow 1 due to contention or failure.
3. If any tenant's aggregated cost exceeds 80% of their cap, the job emits an alert-level log entry and increments the `ai_budget_warnings_total` Prometheus counter.
4. If any tenant's aggregated cost exceeds 100% of their cap with overage tolerance, the job logs a critical alert and increments `ai_budget_exceeded_total`.

---

## 2. Technical Design

### 2.1 Data Model (PostgreSQL DDL)

#### 2.1.1 `ai_usage_records` — Raw per-request usage

```sql
CREATE TABLE ai_usage_records (
    id              BIGSERIAL PRIMARY KEY,
    record_id       VARCHAR(64) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    session_id      VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    turn_id         VARCHAR(64),                          -- nullable for non-chat operations
    user_id         VARCHAR(128) NOT NULL,
    tenant_id       VARCHAR(64) NOT NULL,
    
    -- Provider metadata
    provider        VARCHAR(32) NOT NULL,                  -- 'anthropic', 'openai', 'google', etc.
    model_id        VARCHAR(128) NOT NULL,                 -- e.g., 'claude-sonnet-4-20250514'
    request_type    VARCHAR(32) NOT NULL DEFAULT 'chat',   -- 'chat', 'tool_call', 'generation', 'repair'
    
    -- Token counts (as reported by provider)
    input_tokens            INTEGER NOT NULL DEFAULT 0,
    output_tokens           INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens   INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens       INTEGER NOT NULL DEFAULT 0,
    
    -- Cost (computed from pricing table at write time)
    cost            NUMERIC(12,6) NOT NULL DEFAULT 0,
    cost_currency   VARCHAR(3) NOT NULL DEFAULT 'USD',
    
    -- Performance
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    
    -- Status
    pricing_unknown BOOLEAN NOT NULL DEFAULT FALSE,       -- TRUE if model not found in pricing table
    
    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Indexes
    CONSTRAINT fk_usage_session
        FOREIGN KEY (session_id) REFERENCES ai_sessions(session_id)
        ON DELETE CASCADE
);

-- Query patterns:
-- 1. Monthly cost by tenant:    WHERE tenant_id = ? AND created_at >= date_trunc('month', NOW())
-- 2. Daily tokens by user:       WHERE user_id = ? AND created_at >= CURRENT_DATE
-- 3. Cost by model (rollup):     WHERE tenant_id = ? AND created_at BETWEEN ? AND ?
-- 4. Budget sync (recent rows):  WHERE created_at >= NOW() - INTERVAL '2 days'

CREATE INDEX idx_usage_tenant_date     ON ai_usage_records(tenant_id, created_at);
CREATE INDEX idx_usage_user_date       ON ai_usage_records(user_id, created_at);
CREATE INDEX idx_usage_session         ON ai_usage_records(session_id);
CREATE INDEX idx_usage_model_date      ON ai_usage_records(model_id, created_at);
CREATE INDEX idx_usage_pricing_unknown ON ai_usage_records(pricing_unknown) WHERE pricing_unknown = TRUE;
```

#### 2.1.2 `ai_usage_aggregates` — Denormalized daily rollups

```sql
CREATE TABLE ai_usage_aggregates (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           VARCHAR(64) NOT NULL,
    user_id             VARCHAR(128) NOT NULL,
    usage_date          DATE NOT NULL,
    
    -- Token totals
    total_input_tokens          BIGINT NOT NULL DEFAULT 0,
    total_output_tokens         BIGINT NOT NULL DEFAULT 0,
    total_cache_creation_tokens BIGINT NOT NULL DEFAULT 0,
    total_cache_read_tokens     BIGINT NOT NULL DEFAULT 0,
    
    -- Cost
    total_cost          NUMERIC(14,2) NOT NULL DEFAULT 0,
    
    -- Request count
    request_count       INTEGER NOT NULL DEFAULT 0,
    
    -- Last update
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- One row per tenant+user+day
    UNIQUE (tenant_id, user_id, usage_date)
);

CREATE INDEX idx_aggregates_tenant_date ON ai_usage_aggregates(tenant_id, usage_date);
CREATE INDEX idx_aggregates_user_date   ON ai_usage_aggregates(user_id, usage_date);
```

#### 2.1.3 `ai_pricing_table` — Model cost rates

```sql
CREATE TABLE ai_pricing_table (
    id                  SERIAL PRIMARY KEY,
    provider            VARCHAR(32) NOT NULL,
    model_id            VARCHAR(128) NOT NULL,
    model_display_name  VARCHAR(200),
    
    -- Per-token rates in USD
    input_token_rate            NUMERIC(10,8) NOT NULL,    -- e.g., 0.00000300 for $3/M tokens
    output_token_rate           NUMERIC(10,8) NOT NULL,
    cache_creation_token_rate   NUMERIC(10,8) NOT NULL DEFAULT 0,
    cache_read_token_rate       NUMERIC(10,8) NOT NULL DEFAULT 0,
    
    -- Model context window
    max_input_tokens     INTEGER NOT NULL DEFAULT 200000,
    
    -- Metadata
    effective_from      DATE NOT NULL,
    effective_until     DATE DEFAULT NULL,                 -- NULL = currently active
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE (provider, model_id, effective_from)
);

-- Seed data for Anthropic models (production pricing as of June 2026)
INSERT INTO ai_pricing_table (provider, model_id, model_display_name,
    input_token_rate, output_token_rate, cache_creation_token_rate, cache_read_token_rate,
    max_input_tokens, effective_from) VALUES
('anthropic', 'claude-sonnet-4-20250514',  'Claude Sonnet 4',
     0.00000300, 0.00001500, 0.00000375, 0.00000030, 200000, '2026-06-01'),
('anthropic', 'claude-haiku-3-5-20241022', 'Claude Haiku 3.5',
     0.00000080, 0.00000400, 0.00000100, 0.00000008, 200000, '2026-06-01'),
('anthropic', 'claude-opus-4-20250514',    'Claude Opus 4',
     0.00001500, 0.00007500, 0.00001875, 0.00000150, 200000, '2026-06-01'),
('openai',    'gpt-4o-2025-05-13',         'GPT-4o',
     0.00000250, 0.00001000, 0.00000125, 0.00000025, 128000, '2026-06-01'),
('openai',    'gpt-4o-mini-2025-07-18',    'GPT-4o Mini',
     0.00000015, 0.00000060, 0.00000008, 0.00000002, 128000, '2026-06-01');
```

#### 2.1.4 `ai_budget_config` — Per-tenant and per-user budget limits

```sql
CREATE TABLE ai_budget_config (
    id                  SERIAL PRIMARY KEY,
    
    -- Scope: tenant-wide or user-specific
    scope               VARCHAR(8) NOT NULL CHECK (scope IN ('tenant', 'user')),
    tenant_id           VARCHAR(64) NOT NULL,
    user_id             VARCHAR(128),                   -- NULL for tenant-scoped rows
    
    -- Budget limits
    monthly_cost_cap_usd    NUMERIC(12,2),              -- NULL = unlimited
    daily_token_limit       INTEGER,                     -- NULL = unlimited
    
    -- Notify at
    warning_threshold_pct   INTEGER NOT NULL DEFAULT 80, -- 0-100, default 80%
    
    -- Audit
    created_by          VARCHAR(128) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE (scope, tenant_id, COALESCE(user_id, ''))
);

CREATE INDEX idx_budget_config_tenant ON ai_budget_config(tenant_id);
```

### 2.2 Service Signatures

#### 2.2.1 `CostTracker` (`app/services/ai/cost_tracker.py`)

```python
"""Cost tracking and token budget enforcement service.

Records per-request token usage, computes cost from pricing table,
and enforces per-tenant / per-user budget limits before LLM requests.

Dependencies:
    - AsyncSession (database)
    - FeatureFlagService (for FEATURE_AI_COST_TRACKING gate)
    - ModelRouter (for provider metadata enrichment)

Environment variables:
    AI_COST_TRACKING_ENABLED     (bool, default: true)
    AI_BUDGET_OVERAGE_TOLERANCE_USD  (float, default: 5.00)
    AI_TOKEN_OVERAGE_TOLERANCE       (int, default: 1000)
    AI_BUDGET_SYNC_INTERVAL_SECONDS  (int, default: 300)
"""

from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from datetime import datetime, date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class UsageRecord:
    """Input to CostTracker.record()."""
    session_id: str
    turn_id: Optional[str]
    user_id: str
    tenant_id: str
    provider: str
    model_id: str
    request_type: str           # 'chat' | 'tool_call' | 'generation' | 'repair'
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    latency_ms: int


@dataclass
class BudgetCheckResult:
    """Output of CostTracker.check_budget()."""
    allowed: bool
    warning: bool = False
    reason: Optional[str] = None       # e.g., 'TENANT_MONTHLY_COST_EXCEEDED'
    reset_at: Optional[str] = None     # ISO datetime when budget resets
    remaining_budget_pct: Optional[float] = None
    remaining_tokens: Optional[int] = None


class CostTracker:
    """Core service for usage metering and budget enforcement."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def record(self, usage: UsageRecord) -> str:
        """Persist a usage record and update running aggregates.

        Returns the record_id. Raises RuntimeError on DB failure (caller
        should catch and log, never fail the user request).

        Steps:
        1. Look up pricing from ai_pricing_table for (provider, model_id)
           where effective_from <= today AND (effective_until IS NULL OR effective_until >= today).
        2. Compute cost:
           cost = (input_tokens * input_rate)
                + (output_tokens * output_rate)
                + (cache_creation_tokens * cache_creation_rate)
                + (cache_read_tokens * cache_read_rate)
        3. INSERT into ai_usage_records.
        4. UPSERT ai_usage_aggregates: increment totals.
        5. Return record_id.
        """
        ...

    async def check_budget(
        self,
        user_id: str,
        tenant_id: str,
    ) -> BudgetCheckResult:
        """Check whether a new request is within budget limits.

        Evaluates in order:
        1. Global enabled flag.
        2. Tenant monthly cost cap.
        3. User daily token limit.
        4. User monthly cost cap (optional).

        Returns BudgetCheckResult with allowed, warning, and metadata.
        """
        ...

    async def get_usage_summary(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        group_by: str = "model",     # 'model' | 'user' | 'day'
    ) -> dict:
        """Return aggregated usage summary for reporting.

        Queries ai_usage_aggregates for the given period and dimensions.
        Supports drill-down to individual records via get_usage_details().
        """
        ...

    async def get_usage_details(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        model_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Return paginated individual usage records for audit."""
        ...

    async def get_budget_config(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
    ) -> dict:
        """Return the effective budget configuration for a tenant/user.

        Merges:
        - Tenant-level config from ai_budget_config WHERE scope='tenant'
        - User-level overrides from ai_budget_config WHERE scope='user'
        """
        ...

    async def update_budget_config(
        self,
        tenant_id: str,
        monthly_cost_cap_usd: Optional[Decimal] = None,
        user_id: Optional[str] = None,
        daily_token_limit: Optional[int] = None,
        warning_threshold_pct: Optional[int] = None,
        created_by: str = "system",
    ) -> dict:
        """Create or update budget configuration.

        If user_id is provided, creates/updates a user-scoped config.
        If user_id is None, creates/updates a tenant-scoped config.
        """
        ...

    async def get_pricing(self, model_id: str, provider: str) -> Optional[dict]:
        """Look up pricing for a model+provider combination.

        Returns dict with rates or None if unknown.
        Result is cached in-memory for 5 minutes to reduce DB load.
        """
        ...

    # ── Internal helpers ────────────────────────────────────────────

    @staticmethod
    def _compute_cost(
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int,
        cache_read_tokens: int,
        pricing: dict,
    ) -> Decimal:
        """Compute cost from token counts and pricing rates."""
        ...

    async def _get_tenant_monthly_cost(self, tenant_id: str) -> Decimal:
        """Sum aggregated cost for current month for a tenant."""
        ...

    async def _get_user_daily_tokens(self, user_id: str) -> int:
        """Sum aggregated input+output tokens for today for a user."""
        ...

    async def _upsert_aggregate(
        self,
        tenant_id: str,
        user_id: str,
        usage_date: date,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int,
        cache_read_tokens: int,
        cost: Decimal,
    ) -> None:
        """Increment the aggregate row for the given tenant+user+date."""
        ...
```

#### 2.2.2 `BudgetSyncJob` (`app/services/ai/budget_sync_job.py`)

```python
"""Background job that reconciles ai_usage_aggregates from ai_usage_records.

Runs on a configurable interval (AI_BUDGET_SYNC_INTERVAL_SECONDS, default 300s).
Catches any records that missed inline aggregate updates due to contention or
transient failures.

Uses the existing lifespan pattern in app/main.py to start the background task
via asyncio.create_task. The task checks an Event flag at each iteration:
setting the flag triggers a clean shutdown within the current iteration.
"""

from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class BudgetSyncJob:
    """Periodic reconciliation of usage aggregates."""

    def __init__(self, interval_seconds: int = 300):
        self.interval = interval_seconds
        self._stop_event = asyncio.Event()

    async def run(self) -> None:
        """Main loop — runs until stop() is called."""
        while not self._stop_event.is_set():
            try:
                await self._sync_cycle()
            except Exception:
                logger.exception("Budget sync cycle failed")
            await asyncio.sleep(self.interval)

    async def stop(self) -> None:
        """Signal the job to stop at the next cycle boundary."""
        self._stop_event.set()

    async def _sync_cycle(self) -> None:
        """One reconciliation cycle.

        SQL:
            SELECT tenant_id, user_id, DATE(created_at) as usage_date,
                   SUM(input_tokens), SUM(output_tokens),
                   SUM(cache_creation_tokens), SUM(cache_read_tokens),
                   SUM(cost), COUNT(*)
            FROM ai_usage_records
            WHERE created_at >= NOW() - INTERVAL '2 days'
            GROUP BY tenant_id, user_id, DATE(created_at);

        For each group, UPSERT into ai_usage_aggregates.
        Then check thresholds and emit alerts/metrics.
        """
        ...
```

#### 2.2.3 Dependency Injection in FastAPI Router

```python
"""CostTracker dependency factory — used in ai_usage router."""
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.config import get_session
from app.services.ai.cost_tracker import CostTracker


async def get_cost_tracker(
    session: AsyncSession = Depends(get_session),
) -> CostTracker:
    """FastAPI dependency that yields a CostTracker with DB session."""
    return CostTracker(session)
```

### 2.3 API Contracts

#### `POST /api/v1/ai/chat` (modified — adds budget check before LLM call)

The existing AI Chat Endpoint (US-AI-023) is modified to call `CostTracker.check_budget()` before the LLM interaction loop begins, and `CostTracker.record()` after each provider response within the loop.

**New request behavior (budget enforcement):**

```json
// HTTP 429 Response when budget exceeded
{
    "code": "BUDGET_EXCEEDED",
    "field": "request",
    "message": "Your organization's monthly AI budget has been reached. Usage will resume on July 1, 2026.",
    "details": {
        "reason": "TENANT_MONTHLY_COST_EXCEEDED",
        "resetAt": "2026-07-01T00:00:00Z",
        "budgetCap": 500.00,
        "budgetSpent": 502.30,
        "limitType": "monthly_cost"
    }
}
```

**New response headers (warning):**

```
X-AI-Budget-Warning: true
X-AI-Budget-Remaining: 15%
X-AI-Budget-ResetAt: 2026-07-01T00:00:00Z
```

#### `GET /api/v1/ai/usage/summary`

```http
GET /api/v1/ai/usage/summary?tenant_id=tenant-1&period=monthly&from=2026-06-01&to=2026-06-30&group_by=model
Authorization: Bearer <admin-jwt>
```

**Response 200:**
```json
{
    "period": {"from": "2026-06-01T00:00:00Z", "to": "2026-06-30T23:59:59Z"},
    "tenantId": "tenant-1",
    "summary": {
        "totalCost": 142.53,
        "totalInputTokens": 1420000,
        "totalOutputTokens": 380000,
        "totalCacheCreationTokens": 50000,
        "totalCacheReadTokens": 120000,
        "totalRequests": 3400,
        "budgetCap": 500.00,
        "budgetRemaining": 357.47,
        "budgetUsagePercent": 28.5
    },
    "byModel": [
        {
            "model": "claude-sonnet-4-20250514",
            "cost": 98.20,
            "requests": 1800,
            "avgTokensPerRequest": 620,
            "avgLatencyMs": 2850
        }
    ],
    "byUser": [
        {
            "userId": "user-1",
            "cost": 82.10,
            "requests": 1200,
            "dailyTokenLimit": 100000,
            "todayTokens": 42000,
            "todayTokensPercent": 42.0
        }
    ],
    "generatedAt": "2026-06-14T12:00:00Z"
}
```

**Errors:**
- `403 FORBIDDEN` — caller lacks admin/operator role for this tenant
- `422 VALIDATION_ERROR` — invalid date range or group_by value

#### `GET /api/v1/ai/usage/records`

```http
GET /api/v1/ai/usage/records?tenant_id=tenant-1&user_id=user-1&from=2026-06-10&to=2026-06-14&model_id=claude-sonnet-4-20250514&limit=50&offset=0
Authorization: Bearer <admin-jwt>
```

**Response 200:**
```json
{
    "records": [
        {
            "recordId": "abc-123",
            "sessionId": "sess-456",
            "turnId": "turn-789",
            "userId": "user-1",
            "tenantId": "tenant-1",
            "provider": "anthropic",
            "modelId": "claude-sonnet-4-20250514",
            "requestType": "chat",
            "tokens": {
                "input": 452,
                "output": 188,
                "cacheCreation": 0,
                "cacheRead": 120
            },
            "cost": 0.00416,
            "costCurrency": "USD",
            "latencyMs": 3200,
            "createdAt": "2026-06-14T11:45:00Z"
        }
    ],
    "total": 1200,
    "limit": 50,
    "offset": 0
}
```

#### `GET /api/v1/ai/usage/budget`

```http
GET /api/v1/ai/usage/budget?tenant_id=tenant-1
Authorization: Bearer <admin-jwt>
```

**Response 200:**
```json
{
    "tenantId": "tenant-1",
    "tenantConfig": {
        "monthlyCostCapUsd": 500.00,
        "warningThresholdPct": 80,
        "currentMonthCost": 142.53,
        "budgetRemaining": 357.47,
        "budgetUsagePercent": 28.5
    },
    "userOverrides": [
        {
            "userId": "user-2",
            "dailyTokenLimit": 50000,
            "todayTokens": 18000,
            "dailyTokenPercent": 36.0
        }
    ]
}
```

#### `PUT /api/v1/ai/usage/budget`

```http
PUT /api/v1/ai/usage/budget
Authorization: Bearer <admin-jwt>
Content-Type: application/json

{
    "tenantId": "tenant-1",
    "monthlyCostCapUsd": 1000.00,
    "userOverrides": [
        {
            "userId": "user-2",
            "dailyTokenLimit": 100000
        }
    ]
}
```

**Response 200:**
```json
{
    "tenantId": "tenant-1",
    "monthlyCostCapUsd": 1000.00,
    "updatedAt": "2026-06-14T12:00:00Z"
}
```

### 2.4 Environment Variables / Configuration

```ini
# ============================================
# AI Cost Tracking and Budget Enforcement
# ============================================

# Master switch — set to false to disable all cost tracking and budget
# enforcement without affecting AI authoring functionality.
AI_COST_TRACKING_ENABLED=true

# Default budget limits (used when no ai_budget_config row exists)
# Set to empty to disable.
AI_TENANT_MONTHLY_COST_CAP_USD=500.00
AI_USER_DAILY_TOKEN_LIMIT=100000
AI_USER_MONTHLY_COST_CAP_USD=

# Overage tolerance — small overshoot is tolerated to prevent hard failures
# from clock skew or concurrent writes.
AI_BUDGET_OVERAGE_TOLERANCE_USD=5.00
AI_TOKEN_OVERAGE_TOLERANCE=1000

# Background sync job interval in seconds
AI_BUDGET_SYNC_INTERVAL_SECONDS=300

# Pricing table refresh interval in seconds (how often to reload from DB)
AI_PRICING_CACHE_TTL_SECONDS=300
```

### 2.5 Feature Flag

Add to the existing `app/utils/feature_flags.py`:

```python
'cost_tracking': FeatureFlag(
    name='cost_tracking',
    enabled=False,
    description='Enable AI cost tracking and token budget enforcement',
    environments=[Environment.STAGING, Environment.PRODUCTION]
),
```

Override via env var: `FEATURE_COST_TRACKING=true`

The `require_feature_async("cost_tracking")` dependency is applied to all `/api/v1/ai/usage/*` routes.

### 2.6 Error Codes

| HTTP Status | Code | Condition |
|---|---|---|
| 429 | `BUDGET_EXCEEDED` | Tenant monthly cost cap exceeded |
| 429 | `BUDGET_EXCEEDED` | User daily token limit exceeded |
| 429 | `BUDGET_EXCEEDED` | User monthly cost cap exceeded |
| 422 | `VALIDATION_ERROR` | Invalid date range or group_by in usage query |
| 403 | `FORBIDDEN` | Caller lacks admin/operator role for the tenant |
| 404 | `FEATURE_NOT_AVAILABLE` | `cost_tracking` feature flag disabled |

All error bodies follow the `app/utils/error_envelope.py` pattern:

```json
{
    "code": "BUDGET_EXCEEDED",
    "field": "request",
    "message": "Your organization's monthly AI budget has been reached.",
    "details": {
        "reason": "TENANT_MONTHLY_COST_EXCEEDED",
        "resetAt": "2026-07-01T00:00:00Z",
        "budgetCap": 500.00,
        "budgetSpent": 502.30
    }
}
```

---

## 3. Router Implementation

### 3.1 New Router: `app/routers/ai_usage.py`

```python
"""AI Usage Reporting and Budget API.

Provides admin-facing endpoints for querying usage data and managing
budget configurations. All routes are gated behind the `cost_tracking`
feature flag and require admin/operator role authorization.

Endpoints:
    GET    /api/v1/ai/usage/summary     — Aggregated usage summary
    GET    /api/v1/ai/usage/records     — Paginated individual records
    GET    /api/v1/ai/usage/budget      — Current budget configuration
    PUT    /api/v1/ai/usage/budget      — Update budget configuration
    GET    /api/v1/ai/usage/pricing     — Pricing table listing
"""
from __future__ import annotations
from typing import Optional
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.utils.feature_flags import require_feature_async
from app.utils.error_envelope import api_http_exception
from app.services.ai.cost_tracker import CostTracker, get_cost_tracker

router = APIRouter(
    prefix="/ai/usage",
    tags=["AI Usage"],
    dependencies=[Depends(lambda: require_feature_async("cost_tracking"))],
)


async def _require_admin_role(
    authorization: Optional[str] = Header(None),
    x_tenant_id: Optional[str] = Header(None),
):
    """Dependency that verifies admin/operator role.

    For MVP: checks for a specific admin role or operator scope in the
    JWT token. Returns 403 if unauthorized.
    """
    # TODO: integrate with real auth middleware — see US-AI-003
    if not authorization:
        raise api_http_exception(403, "FORBIDDEN", "Admin role required")
    return {"tenant_id": x_tenant_id or "default"}


@router.get("/summary")
async def get_usage_summary(
    tenant_id: str = Query(..., description="Tenant ID"),
    from_date: Optional[date] = Query(None, alias="from"),
    to_date: Optional[date] = Query(None, alias="to"),
    group_by: str = Query("model", regex="^(model|user|day)$"),
    cost_tracker: CostTracker = Depends(get_cost_tracker),
    auth: dict = Depends(_require_admin_role),
):
    """Return aggregated usage summary for the period."""
    return await cost_tracker.get_usage_summary(
        tenant_id=tenant_id,
        from_date=from_date,
        to_date=to_date,
        group_by=group_by,
    )


@router.get("/records")
async def get_usage_records(
    tenant_id: str = Query(...),
    user_id: Optional[str] = Query(None),
    model_id: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None, alias="from"),
    to_date: Optional[date] = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    cost_tracker: CostTracker = Depends(get_cost_tracker),
    auth: dict = Depends(_require_admin_role),
):
    """Return paginated individual usage records for audit."""
    return {
        "records": await cost_tracker.get_usage_details(
            tenant_id=tenant_id,
            user_id=user_id,
            from_date=from_date,
            to_date=to_date,
            model_id=model_id,
            limit=limit,
            offset=offset,
        ),
        "total": 0,  # TODO: add count query
        "limit": limit,
        "offset": offset,
    }


@router.get("/budget")
async def get_budget(
    tenant_id: str = Query(...),
    cost_tracker: CostTracker = Depends(get_cost_tracker),
    auth: dict = Depends(_require_admin_role),
):
    """Return current budget configuration with usage status."""
    return await cost_tracker.get_budget_config(tenant_id=tenant_id)


class BudgetUpdateDTO(BaseModel):
    tenant_id: str
    monthly_cost_cap_usd: Optional[Decimal] = None
    user_overrides: Optional[list[UserBudgetOverride]] = None


class UserBudgetOverride(BaseModel):
    user_id: str
    daily_token_limit: Optional[int] = None


@router.put("/budget")
async def update_budget(
    body: BudgetUpdateDTO,
    cost_tracker: CostTracker = Depends(get_cost_tracker),
    auth: dict = Depends(_require_admin_role),
):
    """Create or update budget configuration."""
    result = await cost_tracker.update_budget_config(
        tenant_id=body.tenant_id,
        monthly_cost_cap_usd=body.monthly_cost_cap_usd,
        created_by=auth.get("user_id", "admin"),
    )
    if body.user_overrides:
        for override in body.user_overrides:
            await cost_tracker.update_budget_config(
                tenant_id=body.tenant_id,
                user_id=override.user_id,
                daily_token_limit=override.daily_token_limit,
                created_by=auth.get("user_id", "admin"),
            )
    return result


@router.get("/pricing")
async def get_pricing(
    cost_tracker: CostTracker = Depends(get_cost_tracker),
    auth: dict = Depends(_require_admin_role),
):
    """Return current pricing table for all models."""
    # TODO: implement pricing listing in CostTracker
    return {"message": "Not yet implemented"}
```

### 3.2 Modifications to Existing AI Chat Endpoint

In `POST /api/v1/ai/chat` (`app/routers/ai_chat.py`, created in US-AI-023):

```python
# Before the LLM interaction loop:
budget = await cost_tracker.check_budget(
    user_id=session.user_id,
    tenant_id=session.tenant_id,
)
if not budget.allowed:
    raise HTTPException(
        status_code=429,
        detail=build_error(
            code="BUDGET_EXCEEDED",
            message=f"Budget exceeded: {budget.reason}",
            field="request",
            details={
                "reason": budget.reason,
                "resetAt": budget.reset_at,
                "limitType": "monthly_cost" if "COST" in (budget.reason or "") else "daily_token",
            },
        ),
    )

# Include warning headers if approaching limits:
response_headers = {}
if budget.warning:
    response_headers["X-AI-Budget-Warning"] = "true"
    response_headers["X-AI-Budget-Remaining"] = f"{budget.remaining_budget_pct:.0f}%"
    if budget.reset_at:
        response_headers["X-AI-Budget-ResetAt"] = budget.reset_at

# After each provider response within the tool loop:
usage_record = UsageRecord(
    session_id=session.session_id,
    turn_id=turn_id,
    user_id=session.user_id,
    tenant_id=session.tenant_id,
    provider=provider,
    model_id=model_id,
    request_type="chat",
    input_tokens=response.usage.input_tokens,
    output_tokens=response.usage.output_tokens,
    cache_creation_tokens=response.usage.cache_creation_input_tokens or 0,
    cache_read_tokens=response.usage.cache_read_input_tokens or 0,
    latency_ms=elapsed_ms,
)
try:
    await cost_tracker.record(usage_record)
except Exception:
    logger.warning("Failed to persist usage record", exc_info=True)
```

---

## 4. Implementation Plan — Task Breakdown

### Task 1: Database Migrations (Alembic)

**File:** `alembic/versions/20260614_0001_add_ai_cost_tracking_tables.py`

```python
"""Add ai_usage_records, ai_usage_aggregates, ai_pricing_table, ai_budget_config.

Revision ID: 20260614_0001
Revises: <previous_migration_id>
"""
from alembic import op
import sqlalchemy as sa

revision = "20260614_0001"
down_revision = "<previous_migration_id>"


def upgrade():
    op.create_table(
        "ai_usage_records",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("record_id", sa.String(64), unique=True, nullable=False),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("ai_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_id", sa.String(64), nullable=True),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("request_type", sa.String(32), nullable=False, server_default="chat"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_creation_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("cost_currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pricing_unknown", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_usage_tenant_date", "ai_usage_records", ["tenant_id", "created_at"])
    op.create_index("idx_usage_user_date", "ai_usage_records", ["user_id", "created_at"])
    op.create_index("idx_usage_session", "ai_usage_records", ["session_id"])
    op.create_index("idx_usage_model_date", "ai_usage_records", ["model_id", "created_at"])
    op.create_index("idx_usage_pricing_unknown", "ai_usage_records", ["pricing_unknown"],
                    postgresql_where=sa.text("pricing_unknown = TRUE"))

    op.create_table(
        "ai_usage_aggregates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("total_input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_cache_creation_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_cache_read_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_cost", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "user_id", "usage_date"),
    )
    op.create_index("idx_aggregates_tenant_date", "ai_usage_aggregates", ["tenant_id", "usage_date"])
    op.create_index("idx_aggregates_user_date", "ai_usage_aggregates", ["user_id", "usage_date"])

    op.create_table(
        "ai_pricing_table",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("model_display_name", sa.String(200)),
        sa.Column("input_token_rate", sa.Numeric(10, 8), nullable=False),
        sa.Column("output_token_rate", sa.Numeric(10, 8), nullable=False),
        sa.Column("cache_creation_token_rate", sa.Numeric(10, 8), nullable=False, server_default="0"),
        sa.Column("cache_read_token_rate", sa.Numeric(10, 8), nullable=False, server_default="0"),
        sa.Column("max_input_tokens", sa.Integer(), nullable=False, server_default="200000"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "model_id", "effective_from"),
    )

    op.create_table(
        "ai_budget_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(8), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("monthly_cost_cap_usd", sa.Numeric(12, 2), nullable=True),
        sa.Column("daily_token_limit", sa.Integer(), nullable=True),
        sa.Column("warning_threshold_pct", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("scope", "tenant_id", sa.text("COALESCE(user_id, '')")),
    )
    op.create_index("idx_budget_config_tenant", "ai_budget_config", ["tenant_id"])

    # Seed pricing data
    op.execute("""
        INSERT INTO ai_pricing_table (provider, model_id, model_display_name,
            input_token_rate, output_token_rate, cache_creation_token_rate, cache_read_token_rate,
            max_input_tokens, effective_from) VALUES
        ('anthropic', 'claude-sonnet-4-20250514',  'Claude Sonnet 4',
             0.00000300, 0.00001500, 0.00000375, 0.00000030, 200000, '2026-06-01'),
        ('anthropic', 'claude-haiku-3-5-20241022', 'Claude Haiku 3.5',
             0.00000080, 0.00000400, 0.00000100, 0.00000008, 200000, '2026-06-01'),
        ('anthropic', 'claude-opus-4-20250514',    'Claude Opus 4',
             0.00001500, 0.00007500, 0.00001875, 0.00000150, 200000, '2026-06-01'),
        ('openai',    'gpt-4o-2025-05-13',         'GPT-4o',
             0.00000250, 0.00001000, 0.00000125, 0.00000025, 128000, '2026-06-01'),
        ('openai',    'gpt-4o-mini-2025-07-18',    'GPT-4o Mini',
             0.00000015, 0.00000060, 0.00000008, 0.00000002, 128000, '2026-06-01');
    """)


def downgrade():
    op.drop_table("ai_budget_config")
    op.drop_table("ai_pricing_table")
    op.drop_table("ai_usage_aggregates")
    op.drop_table("ai_usage_records")
```

**Estimated effort:** 0.5 days

### Task 2: Create SQLAlchemy ORM Models

**File:** `app/models/ai_usage.py`

```python
"""SQLAlchemy ORM models for AI cost tracking.

All models use Base from app.models.base and follow the same patterns
as app/models/persisted_course.py and app/models/scoring.py.
"""
from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, Integer, BigInteger, Numeric, Boolean, Date,
    DateTime, Text, ForeignKey, UniqueConstraint,
)

from app.models.base import Base


class AIUsageRecord(Base):
    """Raw per-request usage record."""
    __tablename__ = "ai_usage_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(String(64), unique=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_sessions.session_id", ondelete="CASCADE")
    )
    turn_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str] = mapped_column(String(128))
    tenant_id: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str] = mapped_column(String(128))
    request_type: Mapped[str] = mapped_column(String(32), default="chat")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0)
    cost_currency: Mapped[str] = mapped_column(String(3), default="USD")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    pricing_unknown: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "recordId": self.record_id,
            "sessionId": self.session_id,
            "turnId": self.turn_id,
            "userId": self.user_id,
            "tenantId": self.tenant_id,
            "provider": self.provider,
            "modelId": self.model_id,
            "requestType": self.request_type,
            "tokens": {
                "input": self.input_tokens,
                "output": self.output_tokens,
                "cacheCreation": self.cache_creation_tokens,
                "cacheRead": self.cache_read_tokens,
            },
            "cost": float(self.cost),
            "costCurrency": self.cost_currency,
            "latencyMs": self.latency_ms,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class AIUsageAggregate(Base):
    """Denormalized daily usage rollups."""
    __tablename__ = "ai_usage_aggregates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(String(128))
    usage_date: Mapped[date] = mapped_column(Date)
    total_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_cache_creation_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_cache_read_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "usage_date"),
    )


class AIPricingRow(Base):
    """Model cost rates per provider."""
    __tablename__ = "ai_pricing_table"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str] = mapped_column(String(128))
    model_display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    input_token_rate: Mapped[Decimal] = mapped_column(Numeric(10, 8))
    output_token_rate: Mapped[Decimal] = mapped_column(Numeric(10, 8))
    cache_creation_token_rate: Mapped[Decimal] = mapped_column(Numeric(10, 8), default=0)
    cache_read_token_rate: Mapped[Decimal] = mapped_column(Numeric(10, 8), default=0)
    max_input_tokens: Mapped[int] = mapped_column(Integer, default=200000)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )


class AIBudgetConfig(Base):
    """Per-tenant and per-user budget limits."""
    __tablename__ = "ai_budget_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(8))
    tenant_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    monthly_cost_cap_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    daily_token_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    warning_threshold_pct: Mapped[int] = mapped_column(Integer, default=80)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
```

Add import to `app/models/__init__.py`:
```python
from app.models.ai_usage import (
    AIUsageRecord,
    AIUsageAggregate,
    AIPricingRow,
    AIBudgetConfig,
)
```

**Estimated effort:** 0.5 days

### Task 3: Implement `CostTracker` Service

**File:** `app/services/ai/cost_tracker.py`

Implement the `CostTracker` class with all methods as specified in Section 2.2.1.

Key implementation details:
- **Pricing cache**: Use `@lru_cache` with TTL (`AI_PRICING_CACHE_TTL_SECONDS`, default 300s) to avoid querying the pricing table on every request. Invalidate cache when `update_budget_config` is called.
- **Cost computation**: Use `Decimal` for all monetary calculations to avoid floating point errors.
- **Aggregate upsert**: Use PostgreSQL `INSERT ... ON CONFLICT (tenant_id, user_id, usage_date) DO UPDATE SET ...` for the aggregate upsert.
- **Error handling**: Wrap all DB operations in try/except, log failures, and never raise from `record()` — the caller must always be able to proceed even if metering fails.

**Estimated effort:** 2 days

### Task 4: Implement `BudgetSyncJob` Background Worker

**File:** `app/services/ai/budget_sync_job.py`

Implement as specified in Section 2.2.2. Wire into the application lifespan in `app/main.py`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # -- existing startup code --
    
    # Start budget sync job
    budget_sync = BudgetSyncJob(interval_seconds=300)
    sync_task = asyncio.create_task(budget_sync.run())
    
    yield
    
    # -- shutdown --
    await budget_sync.stop()
    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass
```

**Estimated effort:** 1 day

### Task 5: Create `ai_usage` Router

**File:** `app/routers/ai_usage.py`

Implement as specified in Section 3.1. Register in `app/main.py`:

```python
from app.routers import ai_usage
api_router.include_router(ai_usage.router)
```

**Estimated effort:** 1 day

### Task 6: Modify AI Chat Endpoint for Budget Checks

**Files modified:**
- `app/routers/ai_chat.py` (if exists from US-AI-023) or `app/routers/ai.py`

Add the pre-request budget check and post-response usage recording as specified in Section 3.2.

**Estimated effort:** 0.5 days

### Task 7: Add Feature Flag and Env Vars

**Files modified:**
- `app/utils/feature_flags.py` — add `cost_tracking` flag
- `.env.example` — add `AI_COST_TRACKING_ENABLED`, `AI_TENANT_MONTHLY_COST_CAP_USD`, `AI_USER_DAILY_TOKEN_LIMIT`, etc.

**Estimated effort:** 0.25 days

### Task 8: Add Prometheus Metrics

**File:** `app/services/ai/cost_tracker.py` — add Prometheus counter/gauges:

```python
import prometheus_client

ai_tokens_total = prometheus_client.Counter(
    "ai_tokens_total", "Total AI tokens by type and model",
    ["tenant_id", "model_id", "token_type"],  # token_type: input, output, cache_creation, cache_read
)
ai_cost_total = prometheus_client.Counter(
    "ai_cost_total", "Total AI cost in USD by tenant and model",
    ["tenant_id", "model_id"],
)
ai_budget_remaining = prometheus_client.Gauge(
    "ai_budget_remaining", "Remaining budget by tenant",
    ["tenant_id", "budget_type"],  # budget_type: monthly_cost, daily_tokens
)
ai_usage_requests_total = prometheus_client.Counter(
    "ai_usage_requests_total", "Total AI usage requests by tenant and result",
    ["tenant_id", "result"],  # result: recorded, budget_blocked, budget_warning
)
```

Update the budget check to set `ai_budget_remaining` gauge after each check.

**Estimated effort:** 0.5 days

### Task 9: Unit and Integration Tests

**File:** `tests/test_ai_cost_tracking.py`

See Section 6 for full test scenarios.

**Estimated effort:** 2 days

---

## 5. Security and Operational Considerations

### 5.1 Security

- **Data isolation**: Usage records are scoped by `tenant_id`. All usage API queries require tenant-scoped admin authorization. Cross-tenant data leakage is prevented by enforcing the `tenant_id` filter at the query level.
- **Pricing table integrity**: Only operators with database write access can modify the pricing table. The API does not expose a write endpoint for pricing rates.
- **Cost rounding**: Cost is computed with 6 decimal places of precision (micro-cents). Display rounding to 2 decimal places is done at the presentation layer only.

### 5.2 Operational Concerns

- **Usage record volume**: At scale (thousands of AI requests per hour), the `ai_usage_records` table will grow rapidly. Implement a retention policy:
  - Raw records: retain 90 days, then archive to cold storage.
  - Aggregates: retain indefinitely (immutable daily rollups).
  - Add a periodic cleanup job (`DELETE FROM ai_usage_records WHERE created_at < NOW() - INTERVAL '90 days'`) or use PostgreSQL partitioning by month.
- **Budget check performance**: The budget check queries `ai_usage_aggregates` (a single row per tenant+user+date), not the raw records table. This keeps budget checks in the low-millisecond range even at scale.
- **Pricing cache**: The in-memory pricing table cache means pricing updates take up to `AI_PRICING_CACHE_TTL_SECONDS` (default 300s) to propagate. For immediate propagation, operators can call a cache-invalidate endpoint or restart workers.
- **Concurrent writes**: The `UPDATE ... SET total_cost = total_cost + :cost` pattern is safe under PostgreSQL's MVCC because each concurrent writer adds to the existing value atomically.
- **Feature flag**: When `FEATURE_COST_TRACKING` is disabled, `CostTracker.record()` and `check_budget()` are no-ops that return immediately. No performance impact when the feature is off.

---

## 6. Test Scenarios

Create `tests/test_ai_cost_tracking.py` following the existing test patterns in `tests/conftest.py` (in-memory SQLite, FastAPI TestClient overrides).

### Test Group 1: Usage Recording

| # | Scenario | Steps | Expected Result |
|---|---|---|---|
| 1.1 | Record a basic usage entry | Create a `UsageRecord` with valid data and call `CostTracker.record()` | Returns a `record_id`; row exists in `ai_usage_records`; aggregate row is upserted |
| 1.2 | Record with unknown model (no pricing) | Create a `UsageRecord` with `model_id="unknown-model"` | Record is inserted with `cost=0` and `pricing_unknown=True`; no errors raised |
| 1.3 | Record with cache tokens | Include `cache_creation_tokens=500` and `cache_read_tokens=200` | Cost includes cache token rates from pricing table |
| 1.4 | Record failure handling | Force a DB connection error during `record()` | DB error is logged; no exception propagates to caller |
| 1.5 | Record idempotency | Insert the same `record_id` twice | Second insert fails UNIQUE constraint; first record is preserved |

### Test Group 2: Budget Check

| # | Scenario | Steps | Expected Result |
|---|---|---|---|
| 2.1 | Within budget | No usage recorded yet; tenant cap = $500 | `allowed=true`, `warning=false` |
| 2.2 | Approaching tenant cap (80%) | Record enough usage to reach 80% of $500 cap | `allowed=true`, `warning=true`, `remaining_budget_pct=20` |
| 2.3 | Exceeded tenant cap | Record usage exceeding $500 cap + $5 tolerance | `allowed=false`, `reason=TENANT_MONTHLY_COST_EXCEEDED`, `reset_at` = next month |
| 2.4 | Within user daily limit | User has used 10K of 100K daily limit | `allowed=true` |
| 2.5 | Exceeded user daily limit | User has used 100K of 100K daily limit | `allowed=false`, `reason=USER_DAILY_TOKEN_LIMIT_EXCEEDED` |
| 2.6 | No cap configured | `monthly_cost_cap_usd` is NULL in `ai_budget_config` | Budget check passes regardless of usage |
| 2.7 | Feature flag disabled | Set `FEATURE_COST_TRACKING=false` | Both `record()` and `check_budget()` are no-ops |

### Test Group 3: Usage API Endpoints

| # | Scenario | Steps | Expected Result |
|---|---|---|---|
| 3.1 | GET /usage/summary — valid query | Call with `tenant_id=tenant-1`, `from=2026-06-01`, `to=2026-06-30` | Returns 200 with summary, byModel, byUser; totals match seeded data |
| 3.2 | GET /usage/summary — unauthorized | Call without admin JWT | Returns 403 |
| 3.3 | GET /usage/summary — invalid group_by | Call with `group_by=invalid` | Returns 422 |
| 3.4 | GET /usage/records — paginated | Seed 150 records, call with `limit=50&offset=100` | Returns records 101-150, `total=150` |
| 3.5 | GET /usage/budget — existing config | Create a budget config for tenant-1 | Returns the config with current month usage |
| 3.6 | PUT /usage/budget — update | Update `monthly_cost_cap_usd` from 500 to 1000 | Returns the updated config with new cap |

### Test Group 4: Budget API with Chat Endpoint Integration

| # | Scenario | Steps | Expected Result |
|---|---|---|---|
| 4.1 | Chat request within budget | User within limits sends a chat message | Chat proceeds normally; usage recorded after each provider response |
| 4.2 | Chat request over budget | User over daily token limit sends a chat message | Returns 429 with `BUDGET_EXCEEDED` error body |
| 4.3 | Warning headers present | User at 85% of daily limit sends a chat message | Response includes `X-AI-Budget-Warning: true`, `X-AI-Budget-Remaining: 15%` |
| 4.4 | Multiple tool calls in one turn | Chat turn makes 3 tool calls | Each provider response is recorded as a separate `ai_usage_records` row |

### Test Group 5: Background Sync Job

| # | Scenario | Steps | Expected Result |
|---|---|---|---|
| 5.1 | Sync recreates missing aggregates | Delete an aggregate row, run sync job | Aggregate row is recreated from raw records |
| 5.2 | Sync updates existing aggregates | Manually set an aggregate to wrong value, run sync job | Aggregate is corrected to the sum of raw records |
| 5.3 | Sync at threshold emits alert | Tenant at 85% of cap with warning threshold at 80% | Logs alert-level entry; increments `ai_budget_warnings_total` metric |

### Test Group 6: Edge Cases

| # | Scenario | Steps | Expected Result |
|---|---|---|---|
| 6.1 | Zero tokens | Record with 0 input and 0 output tokens | Record is created with cost=0; aggregate incremented; no errors |
| 6.2 | Negative token counts | Attempt to record with negative `input_tokens` | Pydantic validation rejects the request with 422 |
| 6.3 | Extremely high token count | Record with `input_tokens=999999999` | Record is created; cost computation must handle large integers without overflow |
| 6.4 | Concurrent budget writes | 10 concurrent requests each recording 1 token for the same user+date | All 10 succeed; aggregate is exactly 10 (not less due to race) |
| 6.5 | Tenant with no usage records | New tenant with no `ai_usage_records` queries budget | Budget check returns `allowed=true` with zero cost and no warning |

---

## 7. Open Questions / Future Considerations

1. **Prometheus integration maturity**: The existing codebase does not currently expose a Prometheus metrics endpoint. US-AI-021 may add one. If it lands first, the Prometheus counters in Task 8 can register against it. If not, we should either add a `GET /api/v1/metrics` endpoint or skip Prometheus metrics until that epic ships.

2. **Cache token cost allocation**: Some providers (Anthropic) charge differently for cache writes vs cache reads. The current pricing model accounts for both, but the exact ratio depends on provider-specific behavior. We may need to adjust `_compute_cost()` when provider APIs change.

3. **Tenant vs organization hierarchy**: The current model uses `tenant_id` throughout. If the platform introduces a multi-level hierarchy (organization -> tenant -> user), the budget config needs to inherit or cascade. For MVP, flat tenant scope is sufficient.

4. **Notification integration**: When budget thresholds are crossed, the system currently only logs and sets headers. A future enhancement could integrate with email/Slack webhook notifications (US-AI-033 outbox consumer pattern).

5. **Budget rollover**: Unused budget does not roll over to the next month. This is intentional for simplicity. A future customer requirement may request rollover or pooled budgets across tenants.

6. **User-level budget grouping**: When enforcing user-level budgets, should usage be grouped by `user_id` globally, or scoped per tenant? The current design scopes it per tenant (a user has separate budgets for each tenant they belong to). This matches multi-tenant SaaS expectations.

7. **Cost allocation tagging**: Future: add an optional `tags` JSONB column to `ai_usage_records` for custom cost-allocation tags (e.g., `{"project": "onboarding", "department": "engineering"}`) surfaced via the API.

8. **Archive vs delete**: Raw usage records should be archived (not deleted) to cold storage after 90 days to support historical audit queries. The `ai_usage_aggregates` table provides the fast reporting path for periods up to 90 days; beyond that, the archive needs a query interface.

---

## 8. Migration Rollback Plan

1. **Feature flag disable** — Set `FEATURE_COST_TRACKING=false` to disable all cost tracking and budget enforcement without code changes.
2. **Env var disable** — Set `AI_COST_TRACKING_ENABLED=false` to skip budget checks while keeping recording active.
3. **Migration rollback** — If the migration must be reverted:
   ```bash
   alembic downgrade 20260614_0001
   ```
   This drops all four tables. Usage data is lost. Run the aggregate sync query against the database backup first if data preservation is needed.
4. **Code revert** — Revert the modified `ai_chat.py` to remove the `CostTracker.check_budget()` and `CostTracker.record()` calls. Remove the `ai_usage.py` router registration.
5. **Pricing table corrections** — If provider pricing changes, update the `ai_pricing_table` rows via SQL (no code change required). The cache TTL ensures new rates are picked up within `AI_PRICING_CACHE_TTL_SECONDS`.
