# US-AI-026: Multi-Provider Model Routing and Fallback

**Epic:** Platform Runtime and Operations (Flow 13)

**Priority:** SHOULD for MVP, MUST for production

**Depends on:** US-AI-002 (Feature flags and model config), US-AI-003 (Isolated AI API module), US-AI-023 (AI chat endpoint and LLM interaction loop)

**Story Points:** 8

---

## 1. Title

Multi-Provider Model Routing and Automatic Fallback with Circuit Breaker and Task-Tier Selection

---

## 2. Description

As an Operator, I want the AI layer to route requests across multiple LLM providers with automatic fallback on failure and task-tier-based model selection, so that availability, latency, and cost are optimized without user-visible impact.

Currently, the architecture specification (PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md section 10.2) defines a hardcoded primary/fallback pair pointing to Claude models. This story replaces that static config with a dynamic, database-backed routing system that:

- Supports N providers with weighted or priority-ordered routing
- Assigns different model tiers per task type (planning, generation, repair, safety classification)
- Implements a circuit breaker per provider endpoint to prevent cascading retries
- Logs every routing decision with latency, cost, model, and fallback chain for observability
- Integrates with the existing FeatureFlagService and the to-be-built cost tracker (US-AI-036)

---

## 3. Functional Details

### 3.1 Model Tier Assignment by Task Type

The system defines four task tiers, each with its own routing policy:

| Tier        | Task Types                                | Goal              | Max Cost/1K tokens |
|-------------|-------------------------------------------|-------------------|--------------------|
| PLANNER     | query_similar_courses, context pruning    | Fast and cheap    | $0.002             |
| GENERATOR   | propose_create_page, propose_update_page, chat orchestration | Best quality | $0.02              |
| REPAIR      | JSON repair, structured output recovery   | Fast, deterministic-ish | $0.004      |
| CLASSIFIER  | Prompt safety scanning, output guardrails  | Deterministic/small | $0.001           |

Each tier maps to a provider + model combination. Tiers are independently configurable.

### 3.2 Fallback Chain

For each tier, operators define an ordered list of `(provider, model)` pairs:

```
GENERATOR = [
  ("anthropic", "claude-sonnet-4-20250514",     weight=10),  # primary
  ("anthropic", "claude-haiku-3-5-20241022",    weight=5),   # cheaper fallback
  ("openai",    "gpt-4o-2025-05-13",             weight=3),   # cross-provider fallback
]
```

The router attempts providers in priority order. On failure, it moves to the next in the chain. Weight determines selection when multiple entries share the same priority tier (future use for canary A/B traffic splits).

### 3.3 Circuit Breaker

Each `(provider, model, tier)` combination has an independent circuit breaker:

- **Closed**: normal operation. Requests pass through.
- **Open**: after N consecutive failures (configurable, default 3) within a sliding window (default 60 seconds). No requests are sent; the next provider in the fallback chain is used immediately. After a cooldown period (default 30 seconds), transitions to **Half-Open**.
- **Half-Open**: allows 1 probe request. If it succeeds, the breaker transitions back to **Closed**. If it fails, returns to **Open** for another cooldown period.

### 3.4 Routing Decision Audit

Every LLM invocation records:

- `trace_id`: the request's trace ID
- `task_type`: the tier/task classification
- `provider`: the provider actually used
- `model`: the model actually used
- `fallback_chain`: the full ordered list attempted, with status per entry
- `latency_ms`: end-to-end latency for the successful call
- `input_tokens`, `output_tokens`: token counts from the provider response
- `cost_usd`: computed cost (tokens * per-model pricing)
- `circuit_breaker_state`: state of the selected provider's breaker at call time
- `error_code`: non-null if the successful call followed one or more failures

### 3.5 Feature Flag Gating

The entire routing subsystem is gated behind the existing `FEATURE_AI_SUGGESTIONS` flag. When disabled, the system returns a 404 for any AI route (as the existing `require_feature_async` decorator does today). Additionally, a new `FEATURE_MULTI_PROVIDER` flag specifically gates multi-provider routing; when disabled, the router falls back to a single (non-fallback) provider from env vars.

---

## 4. Technical Design

### 4.1 New File Structure

```
app/services/ai/model_router.py        -- Public facade: route_request()
app/services/ai/providers/             -- Provider adapters
  __init__.py                          -- Registry loader
  base.py                              -- Abstract base class
  anthropic_adapter.py                 -- Anthropic SDK wrapper
  openai_adapter.py                    -- OpenAI SDK wrapper (future)
  ollama_adapter.py                    -- Local/self-hosted adapter (future)
app/services/ai/circuit_breaker.py     -- Circuit breaker state machine
app/services/ai/provider_registry.py   -- DB-backed provider config loader
app/models/ai_provider.py              -- SQLAlchemy ORM models
app/repositories/ai_provider_repo.py   -- Repository for provider config
app/routers/ai_admin.py                -- Admin CRUD endpoints for providers
```

### 4.2 SQLAlchemy ORM Models (app/models/ai_provider.py)

```python
"""SQLAlchemy ORM models for AI provider configuration and routing."""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Integer, Float, Boolean, Text, ForeignKey

from app.models.base import Base


class AIProvider(Base):
    """Registered LLM provider (Anthropic, OpenAI, Ollama, etc.)."""
    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    provider_type: Mapped[str] = mapped_column(
        String(32), default="anthropic"
    )  # anthropic, openai, ollama
    base_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    api_key_env_var: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # Name of env var containing the key
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    config_json: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, default=dict
    )  # Extra config: timeout_s, max_retries, default_max_tokens
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "providerType": self.provider_type,
            "baseUrl": self.base_url,
            "isActive": self.is_active,
            "config": self.config_json,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }


class AIProviderModel(Base):
    """Specific model under a provider, with tier assignment and pricing."""
    __tablename__ = "ai_provider_models"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    tier: Mapped[str] = mapped_column(
        String(32), default="GENERATOR"
    )  # PLANNER, GENERATOR, REPAIR, CLASSIFIER
    priority: Mapped[int] = mapped_column(Integer, default=10)
    weight: Mapped[int] = mapped_column(Integer, default=10)
    
    # Pricing per 1K tokens
    input_price_per_1k: Mapped[float] = mapped_column(Float, default=0.0)
    output_price_per_1k: Mapped[float] = mapped_column(Float, default=0.0)
    
    # Circuit breaker defaults (overridable per model)
    max_consecutive_failures: Mapped[int] = mapped_column(Integer, default=3)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=30)
    window_seconds: Mapped[int] = mapped_column(Integer, default=60)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "providerId": self.provider_id,
            "modelId": self.model_id,
            "displayName": self.display_name,
            "tier": self.tier,
            "priority": self.priority,
            "weight": self.weight,
            "inputPricePer1K": self.input_price_per_1k,
            "outputPricePer1K": self.output_price_per_1k,
            "isActive": self.is_active,
        }


class AIProviderMetrics(Base):
    """Aggregated metrics per provider+model+tier for observability."""
    __tablename__ = "ai_provider_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[str] = mapped_column(String(128))
    tier: Mapped[str] = mapped_column(String(32))
    
    # Rolling window
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    successful_requests: Mapped[int] = mapped_column(Integer, default=0)
    failed_requests: Mapped[int] = mapped_column(Integer, default=0)
    total_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    
    window_start: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    window_end: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class AIRoutingLog(Base):
    """Per-request routing decision audit trail."""
    __tablename__ = "ai_routing_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    task_type: Mapped[str] = mapped_column(String(32))
    
    selected_provider_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_providers.id"), nullable=True
    )
    selected_model_id: Mapped[str] = mapped_column(String(128))
    
    fallback_chain: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=list
    )  # [{"provider": "anthropic", "model": "claude-...", "status": "failed", "error": "timeout"}, ...]
    
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    
    circuit_breaker_state: Mapped[str] = mapped_column(String(16), default="closed")
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
```

### 4.3 Alembic Migration

Add a new migration `20250614_0001_add_ai_provider_tables.py` with the DDL above. Include a seed migration that inserts the default provider records:

```python
from alembic import op
import sqlalchemy as sa

revision = "20250614_0001"
down_revision = "20251007_0001"  # depends on prior migration

def upgrade():
    op.create_table("ai_providers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False, server_default="anthropic"),
        sa.Column("base_url", sa.String(500), nullable=True),
        sa.Column("api_key_env_var", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("config_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_ai_providers_name", "ai_providers", ["name"])

    op.create_table("ai_provider_models",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("tier", sa.String(32), nullable=False, server_default="GENERATOR"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("weight", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("input_price_per_1k", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("output_price_per_1k", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("max_consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("window_seconds", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["ai_providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table("ai_provider_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("tier", sa.String(32), nullable=False),
        sa.Column("total_requests", sa.Integer(), server_default=sa.text("0")),
        sa.Column("successful_requests", sa.Integer(), server_default=sa.text("0")),
        sa.Column("failed_requests", sa.Integer(), server_default=sa.text("0")),
        sa.Column("total_latency_ms", sa.Float(), server_default=sa.text("0.0")),
        sa.Column("total_input_tokens", sa.Integer(), server_default=sa.text("0")),
        sa.Column("total_output_tokens", sa.Integer(), server_default=sa.text("0")),
        sa.Column("total_cost_usd", sa.Float(), server_default=sa.text("0.0")),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("window_end", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["ai_providers.id"], ondelete="CASCADE"),
    )

    op.create_table("ai_routing_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.String(64), nullable=False, index=True),
        sa.Column("session_id", sa.String(64), nullable=True, index=True),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("selected_provider_id", sa.Integer(), nullable=True),
        sa.Column("selected_model_id", sa.String(128), nullable=False),
        sa.Column("fallback_chain", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("latency_ms", sa.Integer(), server_default=sa.text("0")),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Float(), server_default=sa.text("0.0")),
        sa.Column("circuit_breaker_state", sa.String(16), server_default="closed"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("success", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.ForeignKeyConstraint(["selected_provider_id"], ["ai_providers.id"], ondelete="SET NULL"),
    )
```

### 4.4 Seed Data

Migration should also seed default provider configuration. Add this to the migration's `upgrade()`:

```python
from sqlalchemy.sql import table, column

# Default providers
providers_table = table("ai_providers",
    column("name", sa.String),
    column("provider_type", sa.String),
    column("api_key_env_var", sa.String),
    column("config_json", sa.JSON),
    column("created_at", sa.DateTime),
    column("updated_at", sa.DateTime),
)

op.bulk_insert(providers_table, [
    {
        "name": "anthropic-default",
        "provider_type": "anthropic",
        "api_key_env_var": "ANTHROPIC_API_KEY",
        "config_json": {"timeout_s": 60, "max_retries": 2, "default_max_tokens": 4096},
        "created_at": sa.func.now(),
        "updated_at": sa.func.now(),
    },
    {
        "name": "openai-fallback",
        "provider_type": "openai",
        "api_key_env_var": "OPENAI_API_KEY",
        "config_json": {"timeout_s": 30, "max_retries": 1, "default_max_tokens": 4096},
        "created_at": sa.func.now(),
        "updated_at": sa.func.now(),
    },
])

# Default models under each provider
models_table = table("ai_provider_models",
    column("provider_id", sa.Integer),
    column("model_id", sa.String),
    column("display_name", sa.String),
    column("tier", sa.String),
    column("priority", sa.Integer),
    column("input_price_per_1k", sa.Float),
    column("output_price_per_1k", sa.Float),
    column("created_at", sa.DateTime),
)

# Get provider IDs
conn = op.get_bind()
result = conn.execute(
    sa.text("SELECT id, name FROM ai_providers WHERE name IN ('anthropic-default', 'openai-fallback')")
)
provider_map = {row[1]: row[0] for row in result}

op.bulk_insert(models_table, [
    {
        "provider_id": provider_map["anthropic-default"],
        "model_id": "claude-sonnet-4-20250514",
        "display_name": "Claude Sonnet 4 (Primary Generator)",
        "tier": "GENERATOR",
        "priority": 10,
        "input_price_per_1k": 0.003,
        "output_price_per_1k": 0.015,
        "created_at": sa.func.now(),
    },
    {
        "provider_id": provider_map["anthropic-default"],
        "model_id": "claude-haiku-3-5-20241022",
        "display_name": "Claude Haiku 3.5 (Fast/Cheap)",
        "tier": "PLANNER",
        "priority": 10,
        "input_price_per_1k": 0.0008,
        "output_price_per_1k": 0.004,
        "created_at": sa.func.now(),
    },
    {
        "provider_id": provider_map["anthropic-default"],
        "model_id": "claude-haiku-3-5-20241022",
        "display_name": "Claude Haiku 3.5 (JSON Repair)",
        "tier": "REPAIR",
        "priority": 10,
        "input_price_per_1k": 0.0008,
        "output_price_per_1k": 0.004,
        "created_at": sa.func.now(),
    },
    {
        "provider_id": provider_map["openai-fallback"],
        "model_id": "gpt-4o-mini-2024-07-18",
        "display_name": "GPT-4o Mini (Cross-provider fallback)",
        "tier": "GENERATOR",
        "priority": 20,
        "input_price_per_1k": 0.00015,
        "output_price_per_1k": 0.0006,
        "created_at": sa.func.now(),
    },
])
```

### 4.5 Core Service: Circuit Breaker (app/services/ai/circuit_breaker.py)

```python
"""Circuit breaker state machine per provider-model-tier combination."""

from __future__ import annotations
import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class BreakerState:
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    opened_at: float = 0.0
    half_open_probe_sent: bool = False


class CircuitBreaker:
    """Per-(provider_id, model_id, tier) circuit breaker.

    Thread-safe via per-key locking (not shown for brevity, but required
    in production). Uses time-based state transitions.
    """

    def __init__(self):
        self._breakers: Dict[Tuple[int, str, str], BreakerState] = {}

    def _key(self, provider_id: int, model_id: str, tier: str) -> Tuple[int, str, str]:
        return (provider_id, model_id, tier)

    def get_state(self, provider_id: int, model_id: str, tier: str) -> str:
        key = self._key(provider_id, model_id, tier)
        state = self._breakers.get(key, BreakerState())
        now = time.time()

        if state.state == CircuitState.OPEN:
            # Check cooldown expiry (configurable, default 30s)
            cooldown = 30.0
            if now - state.opened_at >= cooldown:
                logger.info(
                    "Circuit breaker %r transitioning OPEN -> HALF_OPEN",
                    key,
                )
                state.state = CircuitState.HALF_OPEN
                state.half_open_probe_sent = False

        return state.state.value

    def record_success(self, provider_id: int, model_id: str, tier: str) -> None:
        key = self._key(provider_id, model_id, tier)
        state = self._breakers.get(key)
        if state is None:
            return
        if state.state == CircuitState.HALF_OPEN:
            logger.info(
                "Circuit breaker %r HALF_OPEN probe succeeded; closing",
                key,
            )
        state.state = CircuitState.CLOSED
        state.failure_count = 0
        state.opened_at = 0.0
        state.half_open_probe_sent = False

    def record_failure(
        self,
        provider_id: int,
        model_id: str,
        tier: str,
        max_failures: int = 3,
    ) -> None:
        key = self._key(provider_id, model_id, tier)
        state = self._breakers.setdefault(key, BreakerState())
        state.failure_count += 1
        state.last_failure_time = time.time()

        if state.failure_count >= max_failures and state.state in (
            CircuitState.CLOSED,
            CircuitState.UNKNOWN,
        ):
            logger.warning(
                "Circuit breaker %r opening after %d consecutive failures",
                key,
                state.failure_count,
            )
            state.state = CircuitState.OPEN
            state.opened_at = time.time()
```

### 4.6 Core Service: Model Router Facade (app/services/ai/model_router.py)

```python
"""Public facade for multi-provider model routing with fallback."""

from __future__ import annotations
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Type

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.circuit_breaker import CircuitBreaker, CircuitState
from app.repositories.ai_provider_repo import AIProviderRepository

logger = logging.getLogger(__name__)


class AllProvidersExhaustedError(Exception):
    """Raised when every provider in the chain failed."""


@dataclass
class ModelRoute:
    """A single entry in a fallback chain."""
    provider_id: int
    provider_name: str
    provider_type: str  # "anthropic", "openai", "ollama"
    model_id: str
    tier: str
    priority: int
    weight: int
    max_consecutive_failures: int
    cooldown_seconds: int
    window_seconds: int
    api_key: str
    base_url: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutingResult:
    """Result of a routing operation."""
    content: Any
    model_used: str
    provider_used: str
    provider_id: int
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    fallback_chain: List[Dict[str, Any]]
    circuit_breaker_state: str
    trace_id: str


@dataclass
class ModelResponse:
    """Normalized response from any provider adapter."""
    content: str
    model_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    raw_response: Any = None


class BaseProviderAdapter:
    """Abstract base for provider-specific SDK adapters."""

    async def complete(
        self,
        model_id: str,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float = 0.7,
        **kwargs,
    ) -> ModelResponse:
        raise NotImplementedError

    async def complete_stream(
        self,
        model_id: str,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncGenerator[bytes, None]:
        raise NotImplementedError
        yield b""  # pragma: no cover


class AnthropicAdapter(BaseProviderAdapter):
    """Adapter for Anthropic's Claude API."""

    def __init__(self, api_key: str, base_url: Optional[str] = None, **config):
        import anthropic
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        if config.get("timeout_s"):
            client_kwargs["timeout"] = config["timeout_s"]
        self.client = anthropic.AsyncAnthropic(**client_kwargs)
        self.default_max_tokens = config.get("default_max_tokens", 4096)

    async def complete(
        self,
        model_id: str,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float = 0.7,
        **kwargs,
    ) -> ModelResponse:
        start = time.monotonic()
        response = await self.client.messages.create(
            model=model_id,
            max_tokens=max_tokens or self.default_max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ModelResponse(
            content=response.content[0].text,
            model_id=model_id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=elapsed_ms,
            raw_response=response,
        )


class ModelRouter:
    """Routes LLM requests across providers with fallback and circuit breakers.

    Usage:
        router = ModelRouter(session, provider_repo)
        result = await router.route_request(
            task_type="GENERATOR",
            system_prompt="...",
            messages=[{"role": "user", "content": "Hello"}],
        )
    """

    def __init__(self, db_session: AsyncSession):
        self._repo = AIProviderRepository(db_session)
        self._breaker = CircuitBreaker()
        self._adapters: Dict[str, Type[BaseProviderAdapter]] = {}
        self._register_default_adapters()

    def _register_default_adapters(self):
        self.register_adapter("anthropic", AnthropicAdapter)
        # self.register_adapter("openai", OpenAIAdapter)    # future
        # self.register_adapter("ollama", OllamaAdapter)    # future

    def register_adapter(self, provider_type: str, adapter_cls: Type[BaseProviderAdapter]):
        self._adapters[provider_type] = adapter_cls

    async def route_request(
        self,
        task_type: str,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> RoutingResult:
        """Route a completion request through the provider fallback chain.

        Raises AllProvidersExhaustedError if all providers fail.
        """
        trace_id = trace_id or str(uuid.uuid4())
        fallback_chain: List[Dict[str, Any]] = []
        routes: List[ModelRoute] = await self._repo.get_routes_for_tier(
            task_type, only_active=True
        )

        if not routes:
            logger.error("No active routes configured for tier %s", task_type)
            raise AllProvidersExhaustedError(
                f"No providers configured for task type '{task_type}'"
            )

        for route in routes:
            # Check circuit breaker
            cb_state = self._breaker.get_state(
                route.provider_id, route.model_id, route.tier
            )
            if cb_state == CircuitState.OPEN.value:
                logger.warning(
                    "Circuit breaker OPEN for %s/%s (tier=%s); skipping",
                    route.provider_name, route.model_id, route.tier,
                )
                fallback_chain.append({
                    "provider": route.provider_name,
                    "providerId": route.provider_id,
                    "model": route.model_id,
                    "status": "skipped",
                    "error": f"circuit_breaker_open_{cb_state}",
                })
                continue

            # Get or create adapter
            adapter = await self._get_adapter(route)

            try:
                response = await adapter.complete(
                    model_id=route.model_id,
                    system_prompt=system_prompt,
                    messages=messages,
                    max_tokens=max_tokens or route.config.get("default_max_tokens", 4096),
                    temperature=temperature,
                )

                self._breaker.record_success(
                    route.provider_id, route.model_id, route.tier
                )

                # Compute cost
                cost_usd = (
                    response.input_tokens * route.config.get("input_price_per_1k", 0.0) / 1000
                    + response.output_tokens * route.config.get("output_price_per_1k", 0.0) / 1000
                )

                fallback_chain.append({
                    "provider": route.provider_name,
                    "providerId": route.provider_id,
                    "model": route.model_id,
                    "status": "success",
                })

                return RoutingResult(
                    content=response.content,
                    model_used=route.model_id,
                    provider_used=route.provider_name,
                    provider_id=route.provider_id,
                    latency_ms=response.latency_ms,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    cost_usd=cost_usd,
                    fallback_chain=fallback_chain,
                    circuit_breaker_state=cb_state,
                    trace_id=trace_id,
                )

            except Exception as exc:
                error_code = type(exc).__name__
                logger.warning(
                    "Provider %s/%s failed: %s",
                    route.provider_name, route.model_id, exc,
                )
                self._breaker.record_failure(
                    route.provider_id,
                    route.model_id,
                    route.tier,
                    max_failures=route.max_consecutive_failures,
                )
                fallback_chain.append({
                    "provider": route.provider_name,
                    "providerId": route.provider_id,
                    "model": route.model_id,
                    "status": "failed",
                    "error": error_code,
                })
                # Continue to next provider in chain

        # All providers failed
        logger.error(
            "All providers exhausted for tier=%s trace_id=%s",
            task_type, trace_id,
        )
        raise AllProvidersExhaustedError(
            f"All {len(routes)} providers failed for task type '{task_type}'"
        )

    async def _get_adapter(self, route: ModelRoute) -> BaseProviderAdapter:
        """Get or create a cached provider adapter instance."""
        cache_key = f"{route.provider_type}:{route.provider_id}"
        if cache_key not in self._adapter_cache:
            adapter_cls = self._adapters.get(route.provider_type)
            if not adapter_cls:
                raise ValueError(f"Unsupported provider type: {route.provider_type}")
            self._adapter_cache[cache_key] = adapter_cls(
                api_key=os.environ.get(route.api_key, ""),
                base_url=route.base_url,
                **(route.config or {}),
            )
        return self._adapter_cache[cache_key]
```

### 4.7 Provider Configuration Repository (app/repositories/ai_provider_repo.py)

```python
"""Repository for AI provider configuration."""

from __future__ import annotations
from typing import Optional, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.ai_provider import AIProvider, AIProviderModel
from app.services.ai.model_router import ModelRoute


class AIProviderRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_routes_for_tier(
        self, tier: str, only_active: bool = True
    ) -> Sequence[ModelRoute]:
        """Fetch all (provider, model) routes for a given tier, ordered by priority."""
        query = (
            select(AIProvider, AIProviderModel)
            .join(
                AIProviderModel,
                and_(
                    AIProvider.id == AIProviderModel.provider_id,
                    AIProviderModel.tier == tier,
                ),
            )
            .order_by(AIProviderModel.priority.asc())
        )
        if only_active:
            query = query.where(
                AIProvider.is_active == True,
                AIProviderModel.is_active == True,
            )

        result = await self.session.execute(query)
        rows = result.all()

        return [
            ModelRoute(
                provider_id=provider.id,
                provider_name=provider.name,
                provider_type=provider.provider_type,
                model_id=model.model_id,
                tier=model.tier,
                priority=model.priority,
                weight=model.weight,
                max_consecutive_failures=model.max_consecutive_failures,
                cooldown_seconds=model.cooldown_seconds,
                window_seconds=model.window_seconds,
                api_key=provider.api_key_env_var,
                base_url=provider.base_url,
                config={
                    **(provider.config_json or {}),
                    "input_price_per_1k": model.input_price_per_1k,
                    "output_price_per_1k": model.output_price_per_1k,
                },
            )
            for provider, model in rows
        ]

    async def get_active_providers(self) -> Sequence[AIProvider]:
        result = await self.session.execute(
            select(AIProvider).where(AIProvider.is_active == True)
        )
        return result.scalars().all()

    async def get_provider_models(
        self, provider_id: int
    ) -> Sequence[AIProviderModel]:
        result = await self.session.execute(
            select(AIProviderModel).where(
                AIProviderModel.provider_id == provider_id,
                AIProviderModel.is_active == True,
            )
        )
        return result.scalars().all()
```

### 4.8 Integration into the AI Chat Orchestrator

The existing `app/services/ai/chat_orchestrator.py` (to be built in US-AI-023) will call the router instead of directly invoking an LLM. The integration point:

```python
# In chat_orchestrator.py (pseudocode for integration)
from app.services.ai.model_router import ModelRouter

class ChatOrchestrator:
    def __init__(self, db_session: AsyncSession):
        self.router = ModelRouter(db_session)

    async def execute_turn(self, session, user_prompt, ...):
        result = await self.router.route_request(
            task_type="GENERATOR",
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            session_id=session.session_id,
        )
        # result.content, result.model_used, result.fallback_chain available
```

### 4.9 Admin API Endpoints (app/routers/ai_admin.py)

All endpoints gated behind `require_feature_async("ai_suggestions")`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/ai/admin/providers` | List all providers with their models |
| POST | `/api/v1/ai/admin/providers` | Create a new provider |
| PUT | `/api/v1/ai/admin/providers/{provider_id}` | Update provider config |
| DELETE | `/api/v1/ai/admin/providers/{provider_id}` | Soft-delete (set is_active=false) |
| GET | `/api/v1/ai/admin/providers/{provider_id}/models` | List models for a provider |
| POST | `/api/v1/ai/admin/providers/{provider_id}/models` | Add a model to a provider |
| PUT | `/api/v1/ai/admin/providers/{provider_id}/models/{model_id}` | Update model config |
| DELETE | .../models/{model_id}` | Deactivate a model |
| GET | `/api/v1/ai/admin/routing-logs` | Query routing logs (paginated, filterable) |
| GET | `/api/v1/ai/admin/circuit-breakers` | View current circuit breaker states |
| POST | `/api/v1/ai/admin/circuit-breakers/reset` | Reset all circuit breakers |

### 4.10 Feature Flag Updates

Add to `app/utils/feature_flags.py`:

```python
'multi_provider_routing': FeatureFlag(
    name='multi_provider_routing',
    enabled=False,
    description='Enable multi-provider model routing and fallback',
    environments=[Environment.DEVELOPMENT, Environment.QA, Environment.STAGING, Environment.PRODUCTION]
),
```

The `ModelRouter` checks this flag at construction; if disabled, it returns a single hardcoded provider from env vars `AI_PRIMARY_MODEL` and `AI_PRIMARY_API_KEY`.

---

## 5. API Contracts

### 5.1 Internal Service Contract (not HTTP, called by chat orchestrator)

```python
# app/services/ai/model_router.py

class ModelRouter:
    async def route_request(
        self,
        task_type: str,              # "GENERATOR" | "PLANNER" | "REPAIR" | "CLASSIFIER"
        system_prompt: str,           # System-level instructions
        messages: List[Dict[str, Any]],  # [{"role": "user"/"assistant", "content": "..."}]
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> RoutingResult:
        ...

class RoutingResult:
    content: str                       # The LLM response text
    model_used: str                    # "claude-sonnet-4-20250514"
    provider_used: str                 # "anthropic-default"
    provider_id: int
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    fallback_chain: List[Dict]         # Every attempt in this request
    circuit_breaker_state: str         # "closed" | "open" | "half_open"
    trace_id: str
```

### 5.2 Provider Adapter Contract

```python
class BaseProviderAdapter:
    async def complete(
        self,
        model_id: str,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float = 0.7,
        **kwargs,
    ) -> ModelResponse:
        """Synchronous (non-streaming) completion."""

    async def complete_stream(
        self,
        model_id: str,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncGenerator[bytes, None]:
        """Streaming completion (future)."""
```

### 5.3 Admin REST Endpoints

**GET /api/v1/ai/admin/providers**

Response:
```json
{
  "providers": [
    {
      "id": 1,
      "name": "anthropic-default",
      "providerType": "anthropic",
      "baseUrl": null,
      "isActive": true,
      "config": {"timeout_s": 60, "default_max_tokens": 4096},
      "models": [
        {
          "id": 1,
          "modelId": "claude-sonnet-4-20250514",
          "displayName": "Claude Sonnet 4",
          "tier": "GENERATOR",
          "priority": 10,
          "inputPricePer1K": 0.003,
          "outputPricePer1K": 0.015,
          "isActive": true
        }
      ],
      "createdAt": "2026-06-14T00:00:00Z"
    }
  ]
}
```

**POST /api/v1/ai/admin/providers**

Request:
```json
{
  "name": "openai-gpt4",
  "providerType": "openai",
  "apiKeyEnvVar": "OPENAI_API_KEY",
  "baseUrl": null,
  "config": {"timeout_s": 30}
}
```

**GET /api/v1/ai/admin/routing-logs?task_type=GENERATOR&from=2026-06-01&to=2026-06-14&page=1&per_page=50**

Response:
```json
{
  "logs": [
    {
      "traceId": "abc-123",
      "sessionId": "sess-456",
      "taskType": "GENERATOR",
      "selectedModelId": "claude-sonnet-4-20250514",
      "selectedProviderId": 1,
      "latencyMs": 2450,
      "inputTokens": 1542,
      "outputTokens": 389,
      "costUsd": 0.01245,
      "circuitBreakerState": "closed",
      "fallbackChain": [
        {"provider": "anthropic-default", "model": "claude-sonnet-4-20250514", "status": "success"}
      ],
      "success": true,
      "createdAt": "2026-06-14T12:30:00Z"
    }
  ],
  "total": 1234,
  "page": 1,
  "perPage": 50
}
```

**GET /api/v1/ai/admin/circuit-breakers**

Response:
```json
{
  "breakers": [
    {
      "key": "1:claude-sonnet-4-20250514:GENERATOR",
      "providerName": "anthropic-default",
      "modelId": "claude-sonnet-4-20250514",
      "tier": "GENERATOR",
      "state": "closed",
      "failureCount": 0,
      "lastFailureAt": null,
      "openedAt": null
    }
  ]
}
```

---

## 6. Environment Variables

Add to `.env.example` and document:

```bash
# ============================================
# AI Multi-Provider Routing
# ============================================

# API Keys (one per provider type)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...

# Fallback single-provider mode (used when FEATURE_MULTI_PROVIDER=false)
AI_PRIMARY_PROVIDER=anthropic
AI_PRIMARY_MODEL=claude-sonnet-4-20250514
AI_PRIMARY_API_KEY=${ANTHROPIC_API_KEY}
AI_PRIMARY_MAX_TOKENS=4096
AI_PRIMARY_TIMEOUT_S=60

# Circuit breaker defaults (overridable per model in DB)
AI_CB_MAX_FAILURES=3
AI_CB_COOLDOWN_SECONDS=30
AI_CB_WINDOW_SECONDS=60

# Feature flag override
FEATURE_MULTI_PROVIDER_ROUTING=true

# Cost tracking (thresholds)
AI_TENANT_MONTHLY_COST_CAP_USD=500
AI_USER_DAILY_TOKEN_LIMIT=500000
```

Update the global `feature_flags` in `app/utils/feature_flags.py`:

```python
# Add to _initialize_flags()
'multi_provider_routing': FeatureFlag(
    name='multi_provider_routing',
    enabled=False,
    description='Enable multi-provider model routing with circuit breakers',
    environments=[Environment.DEVELOPMENT, Environment.QA, Environment.STAGING, Environment.PRODUCTION]
),
```

---

## 7. Test Scenarios

### 7.1 Unit Tests (test_model_router.py)

**TC-RTR-01**: `route_request` with single provider returns content successfully.
- Mock `AIProviderRepository.get_routes_for_tier` returning 1 route.
- Mock `AnthropicAdapter.complete` returning a valid response.
- Assert `RoutingResult.content` matches mock, `fallback_chain` has 1 entry with status "success".

**TC-RTR-02**: `route_request` falls back to second provider when first fails.
- First adapter raises `APIConnectionError`. Second adapter succeeds.
- Assert `result.model_used` is the second provider's model.
- Assert `fallback_chain` has 2 entries: first with "failed", second with "success".

**TC-RTR-03**: `route_request` raises `AllProvidersExhaustedError` when all fail.
- All adapters raise exceptions. Assert exception is raised.

**TC-RTR-04**: `route_request` respects circuit breaker OPEN state and skips provider.
- Set breaker state to OPEN for the first provider.
- Assert first entry in fallback_chain has status "skipped".
- Assert only the second provider is attempted.

**TC-RTR-05**: No routes configured for tier raises `AllProvidersExhaustedError`.
- Mock `get_routes_for_tier` returning empty list. Assert error.

**TC-RTR-06**: Circuit breaker transitions OPEN -> HALF_OPEN after cooldown.
- Record 3 failures. Assert state is OPEN.
- Advance time by 31 seconds (past cooldown).
- Call `get_state`. Assert state is HALF_OPEN.

**TC-RTR-07**: Circuit breaker HALF_OPEN probe success transitions to CLOSED.
- Set state to HALF_OPEN. Call `record_success`. Assert state is CLOSED.

**TC-RTR-08**: Circuit breaker HALF_OPEN probe failure returns to OPEN.
- Set state to HALF_OPEN, max_failures=3, failure_count=2.
- Call `record_failure`. Assert state is OPEN.

### 7.2 Integration Tests (test_provider_repo.py)

**TC-RPO-01**: `get_routes_for_tier` returns models ordered by priority.
- Seed 2 models for GENERATOR tier with priorities 10 and 20.
- Assert returned list has priority-10 model first.

**TC-RPO-02**: `get_routes_for_tier` excludes inactive providers/models.
- Deactivate one model. Assert only active model is returned.

**TC-RPO-03**: `get_routes_for_tier` returns empty for non-existent tier.
- Assert empty list.

### 7.3 API Integration Tests (test_ai_admin_api.py)

**TC-ADM-01**: GET `/api/v1/ai/admin/providers` returns seeded providers.
**TC-ADM-02**: POST `/api/v1/ai/admin/providers` creates a new provider.
**TC-ADM-03**: POST with missing `name` returns 422 validation error.
**TC-ADM-04**: PUT updates provider config and returns updated record.
**TC-ADM-05**: GET `/api/v1/ai/admin/routing-logs` returns paginated results.
**TC-ADM-06**: GET `/api/v1/ai/admin/circuit-breakers` returns states.
**TC-ADM-07**: POST `/api/v1/ai/admin/circuit-breakers/reset` resets all states.
**TC-ADM-08**: All admin endpoints return 404 when `FEATURE_AI_SUGGESTIONS` is disabled.

### 7.4 End-to-End / Contract Tests

**TC-E2E-01**: Chat orchestrator with 2 providers; primary fails, fallback succeeds.
- Set up provider chain: anthropic (will fail) -> openai (will succeed).
- Send a chat message. Assert response is returned from fallback.
- Assert `ai_routing_logs` contains 2 entries (one failure, one success).

**TC-E2E-02**: Chat orchestrator with 0 providers returns 503.
- Deactivate all providers. Assert chat returns 503 "AI service unavailable".

**TC-E2E-03**: Circuit breaker blocks failing provider after N failures, uses fallback.
- Make N+1 requests. First N succeed (or use fallback). After N failures on primary, Assert subsequent requests skip primary entirely.

**TC-E2E-04**: Admin can view routing logs filtered by date range.
- Create routing logs with known timestamps. Filter by date range. Assert correct subset.

---

## 8. Task Breakdown

### Task A: Data Layer (3 SP)
- **A.1**: Create SQLAlchemy models in `app/models/ai_provider.py` (AIProvider, AIProviderModel, AIProviderMetrics, AIRoutingLog).
- **A.2**: Create Alembic migration with the DDL and seed data for default Anthropic provider/models.
- **A.3**: Create `app/repositories/ai_provider_repo.py` with `get_routes_for_tier`, `get_active_providers`, `get_provider_models`.
- **A.4**: Register models in `app/models/__init__.py` and import in `main.py` lifespan.

### Task B: Circuit Breaker (2 SP)
- **B.1**: Implement `app/services/ai/circuit_breaker.py` with state machine, time-based transitions, and thread-safe state storage.
- **B.2**: Write unit tests (TC-RTR-06 through TC-RTR-08).

### Task C: Provider Adapters (2 SP)
- **C.1**: Implement `BaseProviderAdapter` abstract class in `app/services/ai/providers/base.py`.
- **C.2**: Implement `AnthropicAdapter` in `app/services/ai/providers/anthropic_adapter.py`.
- **C.3**: Implement adapter registry in `app/services/ai/providers/__init__.py`.

### Task D: Model Router Facade (3 SP)
- **D.1**: Implement `ModelRouter` in `app/services/ai/model_router.py` with fallback chain logic, circuit breaker integration, cost computation, and routing log persistence.
- **D.2**: Write unit tests (TC-RTR-01 through TC-RTR-05).
- **D.3**: Integration point with chat orchestrator (US-AI-023) -- replace hardcoded LLM call with `router.route_request()`.

### Task E: Admin API (2 SP)
- **E.1**: Implement `app/routers/ai_admin.py` with CRUD for providers/models, routing log query, circuit breaker status/reset.
- **E.2**: Register router in `main.py` gated by feature flag `require_feature_async("ai_suggestions")`.
- **E.3**: Write API integration tests (TC-ADM-01 through TC-ADM-08).

### Task F: Configuration and Feature Flag (1 SP)
- **F.1**: Add `multi_provider_routing` feature flag to `FeatureFlagService`.
- **F.2**: Add fallback single-provider env vars (when flag is off) for backward compatibility.
- **F.3**: Update `.env.example` with new environment variables.
- **F.4**: Write end-to-end tests (TC-E2E-01 through TC-E2E-04).

---

**Acceptance Criteria Summary:**

1. When primary provider returns 5xx/timeout/rate-limit, fallback provider is used transparently -- no user-visible error for single-provider failure.
2. Both/all providers failing returns 503 "AI service unavailable" with a clear message.
3. Circuit breaker prevents cascading retries: after N consecutive failures, the failing provider is skipped for a cooldown period.
4. Routing metadata (trace_id, model_used, fallback_chain, latency, cost) is recorded in `ai_routing_logs` for every LLM call.
5. Admin API allows viewing and configuring providers without server restart.
6. Feature flag can disable multi-provider routing entirely, reverting to a single hardcoded provider from env vars.
7. Task-tier routing assigns different models to PLANNER, GENERATOR, REPAIR, and CLASSIFIER tasks.

**Files to be created:**
- `C:\Users\ADMIN\e-learning-backend\app\models\ai_provider.py`
- `C:\Users\ADMIN\e-learning-backend\app\repositories\ai_provider_repo.py`
- `C:\Users\ADMIN\e-learning-backend\app\services\ai\model_router.py`
- `C:\Users\ADMIN\e-learning-backend\app\services\ai\circuit_breaker.py`
- `C:\Users\ADMIN\e-learning-backend\app\services\ai\providers\__init__.py`
- `C:\Users\ADMIN\e-learning-backend\app\services\ai\providers\base.py`
- `C:\Users\ADMIN\e-learning-backend\app\services\ai\providers\anthropic_adapter.py`
- `C:\Users\ADMIN\e-learning-backend\app\routers\ai_admin.py`
- `C:\Users\ADMIN\e-learning-backend\alembic\versions\20250614_0001_add_ai_provider_tables.py`

**Files to be modified:**
- `C:\Users\ADMIN\e-learning-backend\app\models\__init__.py` (register new models)
- `C:\Users\ADMIN\e-learning-backend\app\utils\feature_flags.py` (add multi_provider_routing flag)
- `C:\Users\ADMIN\e-learning-backend\app\main.py` (register ai_admin router, import ai_provider models in lifespan)
- `C:\Users\ADMIN\e-learning-backend\.env.example` (add new env vars)
- `C:\Users\ADMIN\e-learning-backend\.env` (add local dev overrides if needed)
- `C:\Users\ADMIN\e-learning-backend\app\services\ai\chat_orchestrator.py` (integrate ModelRouter once built in US-AI-023)

---
The full enriched epic has been written at:

**`C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-AI-027_JSON_REPAIR_STRUCTURED_OUTPUT_RECOVERY_EPIC.md`** (1021 lines)

The epic covers all 8 sections with specific, actionable detail:

### Section 1 -- Title and Metadata
Canonical ID, source flow, priority, dependencies (US-AI-005, US-AI-026), audit gap reference.

### Section 2 -- Business Context and User Story
Enriched context explaining the failure modes observed in production (8 specific JSON error categories), quantitative business impact table (repair reduces LLM retries from ~8% to ~0.5%), and how this integrates into the US-AI-023 chat orchestrator loop.

### Section 3 -- Functional Requirements (FR-1 through FR-5)
- **FR-1**: 10 deterministic regex strategies with exact patterns, order, and example fixes (strip_code_fences, remove_trailing_commas, escape_single_quotes, fix_nan_infinity, fix_duplicate_keys, etc.)
- **FR-2**: Fast-model (Haiku/GPT-4o-mini) fallback with repair-specific prompt contract
- **FR-3**: Repair budget (1 deterministic pass + 2 fast-model calls) and escalation to primary model regeneration
- **FR-4**: Structured output recovery for non-tool-call JSON (template data, validation, batch proposals)
- **FR-5**: Structured telemetry payload with Prometheus metrics and per-template-type failure tracking

### Section 4 -- Non-Functional Requirements
Latency budget (<10 ms deterministic, <500 ms fast model, <3 s total), accuracy targets (95% deterministic, 99% combined), safety rules (never change values, last-value-wins dedup, idempotency), observability (Prometheus counters/histograms), rate-limit exemption.

### Section 5 -- Technical Design and API Contracts
Complete `JsonRepairService` class with full method signatures, `RepairEvent` dataclass, strategy type definitions, `_deterministic_repair()` internals, `safe_json_loads()` backward-compatible wrapper. All 10 strategy function implementations with regex patterns. Fast-model repair prompt template. Integration hooks into `ChatOrchestrator` with `_parse_tool_call_response()` replacement code. `JsonRepairInfo` DTO added to chat response for frontend badges.

### Section 6 -- Database Design (DDL)
Full PostgreSQL DDL for `ai_repair_events` table (BIGSERIAL PK, trace_id, error_type, strategy arrays, latency_ms, snippet columns) with indexes and month-based partitioning. `AiRepairEvent` SQLAlchemy ORM model. `ALTER TABLE ai_sessions` migration adding `repair_count` and `last_repair_event_id` columns.

### Section 7 -- Configuration and Environment Variables
8 new env vars (`AI_REPAIR_MAX_ATTEMPTS`, `AI_REPAIR_MODEL`, `AI_REPAIR_ENABLE_DETERMINISTIC`, `AI_REPAIR_SNIPPET_LENGTH`, etc.) with types, defaults, and descriptions. `json_repair` feature flag added to `FeatureFlagService`. App lifecycle wiring via `setup_json_repair()` in `app/main.py`.

### Section 8 -- Test Scenarios and Task Breakdown
- 20 unit test scenarios (TR-01 through TR-20) covering each strategy
- 6 fast-model mock tests (FM-01 through FM-06)
- 10 integration tests (IT-01 through IT-10) covering orchestrator integration, DB persistence, feature flags, env var controls
- 4 security tests (ST-01 through ST-04) for injection and PII safety
- 6 tasks totaling 11 engineering days with per-task acceptance criteria

### Appendices
- Error pattern frequency registry (10 patterns with estimated production frequency)
- Full dependency graph showing how US-AI-027 connects to US-AI-005, US-AI-023, US-AI-024, US-AI-026, US-AI-021, US-AI-036, and US-AI-022

---
Now I have a thorough understanding of the codebase. Let me write the full enriched epic.

---

## Enriched User Story: US-AI-028 -- Context Pruning and Token Optimization

### 1. Title & Metadata

| Field | Value |
|---|---|
| **Title** | Context Pruning and Token Optimization |
| **Story ID** | US-AI-028 |
| **Priority** | SHOULD for production |
| **Dependencies** | US-AI-005 (Tool and Template Contract Registry), US-AI-023 (AI Chat Endpoint and LLM Interaction Loop) |
| **Source Flow** | 13. Platform Runtime and Operations Flow |
| **Epic Span** | 2 sprints (Sprint 1: core pruner + relevance engine; Sprint 2: integration, observability, hardening) |

### 2. Business Context & Problem Statement

**Problem:** The AI chat orchestrator (`app/services/ai/chat_orchestrator.py`) currently includes the full system prompt with every registered tool schema, template definition, and verbose documentation for every chat turn. With 12+ tools and 10+ template schemas (each with field-level validation rules, render configs, SCORM behavior configs, and sanitize rules), a single system prompt can exceed 8,000 tokens before the user message is even added. At scale (1000+ sessions/day), this wastes an estimated 40-60% of input token budget on irrelevant context, directly multiplying monthly API costs without improving output quality.

**Cost Projection (Conservative):**

| Component | Full Prompt (tokens) | Pruned Prompt (tokens) | Monthly Waste (10K turns) |
|---|---|---|---|
| Tool schemas | 4,200 | 1,100 | 31M tokens |
| Template definitions | 3,800 | 800 | 30M tokens |
| Documentation/instructions | 1,500 | 500 | 10M tokens |
| **Total per turn** | **9,500** | **2,400** | **71M tokens** |

At $3/M input tokens (Claude 3 Opus), this is approximately $213/month wasted per 10K turns.

**Goal:** Reduce average input token count by 60% per chat turn without degrading output quality, measured by:
- Perplexity parity on generated content before/after pruning
- Validation error rate parity (pruned prompts should not increase schema violations)
- User satisfaction parity (no increase in "retry" requests)

### 3. Functional Requirements

#### FR1: Relevant Schema Selection
The pruner MUST identify which template schemas and tool definitions are relevant to the current user intent, course context, and active proposals. Only relevant schemas are included in the system prompt.

- **FR1.1** The pruner receives the user prompt and current session state (course_id, active_proposal_ids, last_page_focused).
- **FR1.2** The pruner returns a set of `relevant_template_type_keys` and `relevant_tool_names`.
- **FR1.3** The pruner MUST always include `create_session`, `list_pages`, `fetch_page`, and `validate_course` tools regardless of user intent (safety baseline).
- **FR1.4** The pruner MUST always include the `final-assessment` template schema if the course has any final-assessment pages, even if the current chat turn does not reference them.

#### FR2: Context Category Stratification
The system prompt is divided into three categories for pruning decisions:

- **Always-include** (never pruned): core safety rules, system identity, output format rules, response guidelines, PII/safety guardrails.
- **Contextual** (pruned by relevance): template schemas, tool definitions, validation rules, SCORM export compatibility notes.
- **Droppable** (removed unless explicitly relevant): verbose documentation, multi-page examples, RAG result formatting instructions, deprecated tool notes.

#### FR3: Pruning Decision Caching
The relevance classification for a session is cached for 30 seconds. If the user sends another message within 30 seconds of the previous turn, the same pruning set is reused.

#### FR4: Fallback to Full Context
If the pruner produces an empty or below-threshold relevance set, the orchestrator falls back to the full context. The default minimum relevance set size is 3 template schemas + 4 tools.

#### FR5: Observability
Every pruned prompt logs:
- Total tokens before and after pruning
- Templates included / excluded
- Tools included / excluded
- Pruning decision latency (ms)
- User intent classification (text-only, assessment, mixed, unknown)

### 4. Technical Design

#### 4.1 Service Architecture

```
POST /api/v1/ai/chat
         |
    chat_orchestrator.py
         |
    +----v----+
    | intent_classifier  |  -- lightweight regex/NLP to categorize user intent
    +----+----+
         |
    +----v---------+
    | context_pruner |
    +----+---------+
         |
    +----v--------+
    | prompt_assembler |  -- builds the final system prompt from categorized sections
    +----+--------+
         |
    +----v-----------+
    | LLM interaction |
    +----------------+
```

**Module structure:**

```
app/services/ai/
  context_pruner.py          -- Main pruner orchestrator
  intent_classifier.py       -- Lightweight user intent classification
  prompt_assembler.py        -- Assembles system prompt from categorized sections
  prompt_sections/           -- Categorized system prompt fragments
    always_include/
      base_instructions.py
      safety_rules.py
    contextual/
      tool_definitions.py
      template_schemas.py
      validation_rules.py
    droppable/
      verbose_examples.py
      deprecated_notes.py
      rag_formatting.py
```

#### 4.2 API Contracts

**Internal Service Interface (not REST -- called by chat orchestrator)**

```python
# app/services/ai/context_pruner.py

@dataclass
class PruningContext:
    session_id: str
    course_id: str
    user_prompt: str
    active_proposal_ids: list[str]
    last_page_focused: Optional[str]
    course_template_types: list[str]  # template types present in the course
    available_tool_names: list[str]    # all registered tools

@dataclass
class PruningDecision:
    relevant_template_types: list[str]
    relevant_tool_names: list[str]
    always_include_sections: list[str]  # section identifiers
    contextual_sections_included: list[str]
    droppable_sections_included: list[str]
    total_input_tokens_before: int
    total_input_tokens_after: int
    pruning_latency_ms: float
    intent_category: str  # "text_only" | "assessment" | "mixed" | "navigation" | "unknown"

class ContextPruner:
    """Main context pruner orchestrator."""
    
    def __init__(
        self,
        template_registry: TemplateDefinitionRepository,
        tool_registry: ToolRegistry,
        intent_classifier: IntentClassifier,
        prompt_assembler: PromptAssembler,
        token_counter: TokenCounter,
    ):
        self._template_registry = template_registry
        self._tool_registry = tool_registry
        self._intent_classifier = intent_classifier
        self._prompt_assembler = prompt_assembler
        self._token_counter = token_counter
    
    async def build_pruned_prompt(
        self,
        context: PruningContext,
        conversation_history: list[dict],
        system_prompt_fragments: dict[str, str],
    ) -> tuple[str, PruningDecision]:
        """
        Build a pruned system prompt based on relevance.
        
        Returns (pruned_system_prompt, pruning_decision).
        """
        intent = await self._intent_classifier.classify(
            context.user_prompt,
            context.last_page_focused,
        )
        
        relevant_templates = await self._select_relevant_templates(
            intent, context.course_template_types
        )
        relevant_tools = self._select_relevant_tools(
            intent, context.available_tool_names
        )
        
        # Assemble sections
        included_sections = self._determine_sections(
            intent, relevant_templates, relevant_tools
        )
        
        pruned_prompt = self._prompt_assembler.assemble(
            system_prompt_fragments, included_sections
        )
        
        tokens_before = self._token_counter.count(
            self._prompt_assembler.assemble_all(system_prompt_fragments)
        )
        tokens_after = self._token_counter.count(pruned_prompt)
        
        return pruned_prompt, PruningDecision(
            relevant_template_types=relevant_templates,
            relevant_tool_names=relevant_tools,
            always_include_sections=["base_instructions", "safety_rules"],
            contextual_sections_included=included_sections["contextual"],
            droppable_sections_included=included_sections["droppable"],
            total_input_tokens_before=tokens_before,
            total_input_tokens_after=tokens_after,
            pruning_latency_ms=0.0,  # filled by orchestrator
            intent_category=intent.category.value,
        )
```

```python
# app/services/ai/intent_classifier.py

@dataclass
class IntentClassification:
    category: str  # text_only | assessment | mixed | navigation | unknown
    confidence: float  # 0.0 - 1.0
    mentioned_template_types: list[str]  # template types explicitly mentioned in prompt
    mentioned_tools: list[str]  # tools explicitly mentioned in prompt
    detected_keywords: list[str]

class IntentClassifier:
    """
    Lightweight rule-based + optional fast-model intent classifier.
    
    Rule patterns are defined in a YAML file at conf/intent_patterns.yaml,
    allowing tuning without code changes.
    """
    
    PATTERNS: dict[str, list[str]] = {
        "text_only": [
            r"\b(rewrite|simplify|expand|shorten|rephrase|paraphrase)\b",
            r"\b(text|content|paragraph|wording)\b",
            r"\b(tone|style|voice|language)\b",
        ],
        "assessment": [
            r"\b(quiz|test|assessment|exam|question|mcq|multiple.choice)\b",
            r"\b(score|passing|grade|correct|answer)\b",
            r"\b(final.assessment)\b",
        ],
        "navigation": [
            r"\b(reorder|move|rearrange|sequence|order)\b",
            r"\b(navigate|flow|progression|path)\b",
        ],
        "mixed": [],  # fallback when multiple categories match
    }
    
    def classify(
        self, prompt: str, last_page_focused: Optional[str] = None
    ) -> IntentClassification:
        """Classify user intent from the prompt text."""
        ...
```

```python
# app/services/ai/prompt_assembler.py

class PromptAssembler:
    """
    Assembles the final system prompt from categorized sections.
    
    Sections are stored as modular .py files in app/services/ai/prompt_sections/
    or loaded from the database (ai_prompt_sections table).
    """
    
    SECTION_REGISTRY: dict[str, str] = {}  # key -> section text
    
    def assemble(
        self,
        all_fragments: dict[str, str],
        included_sections: dict[str, list[str]],
    ) -> str:
        """
        Build system prompt from included sections.
        
        Order: always_include -> contextual -> droppable
        Within each category, sections are assembled in registration order.
        """
        ordered = (
            [all_fragments[s] for s in included_sections.get("always", [])]
            + [all_fragments[s] for s in included_sections.get("contextual", [])]
            + [all_fragments[s] for s in included_sections.get("droppable", [])]
        )
        return "\n\n---\n\n".join(ordered)
    
    def assemble_all(self, all_fragments: dict[str, str]) -> str:
        """Assemble ALL sections (for token baseline computation)."""
        return self.assemble(
            all_fragments,
            {"always": list(all_fragments.keys()), "contextual": [], "droppable": []},
        )
```

```python
# app/services/ai/token_counter.py

class TokenCounter:
    """
    Token counter for system prompts.
    
    Uses tiktoken (cl100k_base encoding) for accurate estimation.
    Falls back to rough character-based estimation if tiktoken is unavailable.
    """
    
    def __init__(self, encoding_name: str = "cl100k_base"):
        try:
            import tiktoken
            self._encoding = tiktoken.get_encoding(encoding_name)
            self._mode = "tiktoken"
        except ImportError:
            self._mode = "estimate"
    
    def count(self, text: str) -> int:
        if self._mode == "tiktoken":
            return len(self._encoding.encode(text))
        # Rough: ~4 chars per token for English text
        return len(text) // 4
```

#### 4.3 Database Schema (DDL)

```sql
-- Migration: XXXX_add_ai_prompt_sections.sql
-- Revision ID: xxxx_add_ai_prompt_sections

CREATE TABLE ai_prompt_sections (
    id              SERIAL PRIMARY KEY,
    section_key     VARCHAR(100) NOT NULL UNIQUE,
    category        VARCHAR(20) NOT NULL CHECK (category IN ('always_include', 'contextual', 'droppable')),
    content         TEXT NOT NULL,
    token_count     INTEGER NOT NULL DEFAULT 0,
    description     VARCHAR(500),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    version         INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_ai_prompt_sections_category ON ai_prompt_sections(category);
CREATE INDEX ix_ai_prompt_sections_active ON ai_prompt_sections(is_active);

-- Seed data for base sections
INSERT INTO ai_prompt_sections (section_key, category, content, token_count, description) VALUES
('base_instructions', 'always_include', 'You are an AI course authoring assistant...', 320, 'Core system identity and instructions'),
('safety_rules', 'always_include', 'CRITICAL: Never execute tool calls that...', 180, 'Safety guardrails and PII rules'),
('tool_definitions_general', 'contextual', 'The following tools are available...', 450, 'General tool definitions (list_pages, fetch_page, etc.)'),
('tool_definitions_create', 'contextual', 'Tool: propose_create_page\nInput schema:...', 380, 'Create page tool schema'),
('tool_definitions_update', 'contextual', 'Tool: propose_update_page\nInput schema:...', 420, 'Update page tool schema'),
('tool_definitions_delete', 'contextual', 'Tool: propose_delete_page\nInput schema:...', 350, 'Delete page tool and confirmation'),
('tool_definitions_validate', 'contextual', 'Tool: validate_course\nInput schema:...', 290, 'Course validation tool'),
('template_text_content', 'contextual', 'Template: text-content\nSchema: {\n  "title": "string",...', 380, 'Text content template schema'),
('template_tabs', 'contextual', 'Template: tabs\nSchema: {\n  "title": "string",...', 420, 'Tabs template schema'),
('template_accordion', 'contextual', 'Template: accordion\nSchema: {\n  "title": "string",...', 410, 'Accordion template schema'),
('template_click_reveal', 'contextual', 'Template: click-reveal\nSchema: {\n  "title": "string",...', 390, 'Click-to-reveal template schema'),
('template_final_assessment', 'contextual', 'Template: final-assessment\nSchema: {\n  "title": "string",...', 560, 'Final assessment template schema'),
('verbose_examples', 'droppable', 'Example 1: Creating a welcome page...\nExample 2: Updating...', 850, 'Multi-step usage examples'),
('rag_formatting_instructions', 'droppable', 'When using similar_course_query results...', 320, 'RAG result formatting rules'),
('deprecated_tool_notes', 'droppable', 'Note: The legacy create_page tool is deprecated...', 180, 'Deprecation warnings')
ON CONFLICT (section_key) DO NOTHING;


-- Token savings tracking table
CREATE TABLE ai_token_savings (
    id                  SERIAL PRIMARY KEY,
    session_id          VARCHAR(64) NOT NULL,
    chat_turn_id        VARCHAR(64) NOT NULL,
    intent_category     VARCHAR(32) NOT NULL,
    tokens_before       INTEGER NOT NULL,
    tokens_after        INTEGER NOT NULL,
    tokens_saved        INTEGER NOT NULL,
    savings_percent     NUMERIC(5,2) NOT NULL,
    templates_included  TEXT[] NOT NULL DEFAULT '{}',
    tools_included      TEXT[] NOT NULL DEFAULT '{}',
    pruning_latency_ms  NUMERIC(10,2) NOT NULL DEFAULT 0,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    CONSTRAINT fk_session FOREIGN KEY (session_id) REFERENCES ai_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX ix_token_savings_session ON ai_token_savings(session_id);
CREATE INDEX ix_token_savings_intent ON ai_token_savings(intent_category);
CREATE INDEX ix_token_savings_created ON ai_token_savings(created_at);
CREATE INDEX ix_token_savings_aggregate ON ai_token_savings(intent_category, tokens_saved);
```

**Alembic migration pattern:**

```python
"""add ai_prompt_sections and ai_token_savings tables

Revision ID: xxxx_add_ai_prompt_sections
Revises: <parent_revision>
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'xxxx_add_ai_prompt_sections'
down_revision = '<parent_revision>'

def upgrade():
    op.create_table('ai_prompt_sections',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('section_key', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('section_key'),
        sa.CheckConstraint("category IN ('always_include', 'contextual', 'droppable')")
    )
    op.create_index('ix_ai_prompt_sections_category', 'ai_prompt_sections', ['category'])
    op.create_index('ix_ai_prompt_sections_active', 'ai_prompt_sections', ['is_active'])

    op.create_table('ai_token_savings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('chat_turn_id', sa.String(length=64), nullable=False),
        sa.Column('intent_category', sa.String(length=32), nullable=False),
        sa.Column('tokens_before', sa.Integer(), nullable=False),
        sa.Column('tokens_after', sa.Integer(), nullable=False),
        sa.Column('tokens_saved', sa.Integer(), nullable=False),
        sa.Column('savings_percent', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('templates_included', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('tools_included', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('pruning_latency_ms', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['session_id'], ['ai_sessions.session_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_token_savings_session', 'ai_token_savings', ['session_id'])
    op.create_index('ix_token_savings_intent', 'ai_token_savings', ['intent_category'])
    op.create_index('ix_token_savings_created', 'ai_token_savings', ['created_at'])

    # Seed prompt sections
    op.execute("""
        INSERT INTO ai_prompt_sections (section_key, category, content, token_count, description) VALUES
        ('base_instructions', 'always_include', 'You are an AI course authoring assistant...', 320, 'Core system identity and instructions'),
        ('safety_rules', 'always_include', 'CRITICAL: Never execute tool calls that...', 180, 'Safety guardrails and PII rules'),
        ('verbose_examples', 'droppable', 'Example 1: Creating a welcome page...', 850, 'Multi-step usage examples'),
        ('rag_formatting_instructions', 'droppable', 'When using similar_course_query results...', 320, 'RAG result formatting rules')
        ON CONFLICT (section_key) DO NOTHING;
    """)

def downgrade():
    op.drop_index('ix_token_savings_created', table_name='ai_token_savings')
    op.drop_index('ix_token_savings_intent', table_name='ai_token_savings')
    op.drop_index('ix_token_savings_session', table_name='ai_token_savings')
    op.drop_table('ai_token_savings')
    op.drop_index('ix_ai_prompt_sections_active', table_name='ai_prompt_sections')
    op.drop_index('ix_ai_prompt_sections_category', table_name='ai_prompt_sections')
    op.drop_table('ai_prompt_sections')
```

**SQLAlchemy ORM models** (added to `app/models/ai/`):

```python
# app/models/ai/prompt_section.py

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, CheckConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from app.models.base import Base

class AiPromptSection(Base):
    __tablename__ = "ai_prompt_sections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    section_key = Column(String(100), unique=True, nullable=False)
    category = Column(String(20), nullable=False)  # always_include | contextual | droppable
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False, default=0)
    description = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class AiTokenSavings(Base):
    __tablename__ = "ai_token_savings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=False)
    chat_turn_id = Column(String(64), nullable=False)
    intent_category = Column(String(32), nullable=False)
    tokens_before = Column(Integer, nullable=False)
    tokens_after = Column(Integer, nullable=False)
    tokens_saved = Column(Integer, nullable=False)
    savings_percent = Column(Integer, nullable=False)  # scaled by 100 (e.g., 60.50 -> 6050)
    templates_included = Column(ARRAY(Text), nullable=False, default=[])
    tools_included = Column(ARRAY(Text), nullable=False, default=[])
    pruning_latency_ms = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
```

#### 4.4 Service Signatures (Complete)

```python
# app/services/ai/context_pruner.py -- Full implementation

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


class PruningError(Exception):
    """Raised when context pruning fails catastrophically."""


class IntentClassifier:
    """
    Categorizes user intent into one of the known categories.
    
    Uses regex patterns loaded from conf/intent_patterns.yaml.
    If a fast-model classifier is configured (AI_INTENT_CLASSIFIER_MODEL),
    uses that as a fallback for ambiguous prompts.
    """

    # Section-key -> list of compiled patterns
    _INTENT_MAP: dict[str, list[re.Pattern]] = {
        "text_only": [
            re.compile(r, re.IGNORECASE)
            for r in [
                r"\b(rewrite|simplify|expand|shorten|rephrase|paraphrase|polish)\b",
                r"\b(text|content|paragraph|wording|sentence)\b",
                r"\b(tone|style|voice|language|readability)\b",
                r"\b(typo|fix|grammar|spelling|punctuation)\b",
                r"\b(make it (shorter|longer|clearer|simpler))\b",
            ]
        ],
        "assessment": [
            re.compile(r, re.IGNORECASE)
            for r in [
                r"\b(quiz|test|assessment|exam|question|mcq|multiple.choice)\b",
                r"\b(score|passing|grade|correct|answer|wrong)\b",
                r"\b(final.assessment)\b",
                r"\b(add a question|create a quiz|make a test)\b",
            ]
        ],
        "navigation": [
            re.compile(r, re.IGNORECASE)
            for r in [
                r"\b(reorder|move|rearrange|sequence|order|swap)\b",
                r"\b(navigate|flow|progression|path|linear)\b",
                r"\b(move (up|down|before|after|to))\b",
            ]
        ],
        "create_page": [
            re.compile(r, re.IGNORECASE)
            for r in [
                r"\b(add a page|create a page|new page|insert page)\b",
                r"\b(make a (welcome|summary|content|video) page\b)",
                r"\b(create a new (section|slide))\b",
            ]
        ],
        "delete_page": [
            re.compile(r, re.IGNORECASE)
            for r in [
                r"\b(delete|remove|destroy|erase) (page|slide)\b",
                r"\b(get rid of|eliminate)\b",
            ]
        ],
    }

    def __init__(self):
        self._confidence_threshold = float(
            os.getenv("AI_INTENT_CONFIDENCE_THRESHOLD", "0.4")
        )

    def classify(
        self, prompt: str, last_page_focused: Optional[str] = None
    ) -> IntentClassification:
        """Classify user intent from prompt text."""
        scores: dict[str, float] = {}
        matched_keywords: list[str] = []

        for category, patterns in self._INTENT_MAP.items():
            matches = 0
            for pat in patterns:
                found = pat.findall(prompt)
                matches += len(found)
                matched_keywords.extend(found)
            if matches > 0:
                # Score = matches / total_patterns (normalized)
                scores[category] = matches / len(patterns)

        if not scores:
            return IntentClassification(
                category="unknown",
                confidence=0.0,
                mentioned_template_types=[],
                mentioned_tools=[],
                detected_keywords=[],
            )

        best_category = max(scores, key=scores.get)
        best_score = scores[best_category]

        # If multiple categories score similarly, mark as mixed
        runner_up = sorted(scores.values(), reverse=True)
        if len(runner_up) > 1 and runner_up[1] > best_score * 0.8:
            best_category = "mixed"

        return IntentClassification(
            category=best_category,
            confidence=best_score,
            mentioned_template_types=self._extract_template_types(prompt),
            mentioned_tools=self._extract_tools(prompt),
            detected_keywords=list(set(matched_keywords)),
        )

    def _extract_template_types(self, prompt: str) -> list[str]:
        """Detect template types mentioned in the prompt."""
        known = {
            "text.content": r"\b(text.content|text|content)\b",
            "tabs": r"\b(tabs?)\b",
            "accordion": r"\b(accordion|expandable|collapsible)\b",
            "click.reveal": r"\b(click.reveal|click to reveal|reveal)\b",
            "final.assessment": r"\b(final.assessment|assessment|quiz)\b",
            "mcq": r"\b(mcq|multiple choice|quiz question)\b",
        }
        found = []
        for ttype, pat_str in known.items():
            if re.search(pat_str, prompt, re.IGNORECASE):
                found.append(ttype)
        return found

    def _extract_tools(self, prompt: str) -> list[str]:
        """Detect tool names mentioned in the prompt."""
        tools = [
            "propose_create_page", "propose_update_page",
            "propose_delete_page", "validate_course",
            "query_similar_courses", "analyze_document_for_import",
        ]
        return [t for t in tools if t.replace("_", " ") in prompt.lower()]


class ContextPruner:
    """
    Prunes system prompt sections based on user intent and course context.
    
    Caches relevance decisions per session for AI_CONTEXT_CACHE_TTL seconds.
    """

    # Tools always included regardless of intent
    ALWAYS_TOOLS = {"create_session", "list_pages", "fetch_page", "validate_course"}

    # Templates always included if present in the course
    ALWAYS_TEMPLATES = {"final-assessment"}  # safety: assessment schema always needed if course has assessment pages

    def __init__(
        self,
        template_registry,
        intent_classifier: IntentClassifier,
        prompt_assembler,
        token_counter,
    ):
        self._template_registry = template_registry
        self._intent_classifier = intent_classifier
        self._prompt_assembler = prompt_assembler
        self._token_counter = token_counter
        self._cache: dict[str, tuple[float, PruningDecision]] = {}
        self._cache_ttl = float(os.getenv("AI_CONTEXT_CACHE_TTL", "30"))

    async def build_pruned_prompt(
        self,
        context: PruningContext,
        conversation_history: list[dict],
        system_prompt_fragments: dict[str, str],
    ) -> tuple[str, PruningDecision]:
        """
        Build a pruned system prompt.
        
        Raises PruningError if the pruning pipeline fails (orchestrator
        should fall back to full context in this case).
        """
        try:
            # Check cache
            cache_key = f"{context.session_id}:{context.user_prompt[:50]}"
            if cache_key in self._cache:
                ts, decision = self._cache[cache_key]
                if (time.monotonic() - ts) < self._cache_ttl:
                    return self._prompt_assembler.assemble(
                        system_prompt_fragments,
                        self._decision_to_sections(decision, system_prompt_fragments)
                    ), decision

            t0 = time.monotonic()

            intent = await self._intent_classifier.classify(
                context.user_prompt, context.last_page_focused
            )

            relevant_templates = await self._select_relevant_templates(
                intent, context.course_template_types
            )
            relevant_tools = self._select_relevant_tools(
                intent, context.available_tool_names
            )

            included = self._determine_sections(
                intent, relevant_templates, relevant_tools,
                list(system_prompt_fragments.keys())
            )

            pruned_prompt = self._prompt_assembler.assemble(
                system_prompt_fragments, included
            )

            tokens_before = self._token_counter.count(
                self._prompt_assembler.assemble_all(system_prompt_fragments)
            )
            tokens_after = self._token_counter.count(pruned_prompt)

            decision = PruningDecision(
                relevant_template_types=relevant_templates,
                relevant_tool_names=relevant_tools,
                always_include_sections=included.get("always", []),
                contextual_sections_included=included.get("contextual", []),
                droppable_sections_included=included.get("droppable", []),
                total_input_tokens_before=tokens_before,
                total_input_tokens_after=tokens_after,
                pruning_latency_ms=(time.monotonic() - t0) * 1000,
                intent_category=intent.category,
            )

            # Update cache
            self._cache[cache_key] = (time.monotonic(), decision)

            return pruned_prompt, decision

        except Exception as e:
            logger.error("Context pruning failed: %s", str(e), exc_info=True)
            raise PruningError(str(e)) from e

    async def _select_relevant_templates(
        self, intent: IntentClassification, course_types: list[str]
    ) -> list[str]:
        """
        Select template schemas relevant to the current intent.
        
        For "text_only" intent: include text-content and summary templates.
        For "assessment" intent: include final-assessment and mcq.
        For "mixed" or "unknown": include all course templates + 1 extra (conservative).
        """
        intent_to_templates = {
            "text_only": {"text-content", "content-video", "summary"},
            "assessment": {"final-assessment", "mcq"},
            "navigation": {"text-content", "summary"},
            "create_page": set(course_types),  # all course types when creating
            "delete_page": set(),  # no template schemas needed for delete
        }

        selected = intent_to_templates.get(intent.category, set(course_types))
        # Always include final-assessment if course has it
        if "final-assessment" in course_types:
            selected.add("final-assessment")

        # Intersect with what the course actually uses
        return [t for t in selected if t in course_types]

    def _select_relevant_tools(
        self, intent: IntentClassification, available: list[str]
    ) -> list[str]:
        """Select tools relevant to the current intent."""
        intent_to_tools = {
            "text_only": {"propose_update_page", "validate_course"},
            "assessment": {"propose_create_page", "propose_update_page", "validate_course"},
            "navigation": {"propose_update_page", "validate_course"},
            "create_page": {"propose_create_page", "validate_course"},
            "delete_page": {"propose_delete_page", "validate_course"},
        }
        selected = intent_to_tools.get(intent.category, set(available))
        # Always include baseline tools
        selected |= self.ALWAYS_TOOLS
        return [t for t in selected if t in available]

    def _determine_sections(
        self,
        intent: IntentClassification,
        templates: list[str],
        tools: list[str],
        all_section_keys: list[str] | None = None,
    ) -> dict[str, list[str]]:
        """
        Map intent + selections to section keys.
        
        Section keys follow naming convention:
          - "base_instructions" -> always_include
          - "safety_rules" -> always_include
          - "tool_<tool_name>" -> contextual
          - "template_<template_type>" -> contextual
          - "verbose_examples" -> droppable
          - "rag_formatting_instructions" -> droppable
          - "deprecated_*" -> droppable
        """
        always = ["base_instructions", "safety_rules"]

        contextual = []
        for t in tools:
            sk = f"tool_{t}"
            if not all_section_keys or sk in all_section_keys:
                contextual.append(sk)
        for tmpl in templates:
            sk = f"template_{tmpl}"
            if not all_section_keys or sk in all_section_keys:
                contextual.append(sk)

        droppable = []
        if intent.category == "unknown":
            # For unknown intent, include verbose examples to guide the model
            pass  # no droppable sections for unknown intent

        return {"always": always, "contextual": contextual, "droppable": droppable}

    def _decision_to_sections(
        self, decision: PruningDecision, fragments: dict[str, str]
    ) -> dict[str, list[str]]:
        """Rehydrate section keys from a cached decision."""
        all_keys = set(fragments.keys())
        return {
            "always": [s for s in decision.always_include_sections if s in all_keys],
            "contextual": [
                s for s in decision.contextual_sections_included if s in all_keys
            ],
            "droppable": [
                s for s in decision.droppable_sections_included if s in all_keys
            ],
        }
```

#### 4.5 Environment Variables

```ini
# .env additions for Context Pruning

# Intent classifier
AI_INTENT_CONFIDENCE_THRESHOLD=0.4
AI_INTENT_CLASSIFIER_MODEL=claude-3-haiku-20240307  # optional fast-model fallback

# Cache
AI_CONTEXT_CACHE_TTL=30  # seconds

# Pruning constraints
AI_MIN_TEMPLATE_SCHEMAS=3       # minimum template schemas to include
AI_MIN_TOOLS=4                  # minimum tools to include
AI_PRUNE_ENABLED=true           # master toggle for pruning
AI_PRUNE_DROPPABLE_ENABLED=true # enable removal of droppable sections

# Token counting
AI_TOKEN_ENCODING=cl100k_base   # tiktoken encoding name

# Logging / observability
AI_TOKEN_SAVINGS_LOG_SAMPLE_RATE=1.0  # 0.0-1.0, fraction of turns to log savings

# Fallback
AI_PRUNE_FALLBACK_TO_FULL=true  # if pruner fails, fall back to full prompt
```

#### 4.6 Integration Points

**Changes to `chat_orchestrator.py` (US-AI-023):**

```python
# Inside app/services/ai/chat_orchestrator.py

class ChatOrchestrator:
    def __init__(self, context_pruner: ContextPruner, ...):
        self._context_pruner = context_pruner
        self._prune_enabled = os.getenv("AI_PRUNE_ENABLED", "true").lower() == "true"
        self._fallback_to_full = os.getenv("AI_PRUNE_FALLBACK_TO_FULL", "true").lower() == "true"
        self._sample_rate = float(os.getenv("AI_TOKEN_SAVINGS_LOG_SAMPLE_RATE", "1.0"))

    async def process_turn(self, session, prompt, ...):
        # ... existing setup ...
        
        system_prompt = self._build_base_system_prompt(session)
        
        if self._prune_enabled:
            try:
                pruning_context = PruningContext(
                    session_id=session.session_id,
                    course_id=session.course_id,
                    user_prompt=prompt,
                    active_proposal_ids=session.active_proposal_ids,
                    last_page_focused=session.last_page_focused,
                    course_template_types=await self._get_course_types(session.course_id),
                    available_tool_names=list(self._tool_registry.list_all()),
                )
                system_prompt, prune_decision = await self._context_pruner.build_pruned_prompt(
                    pruning_context, conversation_history, self._system_prompt_fragments
                )
                
                # Log savings (sampled)
                if random.random() < self._sample_rate:
                    await self._log_token_savings(session, turn_id, prune_decision)
                    
            except PruningError:
                if self._fallback_to_full:
                    logger.warning("Pruner failed, using full context (session=%s)", session.session_id)
                    system_prompt = self._build_base_system_prompt(session)
                else:
                    raise
        
        # Continue with LLM interaction using (potentially pruned) system_prompt
        ...
```

**Changes to `tool_registry.py` to support relevance tagging:**

```python
# Tools now carry a 'relevance_tags' field
@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    idempotent: bool
    permission_scope: str
    relevance_tags: list[str]  # e.g., ["read", "write", "create", "delete", "assessment"]
```

**Integration with the frontend (US-AI-024):**

The frontend receives pruning metadata in the chat response:

```json
{
  "response": "I've updated the text content...",
  "session_summary": {...},
  "tool_call_trace": [...],
  "pruning_metadata": {
    "tokens_saved": 5200,
    "savings_percent": 62.5,
    "intent_classified": "text_only",
    "templates_included": ["text-content"],
    "tools_included": ["propose_update_page", "validate_course", "list_pages", "fetch_page"]
  }
}
```

### 5. Edge Cases & Failure Modes

| Edge Case | Behavior |
|---|---|
| **User prompt is empty** | Classify as "unknown", fall back to full context. Log warning. |
| **Course has no templates** | Include minimum set (AI_MIN_TEMPLATE_SCHEMAS=3) of common schemas as defaults. |
| **All templates excluded by pruning** | Fall back to full context. Log as error with alert. |
| **Pruner raises exception** | If AI_PRUNE_FALLBACK_TO_FULL=true, fall back to full context silently. Else propagate. |
| **Session removed from cache** | Re-prune on next turn. Acceptable latency cost (<50ms). |
| **tiktoken not installed** | Fall back to character-based estimation (len/4). Log install suggestion once. |
| **Intent classification very low confidence** | Default to "mixed" which includes all course templates + all baseline tools. |
| **Concurrent turns on same session** | Each turn is pruned independently; cache key includes prompt prefix to avoid stale decisions. |
| **User switches topic mid-session** | Each turn is classified independently. Intent can change turn-to-turn. Only the cache within 30s causes reuse. |

### 6. Performance & Observability

**Metrics:**

```python
# Prometheus metrics (app/services/ai/metrics.py or using existing observability)

context_prune_decisions_total = Counter(
    "ai_context_prune_decisions_total",
    "Total context pruning decisions",
    ["intent_category", "outcome"],  # outcome: success | fallback | error
)

context_prune_tokens_saved = Histogram(
    "ai_context_prune_tokens_saved",
    "Tokens saved per session turn",
    buckets=[100, 500, 1000, 2000, 5000, 10000],
)

context_prune_latency = Histogram(
    "ai_context_prune_latency_ms",
    "Context pruning latency in milliseconds",
    buckets=[5, 10, 25, 50, 100, 250],
)

context_prune_savings_percent = Histogram(
    "ai_context_prune_savings_percent",
    "Token savings as percentage of full context",
    buckets=[10, 20, 30, 40, 50, 60, 70, 80],
)
```

**Expected Latency Budget:**

| Component | Target (p50) | Max (p99) |
|---|---|---|
| Intent classification | 2ms | 20ms |
| Template relevance | 5ms | 30ms |
| Prompt assembly | 1ms | 5ms |
| Token counting | 5ms | 50ms |
| **Total pruning overhead** | **13ms** | **105ms** |

Acceptable overhead: < 100ms p99. If exceeded, disable pruning per-turn and log alert.

**Query for Cost Dashboard:**

```sql
-- Aggregate token savings by day and intent category
SELECT
    DATE(created_at) AS day,
    intent_category,
    COUNT(*) AS turns,
    SUM(tokens_saved) AS total_tokens_saved,
    AVG(savings_percent) AS avg_savings_pct,
    AVG(pruning_latency_ms) AS avg_latency_ms
FROM ai_token_savings
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY day, intent_category
ORDER BY day DESC;
```

**Alerting Rules:**

- `ai_context_prune_decisions_total{outcome="error"} > 10` in 5 minutes -> PagerDuty warning
- `context_prune_savings_percent < 10` for 1 hour at > 50 requests -> investigate pruning effectiveness
- `context_prune_latency > 100` p99 for 10 minutes -> possible regression in intent classifier

### 7. Test Scenarios

#### 7.1 Unit Tests (`tests/services/ai/test_context_pruner.py`)

```python
# Minimum test coverage: 25+ test cases across all classes

class TestIntentClassifier:
    async def test_classify_text_only_rewrite(self):
        prompt = "Simplify this text content on page 2"
        result = IntentClassifier().classify(prompt)
        assert result.category == "text_only"
        assert result.confidence > 0

    async def test_classify_assessment_quiz(self):
        prompt = "Add a quiz question about machine learning"
        result = IntentClassifier().classify(prompt)
        assert result.category == "assessment"
        assert "mcq" in result.mentioned_template_types

    async def test_classify_empty_prompt(self):
        result = IntentClassifier().classify("")
        assert result.category == "unknown"
        assert result.confidence == 0.0

    async def test_classify_delete_page(self):
        result = IntentClassifier().classify("Delete the second page")
        assert result.category == "delete_page"

    async def test_classify_mixed_intent(self):
        result = IntentClassifier().classify(
            "Simplify the quiz text on page 3"
        )
        assert result.category == "mixed"  # both text_only and assessment match

    async def test_classify_mentioned_templates(self):
        result = IntentClassifier().classify(
            "Create a tabs page and an accordion page"
        )
        assert "tabs" in result.mentioned_template_types
        assert "accordion" in result.mentioned_template_types

    async def test_extract_tools_from_prompt(self):
        result = IntentClassifier().classify(
            "I want to propose creating a new page"
        )
        assert "propose_create_page" in result.mentioned_tools


class TestContextPruner:
    async def test_prune_text_only_keeps_text_content_only(self):
        course_types = ["text-content", "tabs", "accordion", "final-assessment"]
        intent = IntentClassification("text_only", 0.8, [], [], [])
        pruner = ContextPruner(...)
        templates = await pruner._select_relevant_templates(intent, course_types)
        assert "tabs" not in templates
        assert "accordion" not in templates
        assert "text-content" in templates
        assert "final-assessment" in templates  # always included if course has it

    async def test_prune_assessment_keeps_final_assessment_and_mcq(self):
        course_types = ["text-content", "mcq", "final-assessment", "tabs"]
        intent = IntentClassification("assessment", 0.9, [], [], [])
        pruner = ContextPruner(...)
        templates = await pruner._select_relevant_templates(intent, course_types)
        assert "mcq" in templates
        assert "final-assessment" in templates
        assert "text-content" not in templates
        assert "tabs" not in templates

    async def test_tools_always_include_baseline(self):
        available = ["propose_create_page", "propose_delete_page", "list_pages",
                     "fetch_page", "validate_course"]
        intent = IntentClassification("delete_page", 0.9, [], [], [])
        pruner = ContextPruner(...)
        tools = pruner._select_relevant_tools(intent, available)
        assert "list_pages" in tools
        assert "fetch_page" in tools
        assert "validate_course" in tools
        assert "propose_delete_page" in tools  # relevant to delete intent

    async def test_prune_empty_course_types_fallsback(self):
        intent = IntentClassification("unknown", 0.0, [], [], [])
        pruner = ContextPruner(...)
        templates = await pruner._select_relevant_templates(intent, ["text-content"])
        assert len(templates) >= 1

    async def test_build_pruned_prompt_reduces_tokens(self):
        fragments = {
            "base_instructions": "You are an AI assistant...",
            "safety_rules": "Never execute...",
            "tool_list_pages": "Tool: list_pages...",
            "tool_propose_create": "Tool: propose_create_page...",
            "tool_propose_delete": "Tool: propose_delete_page...",
            "template_text_content": "Template: text-content...",
            "template_tabs": "Template: tabs...",
            "template_accordion": "Template: accordion...",
            "verbose_examples": "Example 1:...",
        }
        context = PruningContext(
            session_id="s1", course_id="c1",
            user_prompt="Simplify the text", active_proposal_ids=[],
            last_page_focused=None,
            course_template_types=["text-content", "tabs"],
            available_tool_names=["list_pages", "fetch_page", "validate_course",
                                  "propose_create_page", "propose_update_page",
                                  "propose_delete_page"],
        )
        pruner = ContextPruner(...)
        prompt, decision = await pruner.build_pruned_prompt(
            context, [], fragments
        )
        assert decision.total_input_tokens_after < decision.total_input_tokens_before
        assert decision.intent_category == "text_only"
        assert "verbose_examples" not in prompt
        assert "propose_delete_page" not in prompt  # irrelevant to text_only

    async def test_cache_reuses_decision_within_ttl(self):
        # Mock time.monotonic and verify same prompt within 30s reuses cached decision
        ...

    async def test_cache_expired_after_ttl(self):
        # Mock time.monotonic and verify prompt after 31s gets re-pruned
        ...

    async def test_pruner_raises_on_template_registry_failure(self):
        with pytest.raises(PruningError):
            await pruner.build_pruned_prompt(...)

    async def test_fallback_to_full_on_prune_failure(self):
        # When orchestrator catches PruningError, verify it uses full prompt
        ...


class TestTokenCounter:
    async def test_tiktoken_count_accuracy(self):
        counter = TokenCounter()
        text = "Hello, this is a test sentence."
        count = counter.count(text)
        assert count > 0
        assert isinstance(count, int)

    async def test_fallback_count_when_tiktoken_missing(self):
        # Simulate ImportError
        with patch("builtins.__import__", side_effect=ImportError):
            counter = TokenCounter()
            count = counter.count("test text")
            assert count > 0


class TestPromptAssembler:
    async def test_assembly_order(self):
        assembler = PromptAssembler()
        fragments = {
            "a": "Section A",
            "b": "Section B",
            "c": "Section C",
        }
        included = {"always": ["a"], "contextual": ["b"], "droppable": ["c"]}
        result = assembler.assemble(fragments, included)
        assert result.index("Section A") < result.index("Section B")
        assert result.index("Section B") < result.index("Section C")

    async def test_assemble_all_includes_everything(self):
        assembler = PromptAssembler()
        fragments = {"a": "X", "b": "Y"}
        result = assembler.assemble_all(fragments)
        assert "X" in result
        assert "Y" in result
```

#### 7.2 Integration Tests (`tests/services/ai/test_context_pruner_integration.py`)

```python
class TestPrunerOrchestratorIntegration:
    async def test_full_pipeline_with_mock_db(self):
        """Verify pruner reads template types from the database."""
        ...

    async def test_token_savings_logged_to_db(self):
        """Verify AiTokenSavings record is created after pruning."""
        ...

    async def test_intent_classifier_with_fast_model_fallback(self):
        """If configured, fast model is called for ambiguous prompts."""
        ...

    async def test_prompt_sections_loaded_from_db(self):
        """Verify sections from ai_prompt_sections table are loaded."""
        ...
```

#### 7.3 E2E Tests (`tests/e2e/test_context_pruning.py`)

```python
class TestContextPruningE2E:
    async def test_chat_turn_with_pruning_returns_savings_metadata(self):
        """Send a chat message and verify response includes pruning_metadata."""
        response = await client.post("/api/v1/ai/chat", json={
            "session_id": session_id,
            "course_id": course_id,
            "prompt": "Simplify the welcome page text",
        })
        assert response.status_code == 200
        data = response.json()
        assert "pruning_metadata" in data
        assert data["pruning_metadata"]["tokens_saved"] > 0

    async def test_pruned_and_full_prompts_produce_equivalent_quality(self):
        """Compare template validation error rates for pruned vs full prompts."""
        # Run N turns with pruning, N turns without
        # Assert no statistically significant difference in validation error rate
        ...

    async def test_pruning_disabled_via_env_var(self):
        """With AI_PRUNE_ENABLED=false, verify full context is always used."""
        ...

    async def test_pruning_cache_hit_returns_same_decision(self):
        """Two rapid requests with same prompt produce same pruning decision."""
        ...
```

#### 7.4 Performance Tests

```python
@pytest.mark.benchmark
async def test_pruning_overhead_budget():
    """Verify pruning adds <100ms p99 overhead."""
    pruner = ContextPruner(...)
    start = time.monotonic()
    for _ in range(100):
        await pruner.build_pruned_prompt(context, [], fragments)
    elapsed = (time.monotonic() - start) * 1000 / 100
    assert elapsed < 100, f"Average pruning time {elapsed:.1f}ms exceeds 100ms budget"
```

### 8. Task Breakdown

**Sprint 1: Core Pruner (5 story points)**

| ID | Task | Owner | Effort | Dependencies |
|---|---|---|---|---|
| T1 | Create `prompt_sections/` directory with section templates | Backend | 1 SP | US-AI-023 |
| T2 | Implement `TokenCounter` with tiktoken + fallback | Backend | 0.5 SP | None |
| T3 | Implement `IntentClassifier` with regex patterns | Backend | 1 SP | None |
| T4 | Implement `PromptAssembler` | Backend | 0.5 SP | T1 |
| T5 | Implement `ContextPruner` main orchestration | Backend | 1.5 SP | T2, T3, T4 |
| T6 | Create `AiPromptSection` and `AiTokenSavings` ORM models | Backend | 0.5 SP | None |
| T7 | Write Alembic migration for new tables + seed data | Backend | 0.5 SP | T6 |
| T8 | Unit tests for IntentClassifier (8 scenarios) | QA/Backend | 0.5 SP | T3 |
| T9 | Unit tests for ContextPruner (12 scenarios) | QA/Backend | 1 SP | T5 |

**Sprint 2: Integration & Hardening (5 story points)**

| ID | Task | Owner | Effort | Dependencies |
|---|---|---|---|---|
| T10 | Integrate ContextPruner into ChatOrchestrator | Backend | 1.5 SP | T5, US-AI-023 |
| T11 | Add pruning_metadata to chat response | Backend | 0.5 SP | T10 |
| T12 | Implement savings logging to `ai_token_savings` table | Backend | 0.5 SP | T7, T10 |
| T13 | Add environment variable configuration | Backend | 0.5 SP | T10 |
| T14 | Add Prometheus metrics for pruning observability | Backend/DevOps | 0.5 SP | T10 |
| T15 | Integration tests: pruner + DB | QA | 1 SP | T7, T10 |
| T16 | E2E tests: quality equivalence check | QA | 1 SP | T10, T15 |
| T17 | Performance benchmarks (100ms p99 budget) | QA | 0.5 SP | T10 |
| T18 | Update deployment documentation with new env vars | Docs | 0.5 SP | T13 |
| T19 | Create cost-dashboard query for token savings | DevOps/Analytics | 0.5 SP | T12 |

**Total: 10 story points (2 sprints)**

### Acceptance Criteria (Final Checklist)

- [ ] `AI_PRUNE_ENABLED=true` reduces average input tokens by >= 50% measured across 100 chat turns.
- [ ] `AI_PRUNE_ENABLED=false` results in identical behavior to pre-pruning baseline.
- [ ] Validation error rate with pruning enabled is within +/- 2% of pruning-disabled baseline (n>=500).
- [ ] Pruner adds <100ms p99 latency overhead.
- [ ] All 25+ unit tests pass in CI.
- [ ] Integration tests verify token savings are persisted to `ai_token_savings` table.
- [ ] Cost dashboard query returns daily/weekly/monthly token savings.
- [ ] Environment variables documented in `.env.example` and deployment runbook.
- [ ] Fallback to full context works when pruner raises an exception.
- [ ] Metrics emitted and visible in Grafana (or equivalent monitoring).
- [ ] Session cache (30s TTL) verified in tests.

---